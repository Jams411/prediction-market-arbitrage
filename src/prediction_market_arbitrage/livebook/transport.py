"""WebSocket transport boundary + connection / reconnect / resync manager
(Milestone M2.1).

This is the seam between a real authenticated socket and the deterministic
:class:`~.state.LiveBookFeed`. The socket itself is **not implemented here** —
both venues' market-data WebSockets require credentialed handshakes
(``docs/API_SOURCES.md`` K-WS-AUTH-*, P-WS-AUTH-*) and a WebSocket client
library; a concrete :class:`WebSocketTransport` is a caller/deployment concern
(see the blocker in ``API_SOURCES.md``). What lives here is:

- :class:`WebSocketTransport` / :class:`SnapshotSource` protocols (the seam),
- :class:`BackoffPolicy` (pure, deterministic reconnect delays),
- frame decoders that dispatch a raw venue frame to the M2.1 update decoders,
- :class:`LiveBookConnection` — connect → subscribe → pump frames into feeds;
  on disconnect → ``mark_disconnected`` → backoff reconnect → REST snapshot
  resync → ``begin_resync`` + ``apply_snapshot`` → back to ``HEALTHY``.

Every effect (socket, REST fetch, clock, sleep) is injected, so the manager is
driven step-by-step and asserted on in tests with fakes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from . import kalshi_ws, polymarket_us_ws
from .errors import LiveBookError
from .state import FeedHealth, LiveBookFeed
from .updates import BookDelta, BookSnapshot
from .ws_auth import Handshake

Update = BookSnapshot | BookDelta
FrameDecoder = Callable[[Mapping[str, object]], Sequence[Update]]
Clock = Callable[[], datetime]


class TransportClosed(Exception):
    """The socket is gone (clean close, reset, or read past EOF). Expected — the
    manager reconnects. Not a :class:`LiveBookError` (which is misuse)."""


class WebSocketTransport(Protocol):
    """Synchronous WebSocket seam. A real implementation wraps an actual client
    (the Kalshi / Polymarket US docs use the ``websockets`` library) and is
    supplied by the caller; this package ships no networked implementation."""

    def connect(self, handshake: Handshake) -> None: ...

    def send(self, text: str) -> None: ...

    def receive(self) -> str:
        """Block until the next text frame. Raise :class:`TransportClosed` when
        the connection has ended."""
        ...

    def close(self) -> None: ...


class SnapshotSource(Protocol):
    """Fetches a fresh REST order-book snapshot for one contract — the resync
    path back to ``HEALTHY`` after a reconnect. Implemented by wrapping the
    M1.2 / M1.3 REST adapters."""

    def fetch(self, contract_id: str) -> BookSnapshot: ...


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Deterministic exponential backoff. ``delay(attempt)`` for attempt
    ``0, 1, 2, ...`` is ``min(max_seconds, base_seconds * factor**attempt)``."""

    base_seconds: float = 1.0
    factor: float = 2.0
    max_seconds: float = 30.0
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if self.base_seconds <= 0 or self.factor < 1 or self.max_seconds < self.base_seconds:
            raise LiveBookError("BackoffPolicy: need base>0, factor>=1, max>=base")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise LiveBookError("BackoffPolicy.max_attempts must be >= 1 or None")

    def delay(self, attempt: int) -> float:
        if attempt < 0:
            raise LiveBookError("BackoffPolicy.delay: attempt must be >= 0")
        return min(self.max_seconds, self.base_seconds * (self.factor**attempt))

    def give_up(self, attempt: int) -> bool:
        return self.max_attempts is not None and attempt >= self.max_attempts


# --------------------------------------------------------------------------- #
# Frame decoders — raw venue frame -> M2.1 updates (control frames -> [])
# --------------------------------------------------------------------------- #


def kalshi_frame_decoder(frame: Mapping[str, object]) -> Sequence[Update]:
    """``orderbook_snapshot`` / ``orderbook_delta`` -> updates; ``ok`` / ``error``
    / anything else (acks, other channels) -> ``[]``."""
    frame_type = frame.get("type")
    if frame_type == "orderbook_snapshot":
        return list(kalshi_ws.decode_orderbook_snapshot(frame))
    if frame_type == "orderbook_delta":
        return list(kalshi_ws.decode_orderbook_delta(frame))
    return []


def polymarket_us_frame_decoder(frame: Mapping[str, object]) -> Sequence[Update]:
    """A ``SUBSCRIPTION_TYPE_MARKET_DATA`` frame with a ``marketData`` object ->
    one snapshot; acks / lite / trade frames -> ``[]``."""
    if (
        frame.get("subscriptionType") == "SUBSCRIPTION_TYPE_MARKET_DATA"
        and isinstance(frame.get("marketData"), Mapping)
    ):
        return [polymarket_us_ws.decode_market_data(frame)]
    return []


# --------------------------------------------------------------------------- #
# Connection manager
# --------------------------------------------------------------------------- #


class LiveBookConnection:
    """Drives a set of :class:`LiveBookFeed`s (one per tracked contract) from one
    authenticated WebSocket connection, with reconnect + REST resync."""

    def __init__(
        self,
        *,
        venue: str,
        feeds: Sequence[LiveBookFeed],
        transport: WebSocketTransport,
        handshake_factory: Callable[[], Handshake],
        subscribe_command: Mapping[str, object],
        decode: FrameDecoder,
        snapshot_source: SnapshotSource,
        clock: Clock,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        if not feeds:
            raise LiveBookError("LiveBookConnection needs at least one feed")
        by_id: dict[str, LiveBookFeed] = {}
        for feed in feeds:
            if feed.venue != venue:
                raise LiveBookError(
                    f"feed venue {feed.venue!r} does not match connection venue {venue!r}"
                )
            if feed.contract.id in by_id:
                raise LiveBookError(f"duplicate feed for contract {feed.contract.id!r}")
            by_id[feed.contract.id] = feed
        self.venue = venue
        self._feeds = by_id
        self._transport = transport
        self._handshake_factory = handshake_factory
        self._subscribe_command = dict(subscribe_command)
        self._decode = decode
        self._snapshots = snapshot_source
        self._clock = clock
        self._backoff = backoff if backoff is not None else BackoffPolicy()

    # -- discrete steps (each is deterministic given the injected effects) -- #

    def connect_and_subscribe(self) -> None:
        self._transport.connect(self._handshake_factory())
        self._transport.send(json.dumps(self._subscribe_command))

    def pump_one(self) -> tuple[Update, ...]:
        """Read one frame, decode it, route each update to its feed by
        ``contract_id``. Returns the updates that were applied (``()`` for a
        control frame or an update for an untracked contract). Propagates
        :class:`TransportClosed`."""
        raw = self._transport.receive()
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LiveBookError(f"transport delivered non-JSON frame: {exc}") from exc
        if not isinstance(frame, Mapping):
            raise LiveBookError("transport frame is not a JSON object")

        applied: list[Update] = []
        received_at = self._now()
        for update in self._decode(frame):
            feed = self._feeds.get(update.contract_id)
            if feed is None:
                continue
            if isinstance(update, BookSnapshot):
                feed.apply_snapshot(update, received_at=received_at)
            else:
                feed.apply_delta(update, received_at=received_at)
            applied.append(update)
        return tuple(applied)

    def handle_disconnect(self) -> None:
        at = self._now()
        for feed in self._feeds.values():
            feed.mark_disconnected(at=at)

    def reconnect(self, sleep: Callable[[float], None]) -> int:
        """Reconnect with backoff. Returns the attempt count that succeeded;
        raises :class:`TransportClosed` if ``BackoffPolicy.max_attempts`` is hit."""
        attempt = 0
        while True:
            try:
                self.connect_and_subscribe()
                return attempt
            except TransportClosed:
                if self._backoff.give_up(attempt):
                    raise
                sleep(self._backoff.delay(attempt))
                attempt += 1

    def resync(self) -> dict[str, FeedHealth]:
        """REST-snapshot every feed and return to ``HEALTHY``. Call after a
        successful :meth:`reconnect`."""
        out: dict[str, FeedHealth] = {}
        for contract_id, feed in self._feeds.items():
            feed.begin_resync(at=self._now())
            snapshot = self._snapshots.fetch(contract_id)
            if snapshot.contract_id != contract_id:
                raise LiveBookError(
                    f"snapshot source returned {snapshot.contract_id!r} for {contract_id!r}"
                )
            feed.apply_snapshot(snapshot, received_at=self._now())
            out[contract_id] = feed.health(self._now())
        return out

    def run_forever(
        self, sleep: Callable[[float], None], *, should_continue: Callable[[], bool] = lambda: True
    ) -> None:
        """Connect, then pump frames until ``should_continue()`` is false,
        reconnecting + resyncing on every :class:`TransportClosed`. The only
        loop in this module; ``sleep`` and ``should_continue`` are injected so a
        test can bound it."""
        self.connect_and_subscribe()
        while should_continue():
            try:
                self.pump_one()
            except TransportClosed:
                self.handle_disconnect()
                self.reconnect(sleep)
                self.resync()

    # -- introspection ------------------------------------------------- #

    def feed_health(self) -> dict[str, FeedHealth]:
        now = self._now()
        return {cid: feed.health(now) for cid, feed in self._feeds.items()}

    def all_healthy(self) -> bool:
        return all(h.trading_enabled for h in self.feed_health().values())

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime):
            raise LiveBookError("injected clock() must return a datetime")
        return now
