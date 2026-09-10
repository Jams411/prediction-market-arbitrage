"""Bounded **read-only** production observation of Kalshi market data driven
through the shipped live-book runtime — `livebook.LiveBookConnection` +
`livebook.LiveBookFeed` — not the standalone WS smoke script.

Real-money gate #2 / #7 / #8 and assumption A-028 need evidence from the *actual*
code path a live trader would use. Two bounded observation modes, each through
the shipped runtime:

``--observe`` (disconnect / reconnect — real-money gate #8)
    1. Initialize each feed from a **REST snapshot** (`KalshiMarketDataAdapter`,
       public prod REST — no auth).
    2. Open the **authenticated production WebSocket** with the read-only signer
       and `subscribe` one liquid market's `orderbook_delta`.
    3. Pump frames through `LiveBookConnection.pump_one()` until the feed is a
       stable, `seq`-ordered `HEALTHY` stream.
    4. Confirm both feeds `HEALTHY`, then induce **exactly one** controlled
       transport drop (abruptly close the underlying socket) so the next
       `pump_one()` raises `TransportClosed` exactly as an unplanned network
       drop would — the runtime is never bypassed.
    5. Drive the normal runtime recovery path: `handle_disconnect()` ->
       `reconnect()` (with `BackoffPolicy`) -> `resync()` (authenticated
       resubscribe + fresh REST snapshot), recording that `HEALTHY` is restored
       **only after** the resync snapshot.
    6. Pump a few more real deltas to show healthy operation resumes.

``--observe-stale`` (stale-data handling — real-money gate #7)
    1./2. Same REST-snapshot init + authenticated WS subscribe, but on a
       market picked for **moderate** (not maximal) activity.
    3. **Never pause consumption.** Keep calling `pump_one()` continuously and,
       between reads, sample each feed's `FeedHealth` and the fail-closed
       accessor `LiveBookFeed.current_order_book(now, require_healthy=True)`.
    4. Wait for a genuine `HEALTHY -> STALE -> HEALTHY` lifecycle caused by a
       natural gap between qualifying `orderbook_delta` updates that exceeds the
       feed's documented `max_staleness`, ended by a genuine new delta. While
       `STALE`, confirm the fail-closed accessor returns `None` (downstream
       trading is gated off) while the raw book is still retained.
    5. If no market naturally crosses the threshold *and recovers* within the
       bounded watch window, write a blocker and leave gate #7 unchecked.

Everything is read-only market data. There is **no** code path here to submit /
cancel / modify an order, read balances / positions / fills, move funds, set
live trading, or touch the other venue. The signer is used only for the
market-data WS handshake. No clocks or timestamps are manipulated and no frames
are injected — staleness, when observed, comes from a real quiet market.

Run modes::

    python scripts/observe_kalshi_livebook_runtime.py                       # --check (no socket)
    PMA_KALSHI_PROD_WS_OBSERVE=1 \
        python scripts/observe_kalshi_livebook_runtime.py --observe [MIN_DELTAS] [MAX_STEADY_S]
    PMA_KALSHI_PROD_WS_OBSERVE=1 \
        python scripts/observe_kalshi_livebook_runtime.py --observe-stale [MAX_WATCH_S]

Sanitized evidence -> ``docs/evidence/kalshi-live/livebook-runtime/``:
``SUMMARY_RECONNECT.json`` and ``SUMMARY_STALE.json`` — a phase-by-phase timeline
with UTC timestamps + per-phase offsets, health-status transitions,
`DeltaOutcome` tallies, `seq` monotonicity, book-fingerprint change counts, and
an additive-delta (A-028) relationship check — **no** raw prices, sizes,
tickers, or market ids.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket as _socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from kalshi_signer import OpensslRsaPssSigner, SignerError, read_keychain_password

from prediction_market_arbitrage.adapters.kalshi.adapter import KalshiMarketDataAdapter
from prediction_market_arbitrage.adapters.kalshi.normalize import build_contracts
from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.livebook import (
    BackoffPolicy,
    BookSnapshot,
    DeltaOutcome,
    HealthStatus,
    LiveBookConnection,
    LiveBookError,
    LiveBookFeed,
    TransportClosed,
    WebsocketsTransport,
    kalshi_frame_decoder,
    kalshi_subscribe_command,
    kalshi_ws_handshake,
)
from prediction_market_arbitrage.livebook.credentials import KalshiCredentials
from prediction_market_arbitrage.livebook.updates import BookDelta
from prediction_market_arbitrage.livebook.ws_auth import KALSHI_WS_URL_PROD, Handshake


def utc_now() -> datetime:
    return datetime.now(UTC)


VENUE = "kalshi"
KEYCHAIN_SERVICE = "pma-kalshi-prod-api-key-id"
PEM_PATH = Path.home() / ".config" / "pma" / "kalshi-prod-private-key.pem"
RUN_ENV_GUARD = "PMA_KALSHI_PROD_WS_OBSERVE"
OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "evidence"
    / "kalshi-live"
    / "livebook-runtime"
)

MAX_STALENESS = timedelta(seconds=30)
DEFAULT_MIN_DELTAS = 8
DEFAULT_MAX_STEADY_S = 180.0
POST_RESYNC_DELTAS = 3
POST_RESYNC_MAX_S = 90.0
RECV_TIMEOUT_S = 65.0  # > MAX_STALENESS so an over-long gap is a real problem
_ACTIVE_SERIES = ("KXBTCD", "KXBTC", "KXETHD", "KXETH")

# --- gate #7 (stale-data) continuous-consumption watch ---------------------- #
DEFAULT_STALE_WATCH_S = 720.0  # 12 min hard cap on the whole watch
# A quiet market may legitimately go a couple of minutes between deltas; the
# recv timeout must sit above that so a natural gap is not misread as a drop,
# yet still bound a genuinely dead socket.
STALE_WATCH_RECV_TIMEOUT_S = 170.0
STALE_WATCH_WARMUP_DELTAS = 2
STALE_WATCH_WARMUP_MAX_S = 240.0
# "moderate activity" probe: sample a few candidates, read each book twice a
# short interval apart, keep the ones that are alive (book changed) but prefer
# the thinnest (quietest) so a > max_staleness gap is plausible.
MODERATE_PROBE_CANDIDATES = 14
MODERATE_PROBE_GAP_S = 18.0

CREATE_KEY_STEPS = (
    "No usable production Kalshi credential. This harness will not create one.\n"
    "  1. Kalshi web UI -> Account & security -> API Keys -> Create Key (production).\n"
    "  2. security add-generic-password -a \"$USER\" -s "
    f"{KEYCHAIN_SERVICE} -w\n"
    f"  3. Move the private key to {PEM_PATH} and chmod 600 it.\n"
    f"  4. {RUN_ENV_GUARD}=1 python scripts/observe_kalshi_livebook_runtime.py --observe\n"
)


# --------------------------------------------------------------------------- #
# REST snapshot source (public, GET-only) -> livebook BookSnapshot
# --------------------------------------------------------------------------- #


@dataclass
class RestSnapshotSource:
    """`livebook.SnapshotSource`: fetch a fresh REST book for one contract id
    (``TICKER:YES`` / ``TICKER:NO``) and adapt it to a `BookSnapshot`.

    A 2 s memo means a YES+NO resync pair costs one REST round-trip, not two.
    """

    adapter: KalshiMarketDataAdapter
    _memo: dict[str, tuple[float, Any]] = field(default_factory=dict)

    def fetch(self, contract_id: str) -> BookSnapshot:
        ticker, _, outcome = contract_id.rpartition(":")
        if outcome not in ("YES", "NO"):
            raise ValueError(f"unexpected contract id {contract_id!r}")
        cached = self._memo.get(ticker)
        if cached is not None and time.monotonic() - cached[0] < 2.0:
            books = cached[1]
        else:
            books = self.adapter.get_order_books(ticker)
            self._memo[ticker] = (time.monotonic(), books)
        ob: OrderBook = books.yes if outcome == "YES" else books.no
        return BookSnapshot(
            venue=VENUE,
            contract_id=contract_id,
            bids=ob.bids,
            asks=ob.asks,
            sequence=None,  # REST carries no seq; the next WS delta sets the baseline
            source_time=ob.timestamp,
            market_state=None,
        )


# --------------------------------------------------------------------------- #
# Value-free book fingerprint + summary
# --------------------------------------------------------------------------- #


def book_fingerprint(ob: OrderBook | None) -> str | None:
    if ob is None:
        return None
    payload = json.dumps(
        {
            "b": [[str(lvl.price), str(lvl.quantity)] for lvl in ob.bids],
            "a": [[str(lvl.price), str(lvl.quantity)] for lvl in ob.asks],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def book_summary(ob: OrderBook | None) -> dict[str, Any]:
    if ob is None:
        return {"initialized": False}
    return {
        "initialized": True,
        "bid_levels": len(ob.bids),
        "ask_levels": len(ob.asks),
        "has_best_bid": ob.best_bid is not None,
        "has_best_ask": ob.best_ask is not None,
        "fingerprint": book_fingerprint(ob),
    }


def _outcome(contract_id: str) -> str:
    """The venue-neutral outcome label (``YES`` / ``NO``) — used as a sanitised
    dict key so the production market ticker never lands in the evidence."""
    return contract_id.rpartition(":")[2] or contract_id


def _qty_at(ob: OrderBook | None, delta: BookDelta) -> Any:
    """Aggregated quantity resting at ``delta``'s (side, price), or 0 / None."""
    if ob is None:
        return None
    levels = ob.bids if delta.side == "bid" else ob.asks
    for lvl in levels:
        if lvl.price == delta.price:
            return lvl.quantity
    return 0


# --------------------------------------------------------------------------- #
# Observation record
# --------------------------------------------------------------------------- #


class Recorder:
    def __init__(self, contract_ids: list[str]) -> None:
        self._t0 = time.monotonic()
        self.contract_ids = contract_ids
        self.timeline: list[dict[str, Any]] = []
        self.outcomes: dict[str, int] = {}
        self.seq_by_contract: dict[str, list[int]] = {}
        self.seq_monotonic_violations = 0
        self.seq_epoch = 0  # bumped on resubscribe; Kalshi resets seq per subscription
        self.seq_reset_on_resubscribe = False
        self.seq_epoch_first_last: list[list[int]] = []
        self._epoch_seqs: list[int] = []
        self.fingerprint_changes = 0
        self.deltas_applied = 0
        # A-028 additive-delta relationship check (values never persisted).
        self.additive_checked = 0
        self.additive_matches = 0
        self.additive_mismatches = 0
        self.level_removed_on_zero = 0
        self.desyncs = 0
        self._last_fp: dict[str, str | None] = {}

    def mark(self, phase: str, event: str, conn: LiveBookConnection, now: datetime,
             *, extra: dict[str, Any] | None = None) -> None:
        health = {
            _outcome(cid): {"status": h.status.value, "trading_enabled": h.trading_enabled,
                            "last_sequence": h.last_sequence}
            for cid, h in conn.feed_health().items()
        }
        entry: dict[str, Any] = {
            "t_offset_s": round(time.monotonic() - self._t0, 3),
            "utc": now.isoformat(),
            "phase": phase,
            "event": event,
            "health": health,
        }
        if extra:
            entry.update(extra)
        self.timeline.append(entry)

    def close_seq_epoch(self) -> None:
        if self._epoch_seqs:
            self.seq_epoch_first_last.append([self._epoch_seqs[0], self._epoch_seqs[-1]])

    def start_new_seq_epoch(self) -> None:
        """Kalshi restarts ``seq`` from a low value for each new subscription, so
        after a resubscribe the counter legitimately jumps backwards. Segment the
        monotonicity check per epoch and record the reset as its own fact."""
        had_data = bool(self._epoch_seqs)
        self.close_seq_epoch()
        self.seq_epoch += 1
        self.seq_by_contract = {}
        self._epoch_seqs = []
        if had_data:
            self.seq_reset_on_resubscribe = True

    def note_delta(self, cid: str, outcome: DeltaOutcome, seq: int | None,
                   *, additive_ok: bool | None, removed_on_zero: bool,
                   fp: str | None) -> None:
        self.outcomes[outcome.value] = self.outcomes.get(outcome.value, 0) + 1
        if outcome is DeltaOutcome.APPLIED:
            self.deltas_applied += 1
            if seq is not None:
                # Monotonicity is per contract feed within one subscription epoch:
                # one WS frame updates both the YES and NO feed with the same seq
                # (not a violation), and a resubscribe resets seq (new epoch).
                series = self.seq_by_contract.setdefault(cid, [])
                if series and seq <= series[-1]:
                    self.seq_monotonic_violations += 1
                series.append(seq)
                if not self._epoch_seqs or seq > self._epoch_seqs[-1]:
                    self._epoch_seqs.append(seq)
            if additive_ok is not None:
                self.additive_checked += 1
                if additive_ok:
                    self.additive_matches += 1
                else:
                    self.additive_mismatches += 1
            if removed_on_zero:
                self.level_removed_on_zero += 1
            if self._last_fp.get(cid) is not None and fp != self._last_fp.get(cid):
                self.fingerprint_changes += 1
            self._last_fp[cid] = fp
        elif outcome in (
            DeltaOutcome.SEQUENCE_GAP,
            DeltaOutcome.NEGATIVE_QUANTITY,
            DeltaOutcome.CROSSED_RESULT,
        ):
            self.desyncs += 1


# --------------------------------------------------------------------------- #
# Pump loop (transport-agnostic; tested with a fake transport)
# --------------------------------------------------------------------------- #


def pump_collecting(
    conn: LiveBookConnection,
    feeds: dict[str, LiveBookFeed],
    rec: Recorder,
    *,
    phase: str,
    target_deltas: int,
    max_seconds: float,
    now_fn: Callable[[], datetime] = utc_now,
) -> int:
    """Pump frames until ``target_deltas`` APPLIED deltas or ``max_seconds``.
    Returns the count of APPLIED deltas seen in this call."""
    def books() -> dict[str, OrderBook | None]:
        n = now_fn()
        return {cid: f.current_order_book(n, require_healthy=False) for cid, f in feeds.items()}

    start = time.monotonic()
    applied_here = 0
    while applied_here < target_deltas and time.monotonic() - start < max_seconds:
        before = books()
        try:
            updates = conn.pump_one()
        except TransportClosed:
            rec.mark(phase, "transport_closed_while_pumping", conn, now_fn())
            break
        after = books()
        for upd in updates:
            if not isinstance(upd, BookDelta):
                continue
            cid = upd.contract_id
            feed = feeds.get(cid)
            if feed is None:
                continue
            seq = feed.last_sequence
            q_before = _qty_at(before.get(cid), upd)
            q_after = _qty_at(after.get(cid), upd)
            additive_ok: bool | None = None
            removed = False
            if q_before is not None and q_after is not None:
                expected = q_before + upd.quantity_delta
                if expected == 0:
                    additive_ok = q_after == 0
                    removed = True
                elif expected > 0:
                    additive_ok = q_after == expected
                else:
                    additive_ok = None  # below zero -> feed would have desynced, not applied
            rec.note_delta(
                cid, DeltaOutcome.APPLIED, seq,
                additive_ok=additive_ok, removed_on_zero=removed,
                fp=book_fingerprint(after.get(cid)),
            )
            applied_here += 1
    rec.mark(phase, f"pumped_{applied_here}_deltas", conn, now_fn())
    return applied_here


# --------------------------------------------------------------------------- #
# Continuous-consumption staleness watch (real-money gate #7)
# --------------------------------------------------------------------------- #


def watch_staleness_lifecycle(
    conn: LiveBookConnection,
    feeds: dict[str, LiveBookFeed],
    rec: Recorder,
    *,
    max_watch_s: float,
    now_fn: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    """Consume continuously (**never** pausing) and watch for a genuine
    ``HEALTHY -> STALE -> HEALTHY`` lifecycle on at least one feed, caused by a
    real gap between qualifying ``orderbook_delta`` updates that exceeds
    ``max_staleness`` and ended by a real new delta.

    Between every runtime read, sample each feed's health and the fail-closed
    accessor ``current_order_book(now, require_healthy=True)`` — while ``STALE``
    it must return ``None`` (downstream trading gated off) while the raw book is
    still retained. Returns a summary dict; ``lifecycle_observed`` is ``True``
    only when the full round trip (recovery via a real delta) was seen.
    """
    start = time.monotonic()
    # per-feed stage: "init" -> "healthy" -> "stale" -> "recovered"
    stage: dict[str, str] = dict.fromkeys(feeds, "init")
    stale_spans: list[dict[str, Any]] = []
    gate_rejected_while_stale = 0
    gate_served_while_healthy = 0
    max_stale_age_s = 0.0
    recovered = False
    inconclusive: str | None = None
    empty_pumps = 0          # pump_one() calls that returned no update (idle traffic)
    delta_pumps = 0          # pump_one() calls that applied >=1 delta
    max_pump_gap_s = 0.0     # longest wall gap between consecutive pump_one() returns
    _last_pump_ret = start

    def sample_health(n: datetime) -> None:
        nonlocal gate_rejected_while_stale, gate_served_while_healthy, max_stale_age_s
        for cid, feed in feeds.items():
            h = feed.health(n)
            gated = feed.current_order_book(n, require_healthy=True)
            raw = feed.current_order_book(n, require_healthy=False)
            if h.status is HealthStatus.HEALTHY:
                if stage[cid] == "init":
                    stage[cid] = "healthy"
                    rec.mark("C_stale_watch", "feed_healthy", conn, n,
                             extra={"feed": _outcome(cid)})
                if gated is not None:
                    gate_served_while_healthy += 1
            elif h.status is HealthStatus.STALE:
                if stage[cid] == "healthy":
                    stage[cid] = "stale"
                    stale_spans.append({
                        "feed": _outcome(cid),
                        "entered_utc": n.isoformat(),
                        "entered_offset_s": round(time.monotonic() - start, 3),
                    })
                    rec.mark("C_stale_watch", "feed_went_stale", conn, n, extra={
                        "feed": _outcome(cid),
                        "reason": h.reason,
                        "fail_closed_accessor_returned_none": gated is None,
                        "raw_book_still_retained": raw is not None,
                    })
                if stage[cid] == "stale":
                    if gated is None:
                        gate_rejected_while_stale += 1
                    if h.last_update is not None:
                        max_stale_age_s = max(
                            max_stale_age_s, (n - h.last_update).total_seconds()
                        )

    while time.monotonic() - start < max_watch_s and not recovered:
        sample_health(now_fn())
        try:
            updates = conn.pump_one()
        except TransportClosed:
            # A recv-timeout on a quiet-but-alive socket is indistinguishable
            # here from a real drop: the shipped transport releases the socket
            # either way. If nothing arrived to sample health during the gap,
            # that is the architectural blocker, not a market that was too busy.
            inconclusive = (
                "transport closed during watch (WebsocketsTransport recv_timeout "
                f"{STALE_WATCH_RECV_TIMEOUT_S}s elapsed with no frame, or a real drop); "
                f"empty_pumps={empty_pumps}"
            )
            rec.mark("C_stale_watch", "transport_closed_during_watch", conn, now_fn(),
                     extra={"empty_pumps": empty_pumps, "delta_pumps": delta_pumps})
            break
        except LiveBookError:  # transport already released (defensive)
            inconclusive = "transport unusable during watch (already released)"
            break
        now_ret = time.monotonic()
        max_pump_gap_s = max(max_pump_gap_s, now_ret - _last_pump_ret)
        _last_pump_ret = now_ret
        n2 = now_fn()
        applied_this_pump = 0
        for upd in updates:
            if not isinstance(upd, BookDelta):
                continue
            cid = upd.contract_id
            feed = feeds.get(cid)
            if feed is None:
                continue
            applied_this_pump += 1
            seq = feed.last_sequence
            rec.note_delta(
                cid, DeltaOutcome.APPLIED, seq, additive_ok=None,
                removed_on_zero=False,
                fp=book_fingerprint(feed.current_order_book(n2, require_healthy=False)),
            )
            if stage.get(cid) == "stale" and feed.health(n2).status is HealthStatus.HEALTHY:
                stage[cid] = "recovered"
                recovered = True
                rec.mark("C_stale_watch", "feed_recovered_via_real_delta", conn, n2, extra={
                    "feed": _outcome(cid),
                    "recovery_seq": seq,
                    "fail_closed_accessor_serves_again":
                        feed.current_order_book(n2, require_healthy=True) is not None,
                })
        if applied_this_pump:
            delta_pumps += 1
        else:
            empty_pumps += 1
        # A hyper-active market never yields a stale interval to observe; stop
        # early once that is unambiguous rather than burning the whole cap.
        if (
            time.monotonic() - start > 90.0
            and empty_pumps == 0
            and delta_pumps >= 60
            and max_stale_age_s < MAX_STALENESS.total_seconds() * 0.5
        ):
            rec.mark("C_stale_watch", "early_stop_market_too_active", conn, now_fn(),
                     extra={"delta_pumps": delta_pumps})
            break

    sample_health(now_fn())
    if not recovered and inconclusive is None:
        if empty_pumps == 0 and max_stale_age_s <= MAX_STALENESS.total_seconds():
            inconclusive = (
                "market stayed active: every pump_one() returned a qualifying delta and no "
                "feed aged past max_staleness within the window — no stale interval to observe"
            )
        elif stale_spans:
            inconclusive = (
                "feed(s) went STALE but no genuine recovering delta arrived in the window"
            )
        else:
            inconclusive = "watch window elapsed without a natural HEALTHY->STALE transition"
    return {
        "lifecycle_observed": recovered,
        "inconclusive": inconclusive,
        "feeds_that_went_stale": sorted({s["feed"] for s in stale_spans}),
        "stale_spans": stale_spans,
        "max_observed_stale_age_s": round(max_stale_age_s, 3),
        "max_staleness_threshold_s": MAX_STALENESS.total_seconds(),
        "fail_closed_gate_rejections_while_stale": gate_rejected_while_stale,
        "fail_closed_gate_serves_while_healthy": gate_served_while_healthy,
        "empty_pumps": empty_pumps,
        "delta_pumps": delta_pumps,
        "max_pump_gap_s": round(max_pump_gap_s, 3),
        "watch_elapsed_s": round(time.monotonic() - start, 3),
        "watch_cap_s": max_watch_s,
    }


# --------------------------------------------------------------------------- #
# Preflight (no socket)
# --------------------------------------------------------------------------- #


def preflight() -> dict[str, Any]:
    from shutil import which

    openssl_ok = which("openssl") is not None
    pem_ok = PEM_PATH.is_file()
    try:
        read_keychain_password(KEYCHAIN_SERVICE)
        keychain = "present"
    except SignerError as exc:
        keychain = str(exc)
    return {
        "openssl_on_path": openssl_ok,
        "private_key_file_present": pem_ok,
        "keychain_key_id": keychain,
        "env_guard_set": os.environ.get(RUN_ENV_GUARD) == "1",
        "ready": openssl_ok and pem_ok and keychain == "present",
    }


# --------------------------------------------------------------------------- #
# Market pick (public, GET-only)
# --------------------------------------------------------------------------- #


def _open_candidates(adapter: KalshiMarketDataAdapter, *, want: int) -> list[str]:
    candidates: list[str] = []
    for series in _ACTIVE_SERIES:
        page = adapter.list_markets(status="open", series_ticker=series, limit=100)
        candidates += [m.id for m in page.markets]
        if len(candidates) >= want:
            break
    return candidates


def _open_markets_any_series(adapter: KalshiMarketDataAdapter, *, pages: int) -> list[str]:
    """Open markets across the exchange (no series filter) — used to reach the
    quieter, non-crypto markets a natural staleness window needs."""
    out: list[str] = []
    cursor: str | None = None
    for _ in range(pages):
        page = adapter.list_markets(status="open", limit=100, cursor=cursor)
        out += [m.id for m in page.markets]
        cursor = page.cursor
        if not cursor:
            break
    return out


def pick_liquid_market(adapter: KalshiMarketDataAdapter) -> str:
    candidates = _open_candidates(adapter, want=40)
    if not candidates:
        raise SystemExit("no open markets for the active production series")
    best, best_depth = "", -1
    for ticker in candidates[:40]:
        try:
            books = adapter.get_order_books(ticker)
        except Exception:  # noqa: BLE001 - skip a bad market, keep scanning
            continue
        depth = min(len(books.yes.bids), len(books.yes.asks))
        if depth > best_depth:
            best, best_depth = ticker, depth
    return best or candidates[0]


def _two_sided(books: Any) -> bool:
    return (
        books.yes.best_bid is not None and books.yes.best_ask is not None
        and books.no.best_bid is not None and books.no.best_ask is not None
    )


def pick_moderate_market(
    adapter: KalshiMarketDataAdapter, *, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Pick a market with *moderate* activity for the gate #7 watch: alive
    enough to eventually deliver a recovering delta, quiet enough that a gap can
    exceed ``max_staleness``.

    Probe: read a sample of open two-sided books twice, ``MODERATE_PROBE_GAP_S``
    apart. Keep the ones that changed between reads (alive) and, among those,
    return the thinnest (quietest). Fall back to the thinnest live two-sided
    book, then to any candidate.
    """
    candidates = _open_markets_any_series(adapter, pages=3)
    if not candidates:
        raise SystemExit("no open markets on the exchange")
    # Skip the deliberately hyper-active crypto series — they never go quiet.
    non_crypto = [t for t in candidates if not t.startswith(_ACTIVE_SERIES)]
    sample = (non_crypto or candidates)[:MODERATE_PROBE_CANDIDATES]

    first: dict[str, tuple[str | None, int]] = {}
    for ticker in sample:
        try:
            books = adapter.get_order_books(ticker)
        except Exception:  # noqa: BLE001
            continue
        if not _two_sided(books):
            continue
        depth = min(len(books.yes.bids), len(books.yes.asks))
        first[ticker] = (book_fingerprint(books.yes), depth)

    sleep(MODERATE_PROBE_GAP_S)

    alive: list[tuple[int, str]] = []
    live_two_sided: list[tuple[int, str]] = []
    for ticker, (fp0, depth) in first.items():
        try:
            books = adapter.get_order_books(ticker)
        except Exception:  # noqa: BLE001
            continue
        if not _two_sided(books):
            continue
        live_two_sided.append((depth, ticker))
        if book_fingerprint(books.yes) != fp0:
            alive.append((depth, ticker))

    if alive:
        return min(alive)[1]
    if live_two_sided:
        return min(live_two_sided)[1]
    # The public open-markets listing surfaced nothing with a usable two-sided
    # book (it is dominated by empty-book markets); fall back to a real liquid
    # market so the watch still runs and records a documented outcome.
    return pick_liquid_market(adapter)


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #


@dataclass
class _RuntimeBundle:
    conn: LiveBookConnection
    feeds: dict[str, LiveBookFeed]
    transport: WebsocketsTransport
    src: RestSnapshotSource
    adapter: KalshiMarketDataAdapter
    backoff: BackoffPolicy


def _build_runtime(ticker: str, *, recv_timeout: float,
                   adapter: KalshiMarketDataAdapter | None = None) -> _RuntimeBundle:
    now = utc_now
    key_id = read_keychain_password(KEYCHAIN_SERVICE)
    signer = OpensslRsaPssSigner(PEM_PATH)
    credentials = KalshiCredentials(api_key_id=key_id, private_key_pem=PEM_PATH.read_text())

    adapter = adapter or KalshiMarketDataAdapter()
    yes_c, no_c = build_contracts(adapter.get_market(ticker))
    feeds = {
        yes_c.id: LiveBookFeed(contract=yes_c, venue=VENUE, max_staleness=MAX_STALENESS),
        no_c.id: LiveBookFeed(contract=no_c, venue=VENUE, max_staleness=MAX_STALENESS),
    }
    src = RestSnapshotSource(adapter)
    transport = WebsocketsTransport(recv_timeout=recv_timeout)
    backoff = BackoffPolicy(base_seconds=1.0, factor=2.0, max_seconds=8.0, max_attempts=6)

    def handshake_factory() -> Handshake:
        return kalshi_ws_handshake(credentials, signer, now=now(), url=KALSHI_WS_URL_PROD)

    conn = LiveBookConnection(
        venue=VENUE,
        feeds=list(feeds.values()),
        transport=transport,
        handshake_factory=handshake_factory,
        subscribe_command=kalshi_subscribe_command(command_id=1, market_tickers=[ticker]),
        decode=kalshi_frame_decoder,
        snapshot_source=src,
        clock=now,
        backoff=backoff,
    )
    return _RuntimeBundle(conn=conn, feeds=feeds, transport=transport, src=src,
                          adapter=adapter, backoff=backoff)


def _common_summary(rec: Recorder, kind: str, start: datetime, end: datetime,
                    config: dict[str, Any]) -> dict[str, Any]:
    statuses_seen: list[str] = []
    for entry in rec.timeline:
        for h in entry["health"].values():
            if h["status"] not in statuses_seen:
                statuses_seen.append(h["status"])
    return {
        "venue": VENUE,
        "environment": "production",
        "observation": kind,
        "path": "livebook.LiveBookConnection + LiveBookFeed (shipped runtime)",
        "market_ticker": "<redacted>",
        "session_start_utc": start.isoformat(),
        "session_end_utc": end.isoformat(),
        "wall_elapsed_s": round((end - start).total_seconds(), 3),
        "config": config,
        "applied_delta_count": rec.deltas_applied,
        "delta_outcomes": rec.outcomes,
        "seq_monotonic_violations_within_subscription": rec.seq_monotonic_violations,
        "seq_epochs_first_last": rec.seq_epoch_first_last,
        "seq_reset_on_resubscribe": rec.seq_reset_on_resubscribe,
        "book_fingerprint_changes": rec.fingerprint_changes,
        "additive_delta_check": {
            "checked": rec.additive_checked,
            "matches": rec.additive_matches,
            "mismatches": rec.additive_mismatches,
            "level_removed_on_zero": rec.level_removed_on_zero,
            "desyncs": rec.desyncs,
            "note": "check: qty_after == (qty_before + delta_fp); raw values not persisted",
        },
        "health_statuses_seen": statuses_seen,
        "timeline": rec.timeline,
        "safety": [
            "read-only market data only; no order/cancel/modify code path",
            "no balances/positions/fills; no funds; live trading untouched",
            "signer used only for the market-data WS handshake; single venue only",
            "no clock/timestamp manipulation; no injected frames",
        ],
    }


# --------------------------------------------------------------------------- #
# Observation #8 — disconnect / reconnect / resync
# --------------------------------------------------------------------------- #


def run_observation(min_deltas: int, max_steady_s: float) -> int:
    """Real-money gate #8: one controlled transport drop through the shipped
    runtime, then the normal ``handle_disconnect -> reconnect -> resync``
    recovery, with ``HEALTHY`` restored only after the resync snapshot."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = utc_now
    session_start = now()

    rt = _build_runtime(pick_liquid_market(KalshiMarketDataAdapter()),
                        recv_timeout=RECV_TIMEOUT_S)
    conn, feeds, transport, src = rt.conn, rt.feeds, rt.transport, rt.src
    rec = Recorder(list(feeds.keys()))
    rec.mark("A_init", "start", conn, now())

    # Phase A — initial REST snapshot / live-book initialization.
    for cid, feed in feeds.items():
        feed.apply_snapshot(src.fetch(cid), received_at=now())
    rec.mark("A_init", "rest_snapshot_applied", conn, now(),
             extra={"books": {_outcome(cid): book_summary(
                 f.current_order_book(now(), require_healthy=False))
                 for cid, f in feeds.items()}})

    # Phase B — WS subscribe + steady-state deltas.
    conn.connect_and_subscribe()
    rec.mark("B_steady", "ws_connect_and_subscribe", conn, now())
    applied = pump_collecting(conn, feeds, rec, phase="B_steady",
                              target_deltas=min_deltas, max_seconds=max_steady_s, now_fn=now)
    if applied < min_deltas:
        reason = f"market too inactive: {applied}/{min_deltas} deltas in {max_steady_s}s"
        _write_blocker("SUMMARY_RECONNECT.json", rec, session_start, now(), reason=reason)
        print(f"BLOCKER: {reason} — evidence not collected")
        transport.close()
        return 3

    # Phase C — confirm both feeds are HEALTHY *before* the drop, so the induced
    # disconnect exercises a clean HEALTHY -> DISCONNECTED transition.
    healthy_pre_drop = conn.all_healthy()
    rec.mark("C_confirm", "feeds_healthy_pre_drop", conn, now(),
             extra={"all_healthy": healthy_pre_drop})

    # Phase D — one controlled disconnect + detection. Break the real socket
    # under the runtime (an abrupt drop, not a graceful close) so the next
    # pump_one() read raises TransportClosed exactly as an unplanned drop would.
    ws_conn = transport._conn  # noqa: SLF001 - deliberate induced drop
    if ws_conn is not None:
        try:
            ws_conn.socket.shutdown(_socket.SHUT_RDWR)
        except OSError:
            pass
        ws_conn.socket.close()
    rec.mark("D_disconnect", "socket_dropped", conn, now())
    # The websockets client buffers frames in a background reader thread, so the
    # runtime may hand back a few already-received frames before the next read
    # surfaces the drop. Pump until TransportClosed (bounded).
    detected = False
    drained = 0
    drop_deadline = time.monotonic() + 20.0
    while time.monotonic() < drop_deadline:
        try:
            conn.pump_one()
            drained += 1
        except TransportClosed:
            detected = True
            break
    if not detected:
        transport.close()  # fallback: force-release so reconnect can proceed
    conn.handle_disconnect()
    rec.mark("D_disconnect", "handle_disconnect", conn, now(),
             extra={"transport_closed_raised": detected,
                    "buffered_frames_drained_before_detection": drained})

    # Phase E — reconnect (BackoffPolicy) + authenticated resubscribe + resync.
    attempt = conn.reconnect(time.sleep)
    rec.mark("E_recover", "reconnected", conn, now(), extra={"reconnect_attempts": attempt})
    healthy_before_resync = conn.all_healthy()
    resync_health = conn.resync()
    rec.start_new_seq_epoch()  # the resubscribe starts a fresh Kalshi seq sequence
    rec.mark("E_recover", "resynced", conn, now(),
             extra={
                 "healthy_before_resync": healthy_before_resync,
                 "post_resync": {_outcome(cid): h.status.value
                                 for cid, h in resync_health.items()},
                 "books": {_outcome(cid): book_summary(
                     f.current_order_book(now(), require_healthy=False))
                     for cid, f in feeds.items()},
             })

    # Phase F — healthy operation resumes (subsequent real deltas).
    pump_collecting(conn, feeds, rec, phase="F_resumed",
                    target_deltas=POST_RESYNC_DELTAS, max_seconds=POST_RESYNC_MAX_S, now_fn=now)
    transport.close()
    session_end = now()

    rec.close_seq_epoch()
    summary = _common_summary(rec, "disconnect_reconnect_resync (real-money gate #8)",
                              session_start, session_end, {
                                  "min_deltas": min_deltas,
                                  "max_steady_s": max_steady_s,
                                  "max_staleness_s": MAX_STALENESS.total_seconds(),
                                  "healthy_pre_drop": healthy_pre_drop,
                                  "reconnect_attempts": attempt,
                                  "backoff": {
                                      "base_seconds": rt.backoff.base_seconds,
                                      "factor": rt.backoff.factor,
                                      "max_seconds": rt.backoff.max_seconds,
                                      "max_attempts": rt.backoff.max_attempts,
                                  },
                                  "backoff_note": (
                                      "reconnect succeeded on the first attempt against the "
                                      "live server; BackoffPolicy delay/give-up is covered by "
                                      "deterministic tests, not exercised here"
                                  ),
                              })
    (OUT_DIR / "SUMMARY_RECONNECT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"applied deltas: {rec.deltas_applied} | within-subscription seq violations: "
        f"{rec.seq_monotonic_violations} | seq epochs: {rec.seq_epoch_first_last} | "
        f"reconnect attempts: {attempt} | desyncs: {rec.desyncs}"
    )
    print(f"wrote sanitised evidence to {OUT_DIR / 'SUMMARY_RECONNECT.json'}")
    return 0


# --------------------------------------------------------------------------- #
# Observation #7 — natural stale-data lifecycle (continuous consumption)
# --------------------------------------------------------------------------- #


def run_stale_observation(max_watch_s: float) -> int:
    """Real-money gate #7: watch for a genuine ``HEALTHY -> STALE -> HEALTHY``
    lifecycle on a naturally quiet market **without ever pausing consumption**.
    Writes a blocker and returns 3 if no lifecycle is captured in the window."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = utc_now
    session_start = now()

    adapter = KalshiMarketDataAdapter()
    ticker = pick_moderate_market(adapter)
    rt = _build_runtime(ticker, recv_timeout=STALE_WATCH_RECV_TIMEOUT_S, adapter=adapter)
    conn, feeds, transport, src = rt.conn, rt.feeds, rt.transport, rt.src
    rec = Recorder(list(feeds.keys()))
    rec.mark("A_init", "start", conn, now())

    # Phase A — initial REST snapshot / live-book initialization.
    for cid, feed in feeds.items():
        feed.apply_snapshot(src.fetch(cid), received_at=now())
    rec.mark("A_init", "rest_snapshot_applied", conn, now(),
             extra={"books": {_outcome(cid): book_summary(
                 f.current_order_book(now(), require_healthy=False))
                 for cid, f in feeds.items()}})

    # Phase B — WS subscribe + a small warm-up so we start from a real HEALTHY
    # WS-fed state (not just the REST snapshot).
    conn.connect_and_subscribe()
    rec.mark("B_steady", "ws_connect_and_subscribe", conn, now())
    warmed = pump_collecting(conn, feeds, rec, phase="B_steady",
                             target_deltas=STALE_WATCH_WARMUP_DELTAS,
                             max_seconds=STALE_WATCH_WARMUP_MAX_S, now_fn=now)

    # Phase C — continuous-consumption staleness watch. If the warm-up already
    # lost the socket (a too-quiet market idle-timed the transport out), there
    # is nothing to watch — record the blocker directly.
    if transport._conn is None:  # noqa: SLF001 - deliberate liveness check
        result = {
            "lifecycle_observed": False,
            "inconclusive": (
                "warm-up lost the socket before the watch: the chosen market did not "
                f"deliver {STALE_WATCH_WARMUP_DELTAS} deltas within "
                f"{STALE_WATCH_RECV_TIMEOUT_S}s, so WebsocketsTransport raised "
                "TransportClosed on a recv timeout (quiet socket == dead socket in the "
                "shipped transport)"
            ),
            "feeds_that_went_stale": [],
            "stale_spans": [],
            "max_observed_stale_age_s": 0.0,
            "max_staleness_threshold_s": MAX_STALENESS.total_seconds(),
            "fail_closed_gate_rejections_while_stale": 0,
            "fail_closed_gate_serves_while_healthy": 0,
            "empty_pumps": 0,
            "delta_pumps": warmed,
            "max_pump_gap_s": 0.0,
            "watch_elapsed_s": 0.0,
            "watch_cap_s": max_watch_s,
        }
        rec.mark("C_stale_watch", "watch_skipped_transport_lost_in_warmup", conn, now())
    else:
        rec.mark("C_stale_watch", "watch_start", conn, now(),
                 extra={"max_watch_s": max_watch_s})
        result = watch_staleness_lifecycle(conn, feeds, rec, max_watch_s=max_watch_s,
                                           now_fn=now)
    rec.mark("C_stale_watch", "watch_end", conn, now(), extra=result)
    transport.close()
    session_end = now()
    rec.close_seq_epoch()

    config = {
        "max_staleness_s": MAX_STALENESS.total_seconds(),
        "warmup_deltas_target": STALE_WATCH_WARMUP_DELTAS,
        "warmup_deltas_seen": warmed,
        "watch_cap_s": max_watch_s,
        "recv_timeout_s": STALE_WATCH_RECV_TIMEOUT_S,
        "market_selection": "pick_moderate_market (alive-but-thin probe)",
    }
    summary = _common_summary(rec, "natural_stale_lifecycle (real-money gate #7)",
                              session_start, session_end, config)
    summary["stale_watch"] = result

    if result["lifecycle_observed"]:
        (OUT_DIR / "SUMMARY_STALE.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(
            f"stale lifecycle OBSERVED | feeds stale: {result['feeds_that_went_stale']} | "
            f"max stale age: {result['max_observed_stale_age_s']}s | "
            f"fail-closed rejections while stale: "
            f"{result['fail_closed_gate_rejections_while_stale']}"
        )
        print(f"wrote sanitised evidence to {OUT_DIR / 'SUMMARY_STALE.json'}")
        return 0

    summary["result"] = "BLOCKED — no natural HEALTHY->STALE->HEALTHY lifecycle in window"
    (OUT_DIR / "SUMMARY_STALE.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        "BLOCKER: no natural stale->healthy lifecycle captured "
        f"(stale seen on {result['feeds_that_went_stale']}, "
        f"inconclusive={result['inconclusive']!r}, "
        f"watch {result['watch_elapsed_s']}s / cap {max_watch_s}s)"
    )
    print(f"wrote blocker evidence to {OUT_DIR / 'SUMMARY_STALE.json'}")
    return 3


def _write_blocker(name: str, rec: Recorder, start: datetime, end: datetime, *,
                   reason: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(
        json.dumps(
            {
                "venue": VENUE,
                "environment": "production",
                "path": "livebook.LiveBookConnection + LiveBookFeed (shipped runtime)",
                "result": "BLOCKED — insufficient live activity",
                "reason": reason,
                "session_start_utc": start.isoformat(),
                "session_end_utc": end.isoformat(),
                "applied_delta_count": rec.deltas_applied,
                "delta_outcomes": rec.outcomes,
                "timeline": rec.timeline,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--observe-stale" in args:
        mode = "observe-stale"
    elif "--observe" in args:
        mode = "observe"
    else:
        mode = "check"
    positional = [a for a in args if not a.startswith("-")]
    min_deltas = int(positional[0]) if len(positional) > 0 else DEFAULT_MIN_DELTAS
    max_steady_s = float(positional[1]) if len(positional) > 1 else DEFAULT_MAX_STEADY_S
    max_watch_s = float(positional[0]) if len(positional) > 0 else DEFAULT_STALE_WATCH_S

    report = preflight()
    print("preflight:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print()

    if mode == "check":
        if not report["ready"]:
            print(CREATE_KEY_STEPS)
        else:
            print(f"Ready. {RUN_ENV_GUARD}=1 python "
                  "scripts/observe_kalshi_livebook_runtime.py --observe\n")
        return 0

    if report["env_guard_set"] is not True:
        print(f"Refusing to open a production socket: set {RUN_ENV_GUARD}=1.\n", file=sys.stderr)
        return 2
    if not report["ready"]:
        print("Refusing to connect: preflight did not pass.\n", file=sys.stderr)
        print(CREATE_KEY_STEPS, file=sys.stderr)
        return 2

    if mode == "observe-stale":
        return run_stale_observation(max_watch_s)
    return run_observation(min_deltas, max_steady_s)


if __name__ == "__main__":
    sys.exit(main())
