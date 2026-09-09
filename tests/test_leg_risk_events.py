"""M3.3 recorder-backed leg-risk events: persist → replay → aggregate.

End-to-end and deterministic. A leg-risk event is only ever written when the
paper broker's ``LegRiskSnapshot`` shows real one-legged exposure
(``unhedged_quantity != 0``); nothing here fabricates events to populate a
metric.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.perf_report import build_report, render_text
from prediction_market_arbitrage.recorder import LegRiskEventRow, Recorder
from prediction_market_arbitrage.replay import RecordedLegRiskEvent, ReplaySession

D = Decimal
T0 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
SESSION = "leg-risk-test"


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _event(
    *, a: str, b: str, unhedged: str, both_terminal: bool, notional: str | None, at_s: int
) -> LegRiskEventRow:
    return LegRiskEventRow(
        order_a_id=a,
        order_b_id=b,
        a_filled_quantity=D("10"),
        b_filled_quantity=D("10") - D(unhedged),
        unhedged_quantity=D(unhedged),
        a_average_price=D("0.4400"),
        b_average_price=D("0.4800"),
        both_terminal=both_terminal,
        as_of=_at(at_s),
        hedge_completion_price=None if notional is None else D("0.4700"),
        unhedged_notional=None if notional is None else D(notional),
    )


def _build(database: str) -> None:
    """Two temporary events (one priced, one not) and one unresolved event."""
    with Recorder.open(database, session_id=SESSION, opened_at=T0, label="lr") as rec:
        rec.record_leg_risk_event(
            _event(a="o1", b="o2", unhedged="7", both_terminal=False, notional="3.2900", at_s=1),
            recorded_at=_at(1),
        )
        rec.record_leg_risk_event(
            _event(a="o1", b="o2", unhedged="4", both_terminal=False, notional=None, at_s=2),
            recorded_at=_at(2),
        )
        rec.record_leg_risk_event(
            _event(a="o3", b="o4", unhedged="6", both_terminal=True, notional="2.8200", at_s=3),
            recorded_at=_at(3),
        )


def test_recorded_leg_risk_events_replay_with_exact_decimal_and_utc(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "lr.duckdb")
    _build(db)

    with ReplaySession.open(db, session_id=SESSION) as session:
        assert session.has_leg_risk_stream() is True
        events = list(session.leg_risk_events())

    assert [e.row_id for e in events] == [1, 2, 3]
    assert all(isinstance(e, RecordedLegRiskEvent) for e in events)
    first = events[0]
    assert first.unhedged_quantity == D("7")  # exact, not 7.0
    assert first.b_filled_quantity == D("3")
    assert first.hedge_completion_price == D("0.4700")
    assert first.unhedged_notional == D("3.2900")
    assert first.temporary is True and first.unresolved is False
    assert first.as_of == _at(1)  # tz-aware UTC round-trip
    assert first.as_of.tzinfo is not None

    assert events[1].hedge_completion_price is None
    assert events[1].unhedged_notional is None

    assert events[2].both_terminal is True
    assert events[2].unresolved is True and events[2].temporary is False


def test_leg_risk_events_appear_on_the_replay_timeline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "lr.duckdb")
    _build(db)
    with ReplaySession.open(db, session_id=SESSION) as session:
        timeline = session.timeline()
        assert session.counts()["leg_risk"] == 3
    kinds = [e.kind for e in timeline]
    assert kinds == ["leg_risk", "leg_risk", "leg_risk"]
    assert [e.row_id for e in timeline] == [1, 2, 3]


def test_perf_report_aggregates_recorded_leg_risk_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "lr.duckdb")
    _build(db)
    with ReplaySession.open(db, session_id=SESSION) as session:
        report = build_report(session)

    lr = report.leg_risk
    assert lr.recorded is True
    assert lr.events == 3
    assert lr.temporary_events == 2
    assert lr.unresolved_events == 1
    assert lr.order_pairs_affected == 2  # (o1,o2) and (o3,o4)
    assert lr.max_abs_unhedged_quantity == D("7")
    # only the two priced events contribute to the notional stats
    assert lr.unhedged_notional.count == 2
    assert lr.unhedged_notional.minimum == D("2.8200")
    assert lr.unhedged_notional.maximum == D("3.2900")
    assert lr.unhedged_notional.mean == (D("3.2900") + D("2.8200")) / D("2")
    assert not any("leg-risk" in u for u in report.unavailable)

    text = render_text(report)
    assert "LEG RISK  (one-legged exposure events)" in text
    assert "events:              3" in text
    assert "unresolved:          1" in text


def test_leg_risk_events_recording_is_byte_identical_across_two_builds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    def rows(database: str) -> list[tuple[object, ...]]:
        _build(database)
        with ReplaySession.open(database, session_id=SESSION) as s:
            return [
                (
                    e.row_id,
                    e.order_a_id,
                    e.order_b_id,
                    str(e.unhedged_quantity),
                    e.both_terminal,
                    None if e.unhedged_notional is None else str(e.unhedged_notional),
                    e.as_of.isoformat(),
                )
                for e in s.leg_risk_events()
            ]

    assert rows(str(tmp_path / "a.duckdb")) == rows(str(tmp_path / "b.duckdb"))


def test_resampling_the_same_transition_does_not_double_count(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "dup.duckdb")
    ev = _event(a="o1", b="o2", unhedged="7", both_terminal=False, notional="3.2900", at_s=1)
    with Recorder.open(db, session_id=SESSION, opened_at=T0) as rec:
        id1 = rec.record_leg_risk_event(ev, recorded_at=_at(1))
        # a loop that observes the same leg_risk(o1, o2, as_of=t1) snapshot again
        id2 = rec.record_leg_risk_event(ev, recorded_at=_at(2))
        assert id1 == id2

    with ReplaySession.open(db, session_id=SESSION) as session:
        assert session.counts()["leg_risk"] == 1
        report = build_report(session)
    assert report.leg_risk.events == 1
    assert report.leg_risk.recorded is True


def test_recording_without_the_table_reports_leg_risk_as_unavailable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "legacy.duckdb")
    _build(db)
    # Simulate a recording written before the leg_risk_events table existed.
    with Recorder.open(db, session_id=SESSION, opened_at=T0) as rec:
        rec.connection.execute("DROP TABLE leg_risk_events")
        rec.connection.execute("DROP SEQUENCE seq_leg_risk_events")

    with ReplaySession.open(db, session_id=SESSION) as session:
        assert session.has_leg_risk_stream() is False
        assert list(session.leg_risk_events()) == []
        assert session.counts()["leg_risk"] == 0
        report = build_report(session)

    assert report.leg_risk.recorded is False
    assert report.leg_risk.events == 0
    assert report.leg_risk.note != ""
    assert any("leg-risk" in u for u in report.unavailable)
    assert "n/a" in render_text(report)
