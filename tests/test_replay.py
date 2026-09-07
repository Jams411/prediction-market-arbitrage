"""Deterministic offline tests for the M2.3 replay adapter."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, timedelta
from decimal import Decimal

import duckdb
import pytest
from replay_support import SESSION_ID, T0, WIDE, build_recording

from prediction_market_arbitrage.domain import Contract, Market, Venue
from prediction_market_arbitrage.livebook import HealthStatus, LiveBookFeed
from prediction_market_arbitrage.recorder.schema import SCHEMA_VERSION
from prediction_market_arbitrage.registry import OutcomeRelation
from prediction_market_arbitrage.replay import ReplayError, ReplaySession

D = Decimal


@pytest.fixture
def recording(tmp_path) -> str:  # type: ignore[no-untyped-def]
    path = str(tmp_path / "rec.duckdb")
    build_recording(path)
    return path


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# --------------------------------------------------------------------------- #
# order books — Decimal + timestamp fidelity, live-book compatibility
# --------------------------------------------------------------------------- #


def test_order_books_reconstruct_with_decimal_and_utc_fidelity(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        books = list(session.order_books())

    assert [b.row_id for b in books] == [1, 2]
    first = books[0].book
    assert first.contract.id == "REPLAY-T1:YES"
    assert first.contract.market.venue.id == "kalshi"
    assert [(lvl.price, lvl.quantity) for lvl in first.bids] == [
        (D("0.40"), D("100")),
        (D("0.38"), WIDE),  # 30-digit value survives exactly
    ]
    assert [(lvl.price, lvl.quantity) for lvl in first.asks] == [(D("0.44"), D("70.5"))]
    assert first.timestamp == T0 + timedelta(seconds=1)
    assert first.timestamp.tzinfo == UTC  # UTC reattached (A-031)
    assert books[0].recorded_at.tzinfo == UTC
    assert books[0].source == "rest_snapshot"


def test_as_book_snapshot_is_livebook_shaped(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        snapshot, recorded_at = next(iter(session.as_book_snapshots()))
    assert snapshot.venue == "kalshi"
    assert snapshot.contract_id == "REPLAY-T1:YES"
    assert snapshot.sequence is None
    assert snapshot.market_state is None
    assert snapshot.source_time == T0 + timedelta(seconds=1)
    assert recorded_at == T0 + timedelta(seconds=1)


def test_feed_book_snapshots_drives_a_real_live_book_feed(recording: str) -> None:
    feed = LiveBookFeed(
        contract=_yes_contract(),
        venue="kalshi",
        max_staleness=timedelta(hours=1),
        require_sequence=False,
    )
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        applied = session.feed_book_snapshots({"REPLAY-T1:YES": feed})

    assert applied == 2
    now = T0 + timedelta(seconds=3)
    book = feed.current_order_book(now)
    assert book is not None
    # last replayed book wins
    assert book.bids[0].price == D("0.41")
    assert book.asks[0].price == D("0.45")
    assert feed.health(now).status is HealthStatus.HEALTHY


def _yes_contract() -> Contract:
    v = Venue(id="kalshi", name="kalshi")
    m = Market(venue=v, id="REPLAY-T1", title="REPLAY-T1", close_time=None)
    return Contract(market=m, id="REPLAY-T1:YES", outcome="YES")


# --------------------------------------------------------------------------- #
# other streams
# --------------------------------------------------------------------------- #


def test_opportunity_stream_roundtrips_engine_totals(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        (opp,) = list(session.opportunities())
    assert opp.relation is OutcomeRelation.COMPLEMENTARY
    assert opp.executable_quantity == D("10")
    assert opp.net_edge == D("10") - opp.net_total_cost
    assert opp.evaluation_time.tzinfo == UTC
    assert isinstance(opp.has_opportunity, bool)


def test_order_fill_position_pnl_streams(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        (order,) = list(session.order_events())
        (fill,) = list(session.fills())
        (pos,) = list(session.positions())
        (pnl,) = list(session.pnl())
    assert (order.side, order.order_type, order.limit_price, order.quantity) == (
        "buy",
        "limit",
        D("0.41"),
        D("10"),
    )
    assert (fill.price, fill.quantity, fill.fee, fill.liquidity) == (
        D("0.41"),
        D("4"),
        D("0.0175"),
        "taker",
    )
    assert (pos.quantity, pos.avg_price) == (D("4"), D("0.41"))
    assert (pnl.scope, pnl.realized, pnl.unrealized) == ("portfolio", D("0"), D("-0.04"))
    for value in (order.event_time, fill.filled_at, pos.as_of, pnl.as_of):
        assert value.tzinfo == UTC


def test_health_stream_reconstructs_feedhealth_including_nulls(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        events = list(session.health_events())
    assert [e.health.status for e in events] == [
        HealthStatus.HEALTHY,
        HealthStatus.DISCONNECTED,
    ]
    assert events[0].health.trading_enabled is True
    assert events[0].health.last_update == T0 + timedelta(seconds=1)
    assert events[1].health.last_update is None
    assert events[1].health.last_sequence is None
    assert events[1].health.trading_enabled is False


# --------------------------------------------------------------------------- #
# timeline + pacing determinism
# --------------------------------------------------------------------------- #


def test_timeline_is_ordered_by_recorded_time_then_kind_then_id(recording: str) -> None:
    from prediction_market_arbitrage.replay.session import _KIND_RANK

    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        timeline = session.timeline()
    keys = [(e.recorded_at, _KIND_RANK[e.kind], e.row_id) for e in timeline]
    assert keys == sorted(keys)
    # +1s bucket: order_book(row 1) sorts before health(row 1) by kind rank
    assert (timeline[0].kind, timeline[0].row_id) == ("order_book", 1)
    assert (timeline[1].kind, timeline[1].row_id) == ("health", 1)


def test_two_identical_recordings_replay_identically(tmp_path) -> None:  # type: ignore[no-untyped-def]
    a, b = str(tmp_path / "a.duckdb"), str(tmp_path / "b.duckdb")
    build_recording(a)
    build_recording(b)
    with ReplaySession.open(a, session_id=SESSION_ID) as sa, ReplaySession.open(
        b, session_id=SESSION_ID
    ) as sb:
        assert sa.timeline() == sb.timeline()


def test_play_default_is_a_plain_deterministic_iterator(recording: str) -> None:
    sleep = RecordingSleep()
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        events = list(session.play())  # default no_sleep
        assert events == session.timeline()
    assert sleep.calls == []  # nothing injected -> nothing slept


def test_play_paces_by_recorded_gaps_and_speed(recording: str) -> None:
    sleep = RecordingSleep()
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        events = list(session.play(sleep=sleep, speed=2.0))
    gaps = [
        (events[i].recorded_at - events[i - 1].recorded_at).total_seconds() / 2.0
        for i in range(1, len(events))
    ]
    assert sleep.calls == gaps
    assert all(g >= 0 for g in sleep.calls)


# --------------------------------------------------------------------------- #
# errors / read-only surface
# --------------------------------------------------------------------------- #


def test_open_rejects_a_non_recorder_database() -> None:
    path = os.path.join(tempfile.mkdtemp(), "blank.duckdb")
    try:
        duckdb.connect(path).close()  # empty db, no schema
        with pytest.raises(ReplayError, match="schema_version|not a recorder"):
            ReplaySession.open(path, session_id="x")
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_missing_session_is_rejected(recording: str) -> None:
    with pytest.raises(ReplayError, match="not in recording_sessions"):
        ReplaySession.open(recording, session_id="no-such-session")


def test_foreign_schema_version_is_rejected(recording: str) -> None:
    rw = duckdb.connect(recording)
    rw.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    rw.close()
    with pytest.raises(ReplayError, match=f"!= replay's expected {SCHEMA_VERSION}"):
        ReplaySession.open(recording, session_id=SESSION_ID)


def test_replay_session_exposes_no_write_api() -> None:
    assert not any(
        name.startswith(("record_", "insert", "write", "update", "delete"))
        for name in dir(ReplaySession)
    )


def test_bad_speed_is_rejected(recording: str) -> None:
    with ReplaySession.open(recording, session_id=SESSION_ID) as session:
        with pytest.raises(ReplayError, match="speed must be > 0"):
            list(session.play(speed=0))


def test_realtime_pacer_scales_the_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    from prediction_market_arbitrage.replay import realtime

    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    realtime(speed=4.0)(2.0)
    realtime(speed=1.0)(-5.0)  # negative gap clamps to 0
    assert slept == [0.5, 0.0]
    with pytest.raises(ReplayError, match="speed must be > 0"):
        realtime(speed=0)
