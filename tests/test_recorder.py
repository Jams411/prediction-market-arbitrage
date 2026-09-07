"""Deterministic offline tests for the M2.2 recorder writes."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from arbitrage_support import EVAL_TIME, kalshi_book, make_record, polymarket_book
from recorder_support import (
    REC_AT,
    REC_TS,
    WIDE_DECIMAL,
    feed_health,
    order_book,
)

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    EngineConfig,
    FixedPerUnitFeeModel,
    OpportunityEvaluation,
)
from prediction_market_arbitrage.livebook import HealthStatus
from prediction_market_arbitrage.recorder import (
    FillRow,
    OrderEventRow,
    PnlRow,
    PositionRow,
    Recorder,
    RecorderError,
)

D = Decimal


def _recorder(session_id: str = "sess-1") -> Recorder:
    return Recorder.open(session_id=session_id, opened_at=REC_TS, label="test")


def _opportunity_evaluation() -> OpportunityEvaluation:
    engine = ArbitrageEngine(
        config=EngineConfig(fee_model=FixedPerUnitFeeModel(D("0.01")))
    )
    return engine.evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("10"),
    )


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #


def test_open_registers_the_session_once() -> None:
    rec = _recorder("sess-x")
    Recorder(rec.connection, session_id="sess-x", opened_at=REC_TS)  # re-register
    rows = rec.connection.execute("SELECT session_id, label FROM recording_sessions").fetchall()
    assert rows == [("sess-x", "test")]  # INSERT OR IGNORE kept the first
    rec.close()


def test_empty_session_id_is_rejected() -> None:
    with pytest.raises(RecorderError, match="session_id"):
        _recorder("  ")


# --------------------------------------------------------------------------- #
# order books
# --------------------------------------------------------------------------- #


def test_record_order_book_preserves_decimal_and_timestamp_fidelity() -> None:
    rec = _recorder()
    book = order_book(
        bids=[("0.40", "100"), ("0.38", str(WIDE_DECIMAL))],
        asks=[("0.44", "70.5")],
    )
    snapshot_id = rec.record_order_book(book, recorded_at=REC_AT, source="rest_snapshot")
    assert snapshot_id == 1

    parent = rec.connection.execute(
        "SELECT venue, market_id, contract_id, outcome, book_timestamp, recorded_at, "
        "source, bid_count, ask_count FROM order_book_snapshots WHERE id = 1"
    ).fetchone()
    assert parent == (
        "kalshi",
        "RECORDER-TEST-T1",
        "RECORDER-TEST-T1:YES",
        "YES",
        REC_TS.replace(tzinfo=None),  # naive UTC, microseconds intact
        REC_AT.replace(tzinfo=None),
        "rest_snapshot",
        2,
        1,
    )
    levels = rec.connection.execute(
        "SELECT side, level_index, price, quantity FROM order_book_levels "
        "WHERE snapshot_id = 1 ORDER BY side, level_index"
    ).fetchall()
    assert levels == [
        ("ask", 0, "0.44", "70.5"),
        ("bid", 0, "0.40", "100"),
        ("bid", 1, "0.38", str(WIDE_DECIMAL)),
    ]
    # exact round-trip
    assert Decimal(levels[2][2]) == D("0.38")
    assert Decimal(levels[2][3]) == WIDE_DECIMAL
    rec.close()


def test_order_book_ids_are_monotonic() -> None:
    rec = _recorder()
    b = order_book(bids=[("0.4", "1")], asks=[("0.5", "1")])
    assert [rec.record_order_book(b, recorded_at=REC_AT, source="s") for _ in range(3)] == [1, 2, 3]
    rec.close()


def test_naive_timestamp_is_rejected() -> None:
    rec = _recorder()
    with pytest.raises(RecorderError, match="timezone-aware"):
        rec.record_order_book(
            order_book(bids=[("0.4", "1")], asks=[("0.5", "1")]),
            recorded_at=datetime(2026, 3, 1, 9, 30),  # noqa: DTZ001
            source="s",
        )
    rec.close()


# --------------------------------------------------------------------------- #
# opportunities
# --------------------------------------------------------------------------- #


def test_record_opportunity_stores_exact_engine_totals() -> None:
    rec = _recorder()
    evaluation = _opportunity_evaluation()
    rec.record_opportunity(evaluation, recorded_at=REC_AT)

    row = rec.connection.execute(
        "SELECT pair_id, relation, executable_quantity, net_edge, fees, "
        "has_opportunity, evaluation_time FROM opportunities WHERE id = 1"
    ).fetchone()
    assert row is not None
    assert row[0] == evaluation.pair_id
    assert row[1] == str(evaluation.relation)
    assert Decimal(row[2]) == evaluation.executable_quantity
    assert Decimal(row[3]) == evaluation.net_edge
    assert Decimal(row[4]) == evaluation.fees
    assert row[5] == evaluation.has_opportunity
    assert row[6] == evaluation.evaluation_time.replace(tzinfo=None)
    rec.close()


# --------------------------------------------------------------------------- #
# orders / fills / positions / pnl
# --------------------------------------------------------------------------- #


def test_record_order_event_and_fill_round_trip() -> None:
    rec = _recorder()
    order = OrderEventRow(
        order_id="ord-1",
        venue="kalshi",
        contract_id="RECORDER-TEST-T1:YES",
        side="buy",
        order_type="limit",
        quantity=D("10"),
        status="submitted",
        event_time=REC_TS,
        limit_price=D("0.41"),
    )
    assert rec.record_order_event(order, recorded_at=REC_AT) == 1
    fill = FillRow(
        fill_id="fill-1",
        order_id="ord-1",
        venue="kalshi",
        contract_id="RECORDER-TEST-T1:YES",
        price=D("0.41"),
        quantity=D("4"),
        fee=D("0.0175"),
        filled_at=REC_TS + timedelta(seconds=2),
        liquidity="taker",
    )
    assert rec.record_fill(fill, recorded_at=REC_AT) == 1

    got_order = rec.connection.execute(
        "SELECT order_id, side, order_type, limit_price, quantity, status FROM order_events"
    ).fetchone()
    assert got_order == ("ord-1", "buy", "limit", "0.41", "10", "submitted")
    got_fill = rec.connection.execute(
        "SELECT fill_id, price, quantity, fee, liquidity FROM fills"
    ).fetchone()
    assert got_fill == ("fill-1", "0.41", "4", "0.0175", "taker")
    rec.close()


def test_limit_order_without_price_is_rejected_at_construction() -> None:
    with pytest.raises(RecorderError, match="limit order needs a limit_price"):
        OrderEventRow(
            order_id="o",
            venue="kalshi",
            contract_id="c",
            side="buy",
            order_type="limit",
            quantity=D("1"),
            status="new",
            event_time=REC_TS,
        )


def test_record_position_and_pnl() -> None:
    rec = _recorder()
    assert (
        rec.record_position(
            PositionRow(
                venue="kalshi",
                contract_id="RECORDER-TEST-T1:YES",
                quantity=D("-3"),
                avg_price=D("0.415"),
                as_of=REC_TS,
            ),
            recorded_at=REC_AT,
        )
        == 1
    )
    assert (
        rec.record_pnl(
            PnlRow(
                scope="portfolio",
                scope_id="all",
                realized=D("1.25"),
                unrealized=D("-0.40"),
                fees=D("0.07"),
                as_of=REC_TS,
            ),
            recorded_at=REC_AT,
        )
        == 1
    )
    assert rec.connection.execute("SELECT quantity, avg_price FROM positions").fetchone() == (
        "-3",
        "0.415",
    )
    assert rec.connection.execute("SELECT scope, realized, unrealized FROM pnl").fetchone() == (
        "portfolio",
        "1.25",
        "-0.40",
    )
    rec.close()


def test_non_decimal_money_field_is_rejected() -> None:
    with pytest.raises(RecorderError, match="expected a Decimal"):
        PositionRow(
            venue="kalshi",
            contract_id="c",
            quantity=3.0,  # type: ignore[arg-type]
            avg_price=D("0.5"),
            as_of=REC_TS,
        )


# --------------------------------------------------------------------------- #
# health events
# --------------------------------------------------------------------------- #


def test_record_health_event_including_null_last_update() -> None:
    rec = _recorder()
    rec.record_health_event(
        feed_health(status=HealthStatus.HEALTHY, last_sequence=7),
        venue="kalshi",
        contract_id="RECORDER-TEST-T1:YES",
        recorded_at=REC_AT,
    )
    rec.record_health_event(
        feed_health(
            status=HealthStatus.DISCONNECTED,
            reason="socket disconnected",
            last_update=None,
            last_sequence=None,
        ),
        venue="kalshi",
        contract_id="RECORDER-TEST-T1:YES",
        recorded_at=REC_AT,
    )
    rows = rec.connection.execute(
        "SELECT status, trading_enabled, last_update, last_sequence FROM health_events ORDER BY id"
    ).fetchall()
    assert rows == [
        ("healthy", True, REC_TS.replace(tzinfo=None), 7),
        ("disconnected", False, None, None),
    ]
    rec.close()


# --------------------------------------------------------------------------- #
# determinism / append-only / persistence
# --------------------------------------------------------------------------- #


def test_same_calls_produce_identical_rows() -> None:
    def run() -> list[tuple[object, ...]]:
        rec = _recorder("det")
        rec.record_order_book(
            order_book(bids=[("0.4", "1")], asks=[("0.5", "2")]), recorded_at=REC_AT, source="s"
        )
        rec.record_health_event(
            feed_health(), venue="kalshi", contract_id="RECORDER-TEST-T1:YES", recorded_at=REC_AT
        )
        rows = rec.connection.execute(
            "SELECT * FROM order_book_snapshots"
        ).fetchall() + rec.connection.execute("SELECT * FROM health_events").fetchall()
        rec.close()
        return rows

    assert run() == run()


def test_recorder_exposes_no_update_or_delete_api() -> None:
    assert not any(
        hasattr(Recorder, name)
        for name in ("update", "delete", "update_order", "delete_row", "upsert")
    )


def test_file_backed_recorder_continues_ids_across_reopen() -> None:
    path = os.path.join(tempfile.mkdtemp(), "rec.duckdb")
    try:
        first = Recorder.open(path, session_id="s", opened_at=REC_TS)
        first.record_order_book(
            order_book(bids=[("0.4", "1")], asks=[("0.5", "1")]), recorded_at=REC_AT, source="a"
        )
        first.close()

        second = Recorder.open(path, session_id="s", opened_at=REC_TS + timedelta(hours=1))
        new_id = second.record_order_book(
            order_book(bids=[("0.4", "1")], asks=[("0.5", "1")]), recorded_at=REC_AT, source="b"
        )
        assert new_id == 2  # sequence persisted
        session_count = second.connection.execute(
            "SELECT count(*) FROM recording_sessions"
        ).fetchone()
        assert session_count == (1,)
        second.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
