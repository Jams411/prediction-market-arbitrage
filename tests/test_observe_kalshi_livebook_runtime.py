"""Deterministic, offline tests for ``scripts/observe_kalshi_livebook_runtime.py``.

No socket, no real credential: the WebSocket transport, the REST snapshot
source, and the Keychain lookup are all fakes. What is pinned here is that the
harness drives the *shipped* ``LiveBookConnection`` / ``LiveBookFeed`` correctly —
snapshot init, applied deltas, monotonic ``seq``, book mutation, the additive
(A-028) relationship check, and the DISCONNECTED -> RESYNCING -> HEALTHY
ordering — and that it stays read-only.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import observe_kalshi_livebook_runtime as obs
import pytest
from livebook_support import (
    FakeSnapshotSource,
    FakeWebSocketTransport,
    RecordingSleep,
    kalshi_contract,
    kalshi_delta_frame,
    kalshi_snapshot_frame,
    levels,
)

from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.livebook import (
    BackoffPolicy,
    BookSnapshot,
    DeltaOutcome,
    Handshake,
    HealthStatus,
    LiveBookConnection,
    LiveBookFeed,
    TransportClosed,
    kalshi_frame_decoder,
    kalshi_subscribe_command,
)
from prediction_market_arbitrage.livebook.updates import BookDelta

SOURCE = Path(obs.__file__).read_text()
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
TICKER = "LIVEBOOK-TEST-T1"


def _now() -> datetime:
    return NOW


def _order_book(
    outcome: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]]
) -> OrderBook:
    return OrderBook(
        contract=kalshi_contract(outcome, ticker=TICKER),
        bids=levels(bids),
        asks=levels(asks),
        timestamp=NOW,
    )


# --------------------------------------------------------------------------- #
# RestSnapshotSource
# --------------------------------------------------------------------------- #


class _FakeBooks:
    def __init__(self, yes: OrderBook, no: OrderBook) -> None:
        self.yes = yes
        self.no = no


class _FakeAdapter:
    def __init__(self, books: _FakeBooks) -> None:
        self._books = books
        self.calls = 0

    def get_order_books(self, ticker: str) -> _FakeBooks:
        self.calls += 1
        return self._books


def test_rest_snapshot_source_adapts_and_memoises() -> None:
    books = _FakeBooks(
        yes=_order_book("YES", [("0.40", "10")], [("0.60", "7")]),
        no=_order_book("NO", [("0.40", "7")], [("0.60", "10")]),
    )
    adapter = _FakeAdapter(books)
    src = obs.RestSnapshotSource(adapter)  # type: ignore[arg-type]

    yes_snap = src.fetch(f"{TICKER}:YES")
    no_snap = src.fetch(f"{TICKER}:NO")

    assert isinstance(yes_snap, BookSnapshot)
    assert yes_snap.venue == "kalshi"
    assert yes_snap.contract_id == f"{TICKER}:YES"
    assert yes_snap.sequence is None
    assert yes_snap.source_time == NOW
    assert [(str(lvl.price), str(lvl.quantity)) for lvl in yes_snap.bids] == [("0.40", "10")]
    assert [(str(lvl.price), str(lvl.quantity)) for lvl in no_snap.asks] == [("0.60", "10")]
    assert adapter.calls == 1  # 2 s memo: YES + NO share one REST round-trip


def test_rest_snapshot_source_rejects_bad_contract_id() -> None:
    src = obs.RestSnapshotSource(_FakeAdapter(_FakeBooks(  # type: ignore[arg-type]
        _order_book("YES", [("0.4", "1")], [("0.6", "1")]),
        _order_book("NO", [("0.4", "1")], [("0.6", "1")]),
    )))
    with pytest.raises(ValueError, match="unexpected contract id"):
        src.fetch("LIVEBOOK-TEST-T1:MAYBE")


# --------------------------------------------------------------------------- #
# fingerprint / summary / qty helpers
# --------------------------------------------------------------------------- #


def test_book_fingerprint_is_stable_and_value_free() -> None:
    ob1 = _order_book("YES", [("0.40", "10")], [("0.60", "7")])
    ob2 = _order_book("YES", [("0.40", "10")], [("0.60", "7")])
    ob3 = _order_book("YES", [("0.40", "11")], [("0.60", "7")])
    fp1 = obs.book_fingerprint(ob1)
    assert fp1 == obs.book_fingerprint(ob2)
    assert fp1 != obs.book_fingerprint(ob3)
    assert fp1 is not None and len(fp1) == 16 and all(c in "0123456789abcdef" for c in fp1)
    assert obs.book_fingerprint(None) is None


def test_recorder_segments_seq_monotonicity_per_subscription_epoch() -> None:
    rec = obs.Recorder(["c:YES"])
    for s in (2, 3, 4):
        rec.note_delta("c:YES", DeltaOutcome.APPLIED, s,
                       additive_ok=None, removed_on_zero=False, fp=None)
    rec.start_new_seq_epoch()
    for s in (1, 2):  # Kalshi restarts seq for the new subscription
        rec.note_delta("c:YES", DeltaOutcome.APPLIED, s,
                       additive_ok=None, removed_on_zero=False, fp=None)
    rec.close_seq_epoch()
    assert rec.seq_monotonic_violations == 0  # the reset is not a violation
    assert rec.seq_reset_on_resubscribe is True
    assert rec.seq_epoch_first_last == [[2, 4], [1, 2]]


def test_timeline_health_keys_are_sanitised_to_outcome_labels() -> None:
    """The recorder must key health/books by YES/NO, never by the full contract
    id — the production market ticker must not reach the evidence file."""
    assert obs._outcome("KXBTCD-26SEP1017-T79499.99:YES") == "YES"
    assert obs._outcome("some-slug:NO") == "NO"

    contract = kalshi_contract("YES", ticker="KXBTCD-26SEP1017-T79499.99")
    feed = LiveBookFeed(contract=contract, venue="kalshi", max_staleness=obs.MAX_STALENESS)
    feeds = {contract.id: feed}
    conn = _connection(FakeWebSocketTransport([]), feeds, FakeSnapshotSource({}))
    rec = obs.Recorder(list(feeds))
    rec.mark("A", "start", conn, NOW)
    assert set(rec.timeline[0]["health"]) == {"YES"}
    assert "KXBTCD-26SEP1017-T79499.99" not in json.dumps(rec.timeline)


def test_qty_at_reads_the_matching_level() -> None:
    ob = _order_book("YES", [("0.40", "10")], [("0.60", "7")])
    bid_delta = BookDelta(venue="kalshi", contract_id=f"{TICKER}:YES", side="bid",
                          price=Decimal("0.40"), quantity_delta=Decimal("1"),
                          sequence=2, source_time=None)
    ask_delta = BookDelta(venue="kalshi", contract_id=f"{TICKER}:YES", side="ask",
                          price=Decimal("0.99"), quantity_delta=Decimal("1"),
                          sequence=3, source_time=None)
    assert obs._qty_at(ob, bid_delta) == Decimal("10")
    assert obs._qty_at(ob, ask_delta) == 0
    assert obs._qty_at(None, bid_delta) is None


# --------------------------------------------------------------------------- #
# pump_collecting through the real LiveBookConnection / LiveBookFeed
# --------------------------------------------------------------------------- #


def _connection(transport: FakeWebSocketTransport, feeds: dict[str, LiveBookFeed],
                src: FakeSnapshotSource) -> LiveBookConnection:
    return LiveBookConnection(
        venue="kalshi",
        feeds=list(feeds.values()),
        transport=transport,
        handshake_factory=lambda: Handshake(url="wss://x", headers={}),
        subscribe_command=kalshi_subscribe_command(command_id=1, market_tickers=[TICKER]),
        decode=kalshi_frame_decoder,
        snapshot_source=src,
        clock=_now,
        backoff=BackoffPolicy(base_seconds=0.0001, factor=1.0, max_seconds=0.001, max_attempts=3),
    )


def test_pump_collecting_records_applied_deltas_monotonic_seq_and_additivity() -> None:
    yes_feed = LiveBookFeed(contract=kalshi_contract("YES", ticker=TICKER), venue="kalshi",
                            max_staleness=obs.MAX_STALENESS)
    no_feed = LiveBookFeed(contract=kalshi_contract("NO", ticker=TICKER), venue="kalshi",
                           max_staleness=obs.MAX_STALENESS)
    feeds = {yes_feed.contract.id: yes_feed, no_feed.contract.id: no_feed}

    # Snapshot then three positive-add deltas on the YES bid at 0.40. Each frame
    # also produces the implied NO ask at 0.60; both sides add cleanly (no
    # removal, no negative) so the additive relationship is unambiguous.
    frames = [
        json.dumps(kalshi_snapshot_frame(seq=1, yes_fp=[("0.40", "10"), ("0.30", "5")],
                                         no_fp=[("0.55", "8")], ticker=TICKER)),
        json.dumps(kalshi_delta_frame(seq=2, side="yes", price_dollars="0.40",
                                      delta_fp="3.00", ticker=TICKER)),
        json.dumps(kalshi_delta_frame(seq=3, side="yes", price_dollars="0.30",
                                      delta_fp="4.00", ticker=TICKER)),
        json.dumps(kalshi_delta_frame(seq=4, side="yes", price_dollars="0.40",
                                      delta_fp="2.00", ticker=TICKER)),
    ]
    transport = FakeWebSocketTransport(frames)
    src = FakeSnapshotSource({})
    conn = _connection(transport, feeds, src)
    conn.connect_and_subscribe()
    conn.pump_one()  # consume the snapshot

    rec = obs.Recorder(list(feeds))
    applied = obs.pump_collecting(conn, feeds, rec, phase="B", target_deltas=6,
                                  max_seconds=5.0, now_fn=_now)

    assert applied >= 4  # 3 frames x (YES bid + implied NO ask)
    assert rec.deltas_applied >= 4
    assert rec.seq_monotonic_violations == 0
    rec.close_seq_epoch()
    assert rec.seq_epoch_first_last == [[2, 4]]  # monotone within the subscription
    assert rec.desyncs == 0
    # every checked delta obeyed qty_after == qty_before + delta_fp
    assert rec.additive_checked >= 3
    assert rec.additive_mismatches == 0
    assert rec.additive_matches == rec.additive_checked
    assert rec.fingerprint_changes >= 1


# --------------------------------------------------------------------------- #
# disconnect -> reconnect -> resync ordering (healthy ONLY after resync)
# --------------------------------------------------------------------------- #


def test_healthy_restored_only_after_post_reconnect_resync() -> None:
    contract = kalshi_contract("YES", ticker=TICKER)
    feed = LiveBookFeed(contract=contract, venue="kalshi", max_staleness=obs.MAX_STALENESS)
    feeds = {contract.id: feed}

    resync_snap = BookSnapshot(venue="kalshi", contract_id=contract.id,
                               bids=levels([("0.41", "9")]), asks=levels([("0.59", "9")]),
                               sequence=None, source_time=NOW)
    frames = [
        json.dumps(kalshi_snapshot_frame(seq=1, yes_fp=[("0.40", "10")], no_fp=None,
                                         ticker=TICKER)),
        json.dumps(kalshi_delta_frame(seq=2, side="yes", price_dollars="0.40",
                                      delta_fp="1.00", ticker=TICKER)),
        TransportClosed,  # induced drop on the next receive
    ]
    transport = FakeWebSocketTransport(frames)
    src = FakeSnapshotSource({contract.id: resync_snap})
    conn = _connection(transport, feeds, src)

    conn.connect_and_subscribe()
    conn.pump_one()  # snapshot -> HEALTHY
    conn.pump_one()  # delta
    assert conn.feed_health()[contract.id].status is HealthStatus.HEALTHY

    with pytest.raises(Exception):  # noqa: B017,PT011 - TransportClosed from the fake
        conn.pump_one()
    conn.handle_disconnect()
    assert conn.feed_health()[contract.id].status is HealthStatus.DISCONNECTED
    assert conn.all_healthy() is False

    conn.reconnect(RecordingSleep())
    assert conn.all_healthy() is False  # reconnect alone does NOT restore health

    conn.resync()
    assert conn.all_healthy() is True
    assert conn.feed_health()[contract.id].status is HealthStatus.HEALTHY
    assert src.fetched == [contract.id]  # the fresh snapshot came from REST


# --------------------------------------------------------------------------- #
# entry point + read-only guards
# --------------------------------------------------------------------------- #


def _stub_preflight(monkeypatch: pytest.MonkeyPatch, **over: Any) -> None:
    report = {"openssl_on_path": True, "private_key_file_present": False,
              "keychain_key_id": "absent", "env_guard_set": False, "ready": False}
    report.update(over)
    monkeypatch.setattr(obs, "preflight", lambda: report)


def test_check_mode_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch)
    monkeypatch.setattr(obs, "run_observation",
                        lambda *a: (_ for _ in ()).throw(AssertionError("must not run")))
    assert obs.main(["--check"]) == 0


def test_observe_refuses_without_env_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch, ready=True, env_guard_set=False)
    monkeypatch.setattr(obs, "run_observation",
                        lambda *a: (_ for _ in ()).throw(AssertionError("must not run")))
    assert obs.main(["--observe"]) == 2


def test_observe_runs_when_ready_and_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch, ready=True, env_guard_set=True)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(obs, "run_observation",
                        lambda md, ms: seen.update(md=md, ms=ms) or 0)
    assert obs.main(["--observe", "5", "60"]) == 0
    assert seen == {"md": 5, "ms": 60.0}


def test_no_account_or_trading_path_in_module() -> None:
    tree = ast.parse(SOURCE)
    pathy = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and ("://" in n.value or n.value.strip().startswith("/"))
    ]
    for lit in pathy:
        low = lit.lower()
        for bad in ("/portfolio", "events/orders", "/orders/", "target_balance"):
            assert bad not in low, f"forbidden path {bad!r} in {lit!r}"
        assert "polymarket" not in low
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "LIVE_TRADING" not in names | attrs
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("live_broker" in m or "trading" in m for m in imported)
