"""Deterministic known-answer tests for the M3.3 paper-performance report."""

from __future__ import annotations

from decimal import Decimal

import pytest
from perf_report_support import SESSION_ID, build_perf_recording

from prediction_market_arbitrage.perf_report import (
    PerfReport,
    PerfReportError,
    Stats,
    build_report,
    render_text,
)
from prediction_market_arbitrage.recorder import Recorder
from prediction_market_arbitrage.replay import ReplaySession

D = Decimal


@pytest.fixture
def report(tmp_path) -> PerfReport:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "perf.duckdb")
    build_perf_recording(db)
    with ReplaySession.open(db, session_id=SESSION_ID) as session:
        return build_report(session)


@pytest.fixture
def empty_report(tmp_path) -> PerfReport:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "empty.duckdb")
    from perf_report_support import T0

    Recorder.open(db, session_id="empty", opened_at=T0).close()
    with ReplaySession.open(db, session_id="empty") as session:
        return build_report(session)


# -- Stats helper -------------------------------------------------------- #


def test_stats_of_empty_is_all_none_not_zero() -> None:
    s = Stats.of([])
    assert s.count == 0
    assert s.mean is None and s.median is None
    assert s.minimum is None and s.maximum is None


def test_stats_median_of_even_count_averages_the_middle_two() -> None:
    s = Stats.of([D("1"), D("2"), D("3"), D("10")])
    assert s.median == D("2.5")
    assert s.mean == D("4")
    assert s.minimum == D("1") and s.maximum == D("10")


# -- opportunities observed / rejected --------------------------------- #


def test_opportunities_observed_positive_and_rejected(report: PerfReport) -> None:
    o = report.opportunities
    assert o.observed == 5
    assert o.positive_edge == 3
    assert o.rejected == 2
    assert dict(o.rejection_reasons) == {"net edge <= 0": 1, "stale book": 1}


def test_mean_and_median_net_edge(report: PerfReport) -> None:
    o = report.opportunities
    assert o.net_edge_total.count == 3
    assert o.net_edge_total.median == D("2")
    assert o.net_edge_total.mean == D("7") / D("3")
    assert o.net_edge_total.minimum == D("1")
    assert o.net_edge_total.maximum == D("4")
    assert o.net_edge_per_unit.median == D("0.2")
    assert o.net_edge_per_unit.minimum == D("0.1")


def test_executable_quantity_and_depth_capped(report: PerfReport) -> None:
    o = report.opportunities
    assert o.executable_quantity.median == D("10")
    assert o.depth_capped_count == 1
    assert o.depth_capped_fraction == D("1") / D("3")


# -- opportunity duration (derived) --------------------------------- #


def test_opportunity_duration_episodes(report: PerfReport) -> None:
    d = report.opportunity_duration
    assert d.episodes == 2
    assert d.episodes_with_duration == 1  # P1's 2-eval positive run
    assert d.single_observation_episodes == 1  # P2's single positive obs
    assert d.duration_seconds.count == 1
    assert d.duration_seconds.mean == D("20")  # at(30) - at(10)


# -- paper trades / fill rates ------------------------------------- #


def test_trade_fill_and_partial_fill_rates(report: PerfReport) -> None:
    t = report.trades
    assert t.orders == 3
    assert (t.fully_filled, t.partially_filled, t.unfilled) == (1, 1, 1)
    assert t.fill_rate == D("1") / D("3")
    assert t.partial_fill_rate == D("1") / D("3")
    assert t.filled_quantity_ratio == D("14") / D("25")


def test_trade_final_status_and_fills(report: PerfReport) -> None:
    t = report.trades
    assert dict(t.final_status_counts) == {
        "filled": 1,
        "partially_filled": 1,
        "rejected": 1,
    }
    assert t.fills == 2
    assert dict(t.fill_liquidity_counts) == {"taker": 2}
    assert t.fill_fees_total == D("0.03")


# -- available depth --------------------------------------------- #


def test_depth_statistics_from_recorded_books(report: PerfReport) -> None:
    d = report.depth
    assert d.order_books == 2
    assert d.best_ask_size.minimum == D("10")
    assert d.best_ask_size.maximum == D("30")
    assert d.best_ask_size.mean == D("20")
    assert d.total_ask_size.mean == D("22.5")
    assert d.best_bid_size.minimum == D("8")
    assert d.total_bid_size.mean == D("15")


# -- pnl + drawdown -------------------------------------------- #


def test_pnl_series_final_values_and_drawdown(report: PerfReport) -> None:
    p = report.pnl
    assert p.scope == "portfolio"
    assert p.scope_id == "acct"
    assert p.samples == 4
    assert p.final_realized == D("8")
    assert p.final_unrealized == D("-1")
    assert p.final_fees == D("0.5")
    assert p.final_net == D("6.5")
    assert p.peak_net == D("6.5")
    assert p.max_drawdown == D("3")


def test_pnl_scope_filter_ignores_other_scopes(report: PerfReport) -> None:
    # A 'contract'-scope row (realized 99) exists but must not leak into the
    # portfolio report.
    assert report.pnl.final_realized == D("8")


def test_pnl_scope_can_be_selected() -> None:
    # explicit contract scope picks up the single contract row
    import tempfile

    from perf_report_support import build_perf_recording as build

    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/x.duckdb"
        build(db)
        with ReplaySession.open(db, session_id=SESSION_ID) as session:
            r = build_report(session, pnl_scope="contract")
    assert r.pnl.samples == 1
    assert r.pnl.final_realized == D("99")


def test_invalid_pnl_scope_is_rejected() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/x.duckdb"
        build_perf_recording(db)
        with ReplaySession.open(db, session_id=SESSION_ID) as session:
            with pytest.raises(PerfReportError):
                build_report(session, pnl_scope="not-a-scope")


# -- missing vs zero ------------------------------------------ #


def test_leg_risk_zero_events_is_a_real_zero_not_unavailable(report: PerfReport) -> None:
    # The perf recording is written by the current Recorder, so the
    # leg_risk_events table exists — no exposure was recorded, which is a real 0.
    assert report.leg_risk.recorded is True
    assert report.leg_risk.events == 0
    assert report.leg_risk.temporary_events == 0
    assert report.leg_risk.unresolved_events == 0
    assert not any("leg-risk" in u for u in report.unavailable)


def test_empty_session_reports_missing_metrics_as_none_not_zero(
    empty_report: PerfReport,
) -> None:
    r = empty_report
    # counts are real zeros
    assert r.opportunities.observed == 0
    assert r.trades.orders == 0
    assert r.depth.order_books == 0
    assert r.pnl.samples == 0
    # aggregates are None (missing), never 0
    assert r.opportunities.net_edge_total.mean is None
    assert r.opportunities.depth_capped_fraction is None
    assert r.trades.fill_rate is None
    assert r.trades.filled_quantity_ratio is None
    assert r.trades.fill_fees_total is None
    assert r.depth.best_ask_size.mean is None
    assert r.pnl.final_net is None
    assert r.pnl.max_drawdown is None
    # and each is called out explicitly
    joined = " ".join(r.unavailable)
    assert "mean/median net edge" in joined
    assert "depth statistics" in joined
    assert "paper PnL" in joined


def test_empty_session_renders_without_error(empty_report: PerfReport) -> None:
    text = render_text(empty_report)
    assert "n/a" in text
    assert "PAPER PERFORMANCE REPORT" in text


# -- render ------------------------------------------------- #


def test_render_is_deterministic_and_distinguishes_na_from_zero(
    report: PerfReport,
) -> None:
    a = render_text(report)
    b = render_text(report)
    assert a == b
    assert "depth-capped:        1" in a
    # leg-risk section prints a real zero as a number, not n/a
    assert "LEG RISK  (one-legged exposure events)" in a
    assert "events:              0" in a
    # a real zero is printed as a number, not n/a
    assert "rejected:        2" in a


def test_stream_counts_are_passed_through(report: PerfReport) -> None:
    counts = dict(report.stream_counts)
    assert counts["opportunity"] == 5
    assert counts["order_event"] == 6
    assert counts["fill"] == 2
    assert counts["pnl"] == 5
