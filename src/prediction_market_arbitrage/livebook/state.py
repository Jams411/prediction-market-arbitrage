"""Deterministic live-book state machine and fail-closed health (Milestone M2.1).

Consumes venue-neutral :class:`~.updates.BookSnapshot` / :class:`~.updates.BookDelta`
messages (decoded from Kalshi / Polymarket US WebSocket frames elsewhere) and
maintains one contract's normalized book, plus a health verdict that a strategy
or trading layer must gate on.

Design (mirrors the M1.5 engine): pure, no I/O, **no wall-clock** — every method
that needs "now" takes an injected timezone-aware ``datetime``. All quantities
and prices are exact :class:`~decimal.Decimal`. Domain invariants are enforced by
constructing a real :class:`~prediction_market_arbitrage.domain.OrderBook`.

Fail-closed rule: ``FeedHealth.trading_enabled`` is ``True`` **only** for
:attr:`HealthStatus.HEALTHY`. Uninitialized, stale, disconnected, resyncing,
desynced, or not-open feeds all disable trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from prediction_market_arbitrage.domain import (
    Contract,
    DomainValidationError,
    OrderBook,
    PriceLevel,
)

from .errors import LiveBookError
from .updates import BookDelta, BookSnapshot, Side, require_aware_dt

_ZERO = Decimal(0)

#: Polymarket US ``state`` values that permit trading. Anything else the feed
#: reports (pre-open, suspended, halted, expired, terminated, closing auction) is
#: treated as not-open. A feed that reports **no** state (Kalshi's orderbook
#: channel) is not gated on this — state comes from a separate channel (A-029).
TRADEABLE_MARKET_STATES: frozenset[str] = frozenset({"MARKET_STATE_OPEN"})


class HealthStatus(Enum):
    """Feed health. Only ``HEALTHY`` permits trading."""

    UNINITIALIZED = "uninitialized"
    HEALTHY = "healthy"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    RESYNCING = "resyncing"
    DESYNCED = "desynced"
    MARKET_NOT_OPEN = "market_not_open"


class DeltaOutcome(Enum):
    """What :meth:`LiveBookFeed.apply_delta` / ``apply_snapshot`` did with a message."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE_SEQUENCE = "stale_sequence"
    SEQUENCE_GAP = "sequence_gap"
    NEGATIVE_QUANTITY = "negative_quantity"
    CROSSED_RESULT = "crossed_result"
    IGNORED_RESYNCING = "ignored_resyncing"
    IGNORED_DESYNCED = "ignored_desynced"


@dataclass(frozen=True, slots=True)
class FeedHealth:
    """A point-in-time health verdict for one feed."""

    status: HealthStatus
    reason: str
    as_of: datetime
    last_update: datetime | None
    last_sequence: int | None

    @property
    def trading_enabled(self) -> bool:
        """Fail-closed: ``True`` only when the feed is fully healthy."""
        return self.status is HealthStatus.HEALTHY


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of applying one message, plus the resulting health verdict."""

    outcome: DeltaOutcome
    health: FeedHealth


class _ConnState(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RESYNCING = "resyncing"


# --------------------------------------------------------------------------- #
# One contract's book
# --------------------------------------------------------------------------- #


class LiveBook:
    """Mutable price->quantity index for one contract. No health, no clock.

    Prices are compared by value (``Decimal`` equality), quantities are exact and
    always strictly positive once stored; a level driven to exactly zero is
    removed.
    """

    __slots__ = ("_asks", "_bids", "_initialized", "contract")

    def __init__(self, contract: Contract) -> None:
        if not isinstance(contract, Contract):
            raise LiveBookError("LiveBook.contract must be a domain Contract")
        self.contract = contract
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _side(self, side: Side) -> dict[Decimal, Decimal]:
        return self._bids if side == "bid" else self._asks

    def apply_snapshot(self, snapshot: BookSnapshot) -> None:
        """Replace all state with ``snapshot``'s levels."""
        self._bids = {level.price: level.quantity for level in snapshot.bids}
        self._asks = {level.price: level.quantity for level in snapshot.asks}
        if len(self._bids) != len(snapshot.bids) or len(self._asks) != len(snapshot.asks):
            raise LiveBookError("BookSnapshot has duplicate price levels on a side")
        self._initialized = True

    def apply_delta(self, delta: BookDelta) -> DeltaOutcome:
        """Add ``delta.quantity_delta`` to ``(side, price)``. Never raises for a
        pure quantity problem — returns :attr:`DeltaOutcome.NEGATIVE_QUANTITY`
        (and leaves state unchanged) when the result would be negative."""
        book = self._side(delta.side)
        current = book.get(delta.price, _ZERO)
        new_quantity = current + delta.quantity_delta
        if new_quantity < _ZERO:
            return DeltaOutcome.NEGATIVE_QUANTITY
        if new_quantity == _ZERO:
            book.pop(delta.price, None)
        else:
            book[delta.price] = new_quantity
        return DeltaOutcome.APPLIED

    def to_order_book(self, timestamp: datetime) -> OrderBook:
        """Build the domain :class:`OrderBook` (raises if crossed/invalid)."""
        bids = tuple(
            PriceLevel(price=price, quantity=self._bids[price])
            for price in sorted(self._bids, reverse=True)
        )
        asks = tuple(
            PriceLevel(price=price, quantity=self._asks[price])
            for price in sorted(self._asks)
        )
        return OrderBook(contract=self.contract, bids=bids, asks=asks, timestamp=timestamp)


# --------------------------------------------------------------------------- #
# One feed: book + connection + sequencing + staleness + health
# --------------------------------------------------------------------------- #


@dataclass
class LiveBookFeed:
    """Drives one :class:`LiveBook` from decoded WebSocket messages and reports
    :class:`FeedHealth`. A (future) socket transport calls
    :meth:`apply_snapshot` / :meth:`apply_delta` / :meth:`mark_disconnected` /
    :meth:`begin_resync`; nothing here opens a socket.
    """

    contract: Contract
    venue: str
    max_staleness: timedelta
    #: Kalshi's orderbook channel numbers every message (``seq``) and a gap means
    #: missed deltas -> resync. Polymarket US market-data messages carry no
    #: sequence and are full snapshots, so sequence checking is disabled there.
    require_sequence: bool = True

    _book: LiveBook = field(init=False)
    _conn: _ConnState = field(init=False, default=_ConnState.CONNECTED)
    _last_sequence: int | None = field(init=False, default=None)
    _last_update: datetime | None = field(init=False, default=None)
    _last_source_time: datetime | None = field(init=False, default=None)
    _desync_reason: str | None = field(init=False, default=None)
    _market_state: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise LiveBookError("LiveBookFeed.contract must be a domain Contract")
        if not self.venue:
            raise LiveBookError("LiveBookFeed.venue must be non-empty")
        if not isinstance(self.max_staleness, timedelta) or self.max_staleness <= timedelta(0):
            raise LiveBookError("LiveBookFeed.max_staleness must be a positive timedelta")
        self._book = LiveBook(self.contract)

    # -- introspection ---------------------------------------------------- #

    @property
    def book(self) -> LiveBook:
        return self._book

    @property
    def last_sequence(self) -> int | None:
        return self._last_sequence

    def current_order_book(
        self, now: datetime, *, require_healthy: bool = True
    ) -> OrderBook | None:
        """The current domain book, or ``None`` when ``require_healthy`` and the
        feed is not :attr:`HealthStatus.HEALTHY` (the fail-closed accessor)."""
        if not self._book.initialized:
            return None
        if require_healthy and not self.health(now).trading_enabled:
            return None
        try:
            return self._book.to_order_book(self._last_update or now)
        except DomainValidationError:
            return None

    # -- message application -------------------------------------------- #

    def apply_snapshot(self, snapshot: BookSnapshot, *, received_at: datetime) -> ApplyResult:
        self._check_target(snapshot.venue, snapshot.contract_id, "snapshot")
        require_aware_dt(received_at, field="received_at")

        # A steady-state feed (not mid-resync, not desynced) that receives a
        # snapshot older than the last accepted message is a reordered / repeated
        # delivery (Polymarket US is at-least-once) — drop it rather than move the
        # book backwards. A resync snapshot is always accepted.
        if (
            self._conn is _ConnState.CONNECTED
            and self._desync_reason is None
            and snapshot.source_time is not None
            and self._last_source_time is not None
            and snapshot.source_time < self._last_source_time
        ):
            return ApplyResult(DeltaOutcome.STALE_SEQUENCE, self.health(received_at))

        self._book.apply_snapshot(snapshot)
        self._last_sequence = snapshot.sequence
        self._last_update = received_at
        self._last_source_time = snapshot.source_time
        self._market_state = snapshot.market_state
        self._conn = _ConnState.CONNECTED
        self._desync_reason = None
        try:
            self._book.to_order_book(received_at)
        except DomainValidationError as exc:
            self._desync_reason = f"snapshot produced an invalid book: {exc}"
            return ApplyResult(DeltaOutcome.CROSSED_RESULT, self.health(received_at))
        return ApplyResult(DeltaOutcome.APPLIED, self.health(received_at))

    def apply_delta(self, delta: BookDelta, *, received_at: datetime) -> ApplyResult:
        self._check_target(delta.venue, delta.contract_id, "delta")
        require_aware_dt(received_at, field="received_at")
        if not self._book.initialized:
            raise LiveBookError("apply_delta called before any snapshot")

        if self._conn is _ConnState.RESYNCING:
            return ApplyResult(DeltaOutcome.IGNORED_RESYNCING, self.health(received_at))
        if self._desync_reason is not None:
            return ApplyResult(DeltaOutcome.IGNORED_DESYNCED, self.health(received_at))

        seq_outcome = self._check_sequence(delta.sequence)
        if seq_outcome is DeltaOutcome.DUPLICATE or seq_outcome is DeltaOutcome.STALE_SEQUENCE:
            return ApplyResult(seq_outcome, self.health(received_at))
        if seq_outcome is DeltaOutcome.SEQUENCE_GAP:
            self._desync_reason = (
                f"sequence gap: expected {(self._last_sequence or 0) + 1}, "
                f"got {delta.sequence}"
            )
            return ApplyResult(DeltaOutcome.SEQUENCE_GAP, self.health(received_at))

        outcome = self._book.apply_delta(delta)
        if outcome is DeltaOutcome.NEGATIVE_QUANTITY:
            self._desync_reason = (
                f"delta drove {delta.side} {delta.price} below zero "
                f"(delta {delta.quantity_delta})"
            )
            return ApplyResult(DeltaOutcome.NEGATIVE_QUANTITY, self.health(received_at))

        # Provisionally advance, then validate the resulting book is not crossed.
        prior_sequence = self._last_sequence
        if delta.sequence is not None:
            self._last_sequence = delta.sequence
        self._last_update = received_at
        if delta.source_time is not None:
            self._last_source_time = delta.source_time
        try:
            self._book.to_order_book(received_at)
        except DomainValidationError as exc:
            self._last_sequence = prior_sequence
            self._desync_reason = f"delta produced a crossed/invalid book: {exc}"
            return ApplyResult(DeltaOutcome.CROSSED_RESULT, self.health(received_at))
        return ApplyResult(DeltaOutcome.APPLIED, self.health(received_at))

    # -- connection lifecycle ----------------------------------------- #

    def mark_disconnected(self, *, at: datetime) -> FeedHealth:
        """Socket dropped. Book contents are retained but the feed is unhealthy
        until a fresh snapshot arrives."""
        require_aware_dt(at, field="at")
        self._conn = _ConnState.DISCONNECTED
        return self.health(at)

    def begin_resync(self, *, at: datetime) -> FeedHealth:
        """Reconnected / requested a fresh snapshot. Clears any desync; the next
        :meth:`apply_snapshot` restores the feed."""
        require_aware_dt(at, field="at")
        self._conn = _ConnState.RESYNCING
        self._desync_reason = None
        return self.health(at)

    # -- health ------------------------------------------------------- #

    def health(self, now: datetime) -> FeedHealth:
        require_aware_dt(now, field="now")

        def verdict(status: HealthStatus, reason: str) -> FeedHealth:
            return FeedHealth(
                status=status,
                reason=reason,
                as_of=now,
                last_update=self._last_update,
                last_sequence=self._last_sequence,
            )

        if not self._book.initialized or self._last_update is None:
            return verdict(HealthStatus.UNINITIALIZED, "no snapshot received yet")
        if self._conn is _ConnState.DISCONNECTED:
            return verdict(HealthStatus.DISCONNECTED, "socket disconnected; awaiting reconnect")
        if self._conn is _ConnState.RESYNCING:
            return verdict(HealthStatus.RESYNCING, "reconnected; awaiting fresh snapshot")
        if self._desync_reason is not None:
            return verdict(HealthStatus.DESYNCED, self._desync_reason)
        if self._market_state is not None and self._market_state not in TRADEABLE_MARKET_STATES:
            return verdict(
                HealthStatus.MARKET_NOT_OPEN, f"venue market state {self._market_state!r}"
            )
        age = now - self._last_update
        if age < timedelta(0):
            return verdict(
                HealthStatus.STALE, f"last update {(-age)} in the future relative to now"
            )
        if age > self.max_staleness:
            return verdict(
                HealthStatus.STALE,
                f"last update {age} old exceeds max {self.max_staleness}",
            )
        return verdict(HealthStatus.HEALTHY, "")

    # -- internals -------------------------------------------------- #

    def _check_target(self, venue: str, contract_id: str, kind: str) -> None:
        if venue != self.venue:
            raise LiveBookError(
                f"{kind} venue {venue!r} does not match feed venue {self.venue!r}"
            )
        if contract_id != self.contract.id:
            raise LiveBookError(
                f"{kind} contract_id {contract_id!r} does not match feed contract "
                f"{self.contract.id!r}"
            )

    def _check_sequence(self, sequence: int | None) -> DeltaOutcome:
        """Classify ``sequence`` against the last accepted one."""
        if not self.require_sequence or sequence is None or self._last_sequence is None:
            return DeltaOutcome.APPLIED  # sequencing not enforced for this feed
        expected = self._last_sequence + 1
        if sequence == self._last_sequence:
            return DeltaOutcome.DUPLICATE
        if sequence < self._last_sequence:
            return DeltaOutcome.STALE_SEQUENCE
        if sequence > expected:
            return DeltaOutcome.SEQUENCE_GAP
        return DeltaOutcome.APPLIED
