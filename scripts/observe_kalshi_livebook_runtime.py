"""Bounded **read-only** production observation of Kalshi market data driven
through the shipped live-book runtime — `livebook.LiveBookConnection` +
`livebook.LiveBookFeed` — not the standalone WS smoke script.

Real-money gate #2 / #7 / #8 and assumption A-028 need evidence from the *actual*
code path a live trader would use. This harness:

1. Initializes each feed from a **REST snapshot** (`KalshiMarketDataAdapter`,
   public prod REST — no auth).
2. Opens the **authenticated production WebSocket** with the read-only signer
   (`scripts.kalshi_signer.OpensslRsaPssSigner`, Keychain key id) and
   `subscribe`s one verified market's `orderbook_delta`.
3. Pumps frames through `LiveBookConnection.pump_one()` for a bounded window,
   applying deltas via `LiveBookFeed` and recording every `DeltaOutcome`,
   `HealthStatus`, `seq`, and a value-free book fingerprint.
4. Exercises the staleness path: stops consuming for `> max_staleness` and
   records the `STALE` verdict.
5. Induces **exactly one** controlled disconnect (closes the underlying socket),
   then drives `handle_disconnect()` -> `reconnect()` -> `resync()` and records
   the `DISCONNECTED -> RESYNCING -> HEALTHY` transition, confirming healthy is
   restored **only after** the post-reconnect fresh snapshot.
6. Pumps a few more frames to show healthy operation resumes.

Everything is read-only market data. There is **no** code path here to submit /
cancel / modify an order, read balances / positions / fills, move funds, set
`LIVE_TRADING`, or touch Polymarket US. The signer is used only for the
market-data WS handshake.

Run modes::

    python scripts/observe_kalshi_livebook_runtime.py                 # --check (no socket)
    PMA_KALSHI_PROD_WS_OBSERVE=1 \
        python scripts/observe_kalshi_livebook_runtime.py --observe [MIN_DELTAS] [MAX_STEADY_S]

Sanitized evidence -> ``docs/evidence/kalshi-live/livebook-runtime/SUMMARY.json``:
a phase-by-phase timeline with UTC timestamps + per-phase offsets, health-status
transitions, `DeltaOutcome` tallies, `seq` monotonicity, book-fingerprint change
counts, and an additive-delta (A-028) relationship check — **no** raw prices,
sizes, tickers, or market ids.
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
    LiveBookConnection,
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


def pick_liquid_market(adapter: KalshiMarketDataAdapter) -> str:
    candidates: list[str] = []
    for series in _ACTIVE_SERIES:
        page = adapter.list_markets(status="open", series_ticker=series, limit=100)
        candidates += [m.id for m in page.markets]
        if len(candidates) >= 40:
            break
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


# --------------------------------------------------------------------------- #
# The observation
# --------------------------------------------------------------------------- #


def run_observation(min_deltas: int, max_steady_s: float) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = utc_now
    session_start = now()

    key_id = read_keychain_password(KEYCHAIN_SERVICE)
    signer = OpensslRsaPssSigner(PEM_PATH)
    credentials = KalshiCredentials(api_key_id=key_id, private_key_pem=PEM_PATH.read_text())

    adapter = KalshiMarketDataAdapter()
    ticker = pick_liquid_market(adapter)
    yes_c, no_c = build_contracts(adapter.get_market(ticker))
    feeds = {
        yes_c.id: LiveBookFeed(contract=yes_c, venue=VENUE, max_staleness=MAX_STALENESS),
        no_c.id: LiveBookFeed(contract=no_c, venue=VENUE, max_staleness=MAX_STALENESS),
    }
    src = RestSnapshotSource(adapter)
    transport = WebsocketsTransport(recv_timeout=RECV_TIMEOUT_S)

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
        backoff=BackoffPolicy(base_seconds=1.0, factor=2.0, max_seconds=8.0, max_attempts=6),
    )
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
        _write_blocker(rec, session_start, now(), ticker_seen=True, reason=reason)
        print(f"BLOCKER: {reason} — evidence not collected")
        transport.close()
        return 3

    # Phase C — staleness path: stop consuming for > max_staleness, read health.
    pause = MAX_STALENESS.total_seconds() + 5.0
    rec.mark("C_stale", "pause_consumption_start", conn, now(), extra={"pause_s": pause})
    time.sleep(pause)
    stale_health = {_outcome(cid): h.status.value for cid, h in conn.feed_health().items()}
    rec.mark("C_stale", "health_after_pause", conn, now(), extra={"observed": stale_health})

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

    # Phase E — reconnect + resubscribe + resync.
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

    # Phase F — healthy operation resumes.
    pump_collecting(conn, feeds, rec, phase="F_resumed",
                    target_deltas=POST_RESYNC_DELTAS, max_seconds=POST_RESYNC_MAX_S, now_fn=now)
    transport.close()
    session_end = now()

    rec.close_seq_epoch()
    summary = _build_summary(rec, session_start, session_end, min_deltas, max_steady_s)
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"applied deltas: {rec.deltas_applied} | within-subscription seq violations: "
        f"{rec.seq_monotonic_violations} | seq epochs: {rec.seq_epoch_first_last} | "
        f"fingerprint changes: {rec.fingerprint_changes} | additive {rec.additive_matches}/"
        f"{rec.additive_checked} | desyncs: {rec.desyncs}"
    )
    print(f"wrote sanitised evidence to {OUT_DIR}")
    return 0


def _build_summary(rec: Recorder, start: datetime, end: datetime,
                   min_deltas: int, max_steady_s: float) -> dict[str, Any]:
    statuses_seen: list[str] = []
    for entry in rec.timeline:
        for h in entry["health"].values():
            if h["status"] not in statuses_seen:
                statuses_seen.append(h["status"])
    return {
        "venue": VENUE,
        "environment": "production",
        "path": "livebook.LiveBookConnection + LiveBookFeed (shipped runtime)",
        "market_ticker": "<redacted>",
        "session_start_utc": start.isoformat(),
        "session_end_utc": end.isoformat(),
        "wall_elapsed_s": round((end - start).total_seconds(), 3),
        "config": {
            "min_deltas": min_deltas,
            "max_steady_s": max_steady_s,
            "max_staleness_s": MAX_STALENESS.total_seconds(),
        },
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
            "no balances/positions/fills; no funds; LIVE_TRADING untouched",
            "signer used only for the market-data WS handshake; no Polymarket US",
        ],
    }


def _write_blocker(rec: Recorder, start: datetime, end: datetime, *,
                   ticker_seen: bool, reason: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "SUMMARY.json").write_text(
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
    mode = "--observe" if "--observe" in args else "--check"
    positional = [a for a in args if not a.startswith("-")]
    min_deltas = int(positional[0]) if len(positional) > 0 else DEFAULT_MIN_DELTAS
    max_steady_s = float(positional[1]) if len(positional) > 1 else DEFAULT_MAX_STEADY_S

    report = preflight()
    print("preflight:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print()

    if mode == "--check":
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
    return run_observation(min_deltas, max_steady_s)


if __name__ == "__main__":
    sys.exit(main())
