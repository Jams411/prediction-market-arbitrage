"""Deterministic failure-path scenarios (Milestone M3.2).

One section per ``docs/ROADMAP.md`` M3.2 bullet. Each scenario drives an
*existing* seam / fake with a modelled failure and asserts the fail-closed
contract — and the designed recovery / resync where one exists. No network, no
wall-clock, no new production feature: every failure is injected.

These are *modelled* failure scenarios. Any real defect found while writing them
is recorded separately in ``docs/PROJECT_JOURNAL.md`` / ``docs/ASSUMPTIONS.md``,
not hidden inside a passing test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import arbitrage_support as arb
import pytest
import risk_support
from dashboard_support import MAX_STALENESS
from livebook_support import (
    FakeSnapshotSource,
    FakeWebSocketTransport,
    RecordingSleep,
    kalshi_contract,
)

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    EngineConfig,
    FixedPerUnitFeeModel,
)
from prediction_market_arbitrage.arbitrage.errors import ArbitrageError
from prediction_market_arbitrage.dashboard import Severity, build_dashboard
from prediction_market_arbitrage.livebook import (
    BackoffPolicy,
    BookSnapshot,
    HealthStatus,
    LiveBookConnection,
    LiveBookError,
    TransportClosed,
)
from prediction_market_arbitrage.livebook.state import LiveBookFeed
from prediction_market_arbitrage.paper_broker import (
    OrderRequest,
    OrderStatus,
    PaperBroker,
    PaperBrokerConfig,
    PaperBrokerError,
)
from prediction_market_arbitrage.recorder import Recorder, RecorderError, initialize
from prediction_market_arbitrage.registry import PairStatus
from prediction_market_arbitrage.replay import ReplaySession
from prediction_market_arbitrage.replay.errors import ReplayError
from prediction_market_arbitrage.risk import RiskLimits, RiskManager

T0 = risk_support.T0
CID = kalshi_contract().id


def _healthy_feed_at(snapshot_at: datetime = T0, *, seq: int = 1) -> LiveBookFeed:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=CID,
            bids=(),
            asks=(),
            sequence=seq,
            source_time=snapshot_at,
        ),
        received_at=snapshot_at,
    )
    return lb


def _kalshi_snapshot(*, seq: int) -> BookSnapshot:
    return BookSnapshot(
        venue="kalshi",
        contract_id=CID,
        bids=(),
        asks=(),
        sequence=seq,
        source_time=T0,
    )


# ======================================================================= #
# 1. Venue disconnects
# ======================================================================= #


def test_disconnect_disables_trading_until_a_fresh_snapshot() -> None:
    lb = _healthy_feed_at()
    assert lb.health(T0).trading_enabled is True

    lb.mark_disconnected(at=T0 + timedelta(seconds=1))
    down = lb.health(T0 + timedelta(seconds=1))
    assert down.status is HealthStatus.DISCONNECTED
    assert down.trading_enabled is False

    # Designed recovery: begin_resync -> fresh snapshot -> HEALTHY again.
    lb.begin_resync(at=T0 + timedelta(seconds=2))
    assert lb.health(T0 + timedelta(seconds=2)).status is HealthStatus.RESYNCING
    lb.apply_snapshot(_kalshi_snapshot(seq=2), received_at=T0 + timedelta(seconds=3))
    assert lb.health(T0 + timedelta(seconds=3)).trading_enabled is True


def test_connection_reconnects_with_backoff_then_resyncs_to_healthy() -> None:
    feed_a = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    attempts = {"n": 0}

    class FlakyTransport(FakeWebSocketTransport):
        def connect(self, handshake: object) -> None:
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise TransportClosed("connect failed")

    transport = FlakyTransport()
    conn = LiveBookConnection(
        venue="kalshi",
        feeds=[feed_a],
        transport=transport,
        handshake_factory=lambda: object(),  # type: ignore[arg-type,return-value]
        subscribe_command={"cmd": "subscribe"},
        decode=lambda frame: [],
        snapshot_source=FakeSnapshotSource({CID: _kalshi_snapshot(seq=9)}),
        clock=lambda: T0,
        backoff=BackoffPolicy(base_seconds=1.0, factor=2.0, max_seconds=8.0),
    )
    conn.handle_disconnect()
    assert feed_a.health(T0).trading_enabled is False

    sleep = RecordingSleep()
    succeeded_on = conn.reconnect(sleep)
    assert succeeded_on == 2
    assert sleep.calls == [1.0, 2.0]  # deterministic backoff before the 3rd try

    health = conn.resync()
    assert health[CID].trading_enabled is True


def test_reconnect_gives_up_after_max_attempts_and_stays_failed_closed() -> None:
    feed_a = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)

    class DeadTransport(FakeWebSocketTransport):
        def connect(self, handshake: object) -> None:
            raise TransportClosed("always down")

    conn = LiveBookConnection(
        venue="kalshi",
        feeds=[feed_a],
        transport=DeadTransport(),
        handshake_factory=lambda: object(),  # type: ignore[arg-type,return-value]
        subscribe_command={"cmd": "subscribe"},
        decode=lambda frame: [],
        snapshot_source=FakeSnapshotSource({CID: _kalshi_snapshot(seq=1)}),
        clock=lambda: T0,
        backoff=BackoffPolicy(base_seconds=1.0, max_attempts=3),
    )
    conn.handle_disconnect()
    with pytest.raises(TransportClosed):
        conn.reconnect(RecordingSleep())
    assert conn.all_healthy() is False


def test_disconnect_is_visible_on_the_dashboard_and_vetoes_opportunities() -> None:
    lb = _healthy_feed_at()
    lb.mark_disconnected(at=T0)
    view = build_dashboard(now=T0, feeds=[lb])
    (fv,) = view.feeds
    assert fv.severity is Severity.ALERT
    assert view.healthy is False

    # Risk gate consuming the same FeedHealth fails closed.
    rm = RiskManager(RiskLimits(max_data_age=timedelta(seconds=1)))
    decision = rm.evaluate_opportunity(
        risk_support.opportunity(net_edge_total="5"), now=T0, health=lb.health(T0)
    )
    assert decision.allowed is False


# ======================================================================= #
# 2. Stale prices
# ======================================================================= #


def test_stale_feed_disables_trading_and_recovers_on_next_update() -> None:
    lb = _healthy_feed_at()
    stale_at = T0 + MAX_STALENESS + timedelta(seconds=1)
    verdict = lb.health(stale_at)
    assert verdict.status is HealthStatus.STALE
    assert verdict.trading_enabled is False

    lb.apply_snapshot(_kalshi_snapshot(seq=2), received_at=stale_at)
    assert lb.health(stale_at).trading_enabled is True


def test_engine_rejects_a_book_older_than_max_book_age() -> None:
    engine = ArbitrageEngine(config=EngineConfig(max_book_age=timedelta(seconds=30)))
    old = arb.TS - timedelta(minutes=5)
    result = engine.evaluate(
        arb.make_record(),
        arb.kalshi_book([("0.40", "100")], timestamp=old),
        arb.polymarket_book([("0.55", "100")], timestamp=old),
        evaluation_time=arb.EVAL_TIME,
        requested_quantity=Decimal("10"),
    )
    assert result.has_opportunity is False
    assert result.rejection_reason != ""


def test_risk_rejects_stale_market_data_by_age() -> None:
    rm = RiskManager(RiskLimits(max_data_age=timedelta(seconds=30)))
    stale_health = risk_support.health(
        status=HealthStatus.STALE, last_update=T0 - timedelta(minutes=10), as_of=T0
    )
    decision = rm.evaluate_opportunity(
        risk_support.opportunity(net_edge_total="5"), now=T0, health=stale_health
    )
    assert decision.allowed is False
    assert any("age" in r or "not healthy" in r for r in decision.reasons)


def test_future_dated_market_data_is_rejected_not_trusted() -> None:
    rm = RiskManager(RiskLimits(max_data_age=timedelta(seconds=30)))
    future = risk_support.health(last_update=T0 + timedelta(minutes=5), as_of=T0)
    decision = rm.evaluate_opportunity(
        risk_support.opportunity(net_edge_total="5"), now=T0, health=future
    )
    assert decision.allowed is False


# ======================================================================= #
# 3. Empty / malformed books
# ======================================================================= #


def test_empty_ask_side_is_never_an_opportunity() -> None:
    engine = ArbitrageEngine()
    result = engine.evaluate(
        arb.make_record(),
        arb.kalshi_book([]),  # empty asks
        arb.polymarket_book([("0.55", "100")]),
        evaluation_time=arb.EVAL_TIME,
        requested_quantity=Decimal("10"),
    )
    assert result.has_opportunity is False
    assert "empty ask" in result.rejection_reason


def test_duplicate_price_levels_in_a_snapshot_are_rejected() -> None:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    dupe = BookSnapshot(
        venue="kalshi",
        contract_id=CID,
        bids=(),
        asks=arb._levels([("0.40", "10"), ("0.40", "20")]),
        sequence=1,
        source_time=T0,
    )
    with pytest.raises(LiveBookError):
        lb.apply_snapshot(dupe, received_at=T0)


def test_a_delta_that_would_cross_the_book_desyncs_the_feed() -> None:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=CID,
            bids=arb._levels([("0.40", "100")]),
            asks=arb._levels([("0.60", "100")]),
            sequence=1,
            source_time=T0,
        ),
        received_at=T0,
    )
    from prediction_market_arbitrage.livebook import BookDelta

    crossing = BookDelta(
        venue="kalshi",
        contract_id=CID,
        side="bid",
        price=Decimal("0.70"),  # bid above the best ask
        quantity_delta=Decimal("5"),
        sequence=2,
        source_time=T0,
    )
    result = lb.apply_delta(crossing, received_at=T0 + timedelta(seconds=1))
    assert result.health.status is HealthStatus.DESYNCED
    assert result.health.trading_enabled is False


def test_non_json_transport_frame_is_a_livebook_error() -> None:
    feed_a = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    conn = LiveBookConnection(
        venue="kalshi",
        feeds=[feed_a],
        transport=FakeWebSocketTransport(inbound=["this is not json"]),
        handshake_factory=lambda: object(),  # type: ignore[arg-type,return-value]
        subscribe_command={"cmd": "subscribe"},
        decode=lambda frame: [],
        snapshot_source=FakeSnapshotSource({CID: _kalshi_snapshot(seq=1)}),
        clock=lambda: T0,
    )
    with pytest.raises(LiveBookError):
        conn.pump_one()


def test_structurally_malformed_kalshi_frame_is_rejected_by_the_decoder() -> None:
    from prediction_market_arbitrage.livebook import kalshi_ws

    bad: dict[str, object] = {
        "type": "orderbook_snapshot",
        "sid": 1,
        "seq": 1,
        "msg": {"market_ticker": "X", "yes_dollars_fp": "not-a-list"},
    }
    with pytest.raises(LiveBookError):
        kalshi_ws.decode_orderbook_snapshot(bad)


# ======================================================================= #
# 4. Fee mismatch
# ======================================================================= #


def test_fees_can_flip_a_gross_edge_to_no_opportunity() -> None:
    books = dict(
        kalshi_book=arb.kalshi_book([("0.40", "100")]),
        polymarket_us_book=arb.polymarket_book([("0.55", "100")]),
    )
    no_fee = ArbitrageEngine(config=EngineConfig(fee_model=FixedPerUnitFeeModel(Decimal("0"))))
    gross = no_fee.evaluate(
        arb.make_record(), **books, evaluation_time=arb.EVAL_TIME, requested_quantity=Decimal("10")
    )
    assert gross.has_opportunity is True

    # A higher fee model than the one the edge was found under -> fail closed.
    high_fee = ArbitrageEngine(
        config=EngineConfig(fee_model=FixedPerUnitFeeModel(Decimal("0.10")))
    )
    net = high_fee.evaluate(
        arb.make_record(), **books, evaluation_time=arb.EVAL_TIME, requested_quantity=Decimal("10")
    )
    assert net.has_opportunity is False
    assert net.fees > gross.fees


def test_execution_buffer_absorbs_a_thin_edge() -> None:
    engine = ArbitrageEngine(
        config=EngineConfig(
            fee_model=FixedPerUnitFeeModel(Decimal("0")),
            execution_buffer_per_unit=Decimal("0.10"),
        )
    )
    result = engine.evaluate(
        arb.make_record(),
        arb.kalshi_book([("0.40", "100")]),
        arb.polymarket_book([("0.55", "100")]),
        evaluation_time=arb.EVAL_TIME,
        requested_quantity=Decimal("10"),
    )
    assert result.has_opportunity is False


def test_risk_min_edge_rejects_an_edge_thinner_than_the_floor() -> None:
    rm = RiskManager(RiskLimits(min_net_edge_per_unit=Decimal("0.05")))
    thin = risk_support.opportunity(net_edge_total="0.20")  # 0.02 / unit over qty 10
    decision = rm.evaluate_opportunity(thin, now=T0)
    assert decision.allowed is False


# ======================================================================= #
# 5. Partial / one-leg fills
# ======================================================================= #


def test_ioc_partial_fill_cancels_the_remainder() -> None:
    broker = PaperBroker(PaperBrokerConfig())
    req = OrderRequest(
        order_id="p1",
        venue="kalshi",
        contract_id="PB-T1:YES",
        side="buy",
        order_type="limit",
        quantity=Decimal("100"),
        limit_price=Decimal("0.60"),
        immediate_or_cancel=True,
    )
    broker.submit(req, at=T0)
    from paper_broker_support import book

    events = broker.advance(
        at=T0, books={"PB-T1:YES": book(asks=[("0.55", "30")], timestamp=T0)}
    )
    order = broker.order("p1")
    assert order.status is OrderStatus.CANCELED
    assert order.filled_quantity == Decimal("30")
    assert order.remaining_quantity == Decimal("70")
    assert events  # a fill + a status event were emitted


def test_one_leg_filled_is_unhedged_and_risk_vetoes_after_the_window() -> None:
    leg = risk_support.leg_risk(unhedged_quantity="40", both_terminal=False, as_of=T0)
    rm = RiskManager(RiskLimits(max_unhedged_time=timedelta(minutes=1)))

    # First observation starts the timer; still inside the window -> allowed.
    ok = rm.evaluate_order(
        risk_support.order(), now=T0, leg=leg, leg_pair_key="pairX"
    )
    assert ok.allowed is True

    # Past the window -> fail closed.
    late = rm.evaluate_order(
        risk_support.order(), now=T0 + timedelta(minutes=2), leg=leg, leg_pair_key="pairX"
    )
    assert late.allowed is False
    assert any("unhedged" in r for r in late.reasons)


def test_unhedged_leg_shows_on_the_dashboard() -> None:
    leg = risk_support.leg_risk(unhedged_quantity="40", both_terminal=False, as_of=T0)
    view = build_dashboard(now=T0, leg_risk=[leg])
    assert any(a.section == "leg_risk" for a in view.alerts)


def test_hedged_pair_clears_the_unhedged_timer() -> None:
    rm = RiskManager(RiskLimits(max_unhedged_time=timedelta(minutes=1)))
    unhedged = risk_support.leg_risk(unhedged_quantity="40", both_terminal=False, as_of=T0)
    rm.evaluate_order(risk_support.order(), now=T0, leg=unhedged, leg_pair_key="pairX")

    hedged = risk_support.leg_risk(unhedged_quantity="0", both_terminal=True, as_of=T0)
    rm.observe_leg_risk(hedged, now=T0 + timedelta(minutes=5), pair_key="pairX")
    assert rm.snapshot(now=T0 + timedelta(minutes=5)).unhedged_pairs == ()


# ======================================================================= #
# 6. Duplicate messages / orders
# ======================================================================= #


def test_duplicate_sequence_delta_is_ignored_not_reapplied() -> None:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=CID,
            bids=arb._levels([("0.40", "100")]),
            asks=arb._levels([("0.60", "100")]),
            sequence=5,
            source_time=T0,
        ),
        received_at=T0,
    )
    from prediction_market_arbitrage.livebook import BookDelta, DeltaOutcome

    delta = BookDelta(
        venue="kalshi",
        contract_id=CID,
        side="bid",
        price=Decimal("0.41"),
        quantity_delta=Decimal("10"),
        sequence=6,
        source_time=T0,
    )
    first = lb.apply_delta(delta, received_at=T0 + timedelta(seconds=1))
    assert first.outcome is DeltaOutcome.APPLIED
    replayed = lb.apply_delta(delta, received_at=T0 + timedelta(seconds=2))
    assert replayed.outcome is DeltaOutcome.DUPLICATE
    # Book unchanged by the duplicate.
    assert lb.book.to_order_book(T0).bids[0].quantity == Decimal("10") + Decimal("0")


def test_stale_sequence_snapshot_is_dropped() -> None:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=CID,
            bids=(),
            asks=(),
            sequence=10,
            source_time=T0 + timedelta(seconds=5),
        ),
        received_at=T0 + timedelta(seconds=5),
    )
    from prediction_market_arbitrage.livebook import DeltaOutcome

    older = BookSnapshot(
        venue="kalshi",
        contract_id=CID,
        bids=(),
        asks=(),
        sequence=8,
        source_time=T0,  # earlier source_time than what we already have
    )
    result = lb.apply_snapshot(older, received_at=T0 + timedelta(seconds=6))
    assert result.outcome is DeltaOutcome.STALE_SEQUENCE


def test_duplicate_order_id_is_rejected_by_the_paper_broker() -> None:
    broker = PaperBroker(PaperBrokerConfig())
    req = OrderRequest(
        order_id="dup",
        venue="kalshi",
        contract_id="PB-T1:YES",
        side="buy",
        order_type="limit",
        quantity=Decimal("10"),
        limit_price=Decimal("0.50"),
    )
    broker.submit(req, at=T0)
    with pytest.raises(PaperBrokerError, match="duplicate order_id"):
        broker.submit(req, at=T0 + timedelta(seconds=1))


def test_recorder_is_append_only_no_update_or_delete_surface() -> None:
    rec = Recorder.open(session_id="s-dup", opened_at=T0)
    for attr in ("update", "delete", "upsert", "overwrite"):
        assert not hasattr(rec, attr)


# ======================================================================= #
# 7. API timeout / rate limit
# ======================================================================= #


def test_adapter_propagates_a_timeout_it_does_not_swallow() -> None:
    from kalshi_support import FakeTransport

    from prediction_market_arbitrage.adapters.kalshi import KalshiClient, KalshiTimeoutError
    from prediction_market_arbitrage.adapters.kalshi.adapter import KalshiMarketDataAdapter

    transport = FakeTransport(raises=KalshiTimeoutError("request timed out"))
    adapter = KalshiMarketDataAdapter(KalshiClient(transport=transport), clock=lambda: T0)
    with pytest.raises(KalshiTimeoutError):
        adapter.get_order_books("SOME-TICKER")


def test_http_429_rate_limit_surfaces_as_an_http_error_with_status() -> None:
    from kalshi_support import FakeTransport, json_response

    from prediction_market_arbitrage.adapters.kalshi import KalshiClient, KalshiHTTPError

    transport = FakeTransport(
        routes=[("/markets/", json_response(429, {"error": {"code": "rate_limited"}}))]
    )
    client = KalshiClient(transport=transport)
    with pytest.raises(KalshiHTTPError) as excinfo:
        client.get_market_orderbook("SOME-TICKER")
    assert excinfo.value.status == 429


def test_polymarket_http_503_is_an_http_error_not_a_book() -> None:
    from polymarket_us_support import FakeTransport, json_response

    from prediction_market_arbitrage.adapters.polymarket_us import (
        PolymarketClient,
        PolymarketHTTPError,
    )

    transport = FakeTransport(routes=[("/book", json_response(503, {"code": 14}))])
    client = PolymarketClient(transport=transport)
    with pytest.raises(PolymarketHTTPError) as excinfo:
        client.get_book("some-slug")
    assert excinfo.value.status == 503


# ======================================================================= #
# 8. Invalid contract mapping
# ======================================================================= #


def test_engine_rejects_a_non_verified_pair() -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError):
        engine.evaluate(
            arb.make_record(status=PairStatus.DRAFT),
            arb.kalshi_book([("0.40", "100")]),
            arb.polymarket_book([("0.55", "100")]),
            evaluation_time=arb.EVAL_TIME,
        )


def test_engine_rejects_books_that_do_not_match_the_pair_record() -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError, match="does not match pair leg"):
        engine.evaluate(
            arb.make_record(),
            arb.kalshi_book([("0.40", "100")], market="WRONG-MARKET"),
            arb.polymarket_book([("0.55", "100")]),
            evaluation_time=arb.EVAL_TIME,
            requested_quantity=Decimal("10"),
        )


def test_feed_rejects_a_message_for_another_contract() -> None:
    lb = LiveBookFeed(contract=kalshi_contract(), venue="kalshi", max_staleness=MAX_STALENESS)
    wrong = BookSnapshot(
        venue="kalshi",
        contract_id="SOME-OTHER-CONTRACT:YES",
        bids=(),
        asks=(),
        sequence=1,
        source_time=T0,
    )
    with pytest.raises(LiveBookError):
        lb.apply_snapshot(wrong, received_at=T0)


def test_connection_rejects_a_feed_from_another_venue() -> None:
    poly_feed = LiveBookFeed(
        contract=kalshi_contract(), venue="polymarket_us", max_staleness=MAX_STALENESS
    )
    with pytest.raises(LiveBookError):
        LiveBookConnection(
            venue="kalshi",
            feeds=[poly_feed],
            transport=FakeWebSocketTransport(),
            handshake_factory=lambda: object(),  # type: ignore[arg-type,return-value]
            subscribe_command={"cmd": "subscribe"},
            decode=lambda frame: [],
            snapshot_source=FakeSnapshotSource({}),
            clock=lambda: T0,
        )


# ======================================================================= #
# 9. Database / process restart
# ======================================================================= #


def test_recording_survives_a_process_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "restart.duckdb")
    from replay_support import SESSION_ID, build_recording

    build_recording(db)  # "process 1" writes, then its Recorder is closed

    # "process 2" opens the same file fresh and reads the audit trail back.
    with ReplaySession.open(db, session_id=SESSION_ID) as session:
        counts_a = session.counts()
        timeline_a = session.timeline()
    with ReplaySession.open(db, session_id=SESSION_ID) as session:
        assert session.counts() == counts_a
        assert session.timeline() == timeline_a
    assert sum(counts_a.values()) > 0


def test_reopening_a_recorder_file_continues_ids_and_stays_append_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "reopen.duckdb")
    health = risk_support.health()
    with Recorder.open(db, session_id="s1", opened_at=T0) as rec:
        rec.record_health_event(
            venue="kalshi", contract_id=CID, health=health, recorded_at=T0
        )
    with Recorder.open(db, session_id="s1", opened_at=T0) as rec:
        rec.record_health_event(
            venue="kalshi", contract_id=CID, health=health, recorded_at=T0 + timedelta(seconds=1)
        )
    with ReplaySession.open(db, session_id="s1") as session:
        assert session.counts()["health"] == 2
        assert len(list(session.health_events())) == 2


def test_a_foreign_schema_version_file_is_refused_not_migrated() -> None:
    import duckdb

    conn = duckdb.connect(":memory:")
    initialize(conn)
    conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    with pytest.raises(RecorderError, match="does not migrate"):
        initialize(conn)


def test_replay_refuses_an_unknown_session_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "unknown.duckdb")
    from replay_support import build_recording

    build_recording(db)
    with pytest.raises(ReplayError, match="not in recording_sessions"):
        ReplaySession.open(db, session_id="no-such-session")
