"""Deterministic offline tests for the M3.1 operational dashboard."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import risk_support
from arbitrage_support import EVAL_TIME
from dashboard_support import (
    MAX_STALENESS,
    T0,
    feed,
    order,
    pnl_row,
    registry,
)

from prediction_market_arbitrage.dashboard import (
    DashboardError,
    Severity,
    build_dashboard,
    render_text,
)
from prediction_market_arbitrage.livebook import BookSnapshot, HealthStatus
from prediction_market_arbitrage.livebook.state import LiveBookFeed
from prediction_market_arbitrage.paper_broker import OrderStatus
from prediction_market_arbitrage.risk import RiskLimits, RiskManager

AFTER_STALE = T0 + MAX_STALENESS + timedelta(seconds=1)


# -- shape / guards --------------------------------------------------------- #


def test_empty_dashboard_is_healthy_and_renders() -> None:
    view = build_dashboard(now=T0)
    assert view.healthy is True
    assert view.alerts == ()
    assert view.feeds == () and view.pairs == () and view.opportunities == ()
    assert view.orders == () and view.fills == () and view.positions == ()
    assert view.pnl == () and view.leg_risk == ()
    text = render_text(view)
    assert "OPERATIONAL DASHBOARD" in text
    assert "HEALTHY" in text


def test_naive_now_is_rejected() -> None:
    with pytest.raises(DashboardError):
        build_dashboard(now=datetime(2026, 3, 3, 10, 0, 0))


def test_view_is_immutable() -> None:
    view = build_dashboard(now=T0)
    with pytest.raises(FrozenInstanceError):
        view.as_of = T0  # type: ignore[misc]


def test_render_is_deterministic() -> None:
    first = build_dashboard(now=T0, feeds=[feed()], registry=registry())
    second = build_dashboard(now=T0, feeds=[feed()], registry=registry())
    assert render_text(first) == render_text(second)


# -- feeds / websocket ---------------------------------------------------- #


def test_healthy_feed_has_no_alert() -> None:
    view = build_dashboard(now=T0, feeds=[feed()])
    (fv,) = view.feeds
    assert fv.trading_enabled is True
    assert fv.status == "healthy"
    assert fv.ws_state == "connected"
    assert fv.stale is False
    assert fv.severity is Severity.OK
    assert view.healthy is True


def test_stale_feed_raises_alert_and_marks_stale() -> None:
    view = build_dashboard(now=AFTER_STALE, feeds=[feed()])
    (fv,) = view.feeds
    assert fv.stale is True
    assert fv.severity is Severity.ALERT
    assert fv.data_age is not None and fv.data_age > MAX_STALENESS
    assert view.healthy is False
    assert any(a.section == "feeds" and "STALE" in a.message for a in view.alerts)


def test_disconnected_feed_alerts_with_ws_state() -> None:
    view = build_dashboard(now=T0, feeds=[feed(status=HealthStatus.DISCONNECTED)])
    (fv,) = view.feeds
    assert fv.ws_state == "disconnected"
    assert fv.trading_enabled is False
    assert fv.severity is Severity.ALERT
    assert view.healthy is False


def test_uninitialized_feed_is_offline_alert() -> None:
    view = build_dashboard(now=T0, feeds=[feed(status=HealthStatus.UNINITIALIZED)])
    (fv,) = view.feeds
    assert fv.ws_state == "offline"
    assert fv.status == "uninitialized"
    assert fv.severity is Severity.ALERT


def test_market_not_open_feed_is_warn_not_alert() -> None:
    lb = LiveBookFeed(
        contract=feed().contract, venue="kalshi", max_staleness=MAX_STALENESS
    )
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=lb.contract.id,
            bids=(),
            asks=(),
            sequence=1,
            source_time=T0,
            market_state="MARKET_STATE_SUSPENDED",
        ),
        received_at=T0,
    )
    view = build_dashboard(now=T0, feeds=[lb])
    (fv,) = view.feeds
    assert fv.status == "market_not_open"
    assert fv.ws_state == "connected"
    assert fv.severity is Severity.WARN
    assert view.healthy is True  # WARN does not fail overall health
    assert any(a.severity is Severity.WARN and a.section == "feeds" for a in view.alerts)


# -- pairs -------------------------------------------------------------- #


def test_registry_pairs_are_projected() -> None:
    view = build_dashboard(now=T0, registry=registry())
    assert [p.pair_id for p in view.pairs] == ["DASH-SYNTH-1", "DASH-SYNTH-2"]
    assert view.pairs[0].verified is True
    assert view.pairs[1].verified is False
    assert view.pairs[0].kalshi_leg == "kalshi-synthetic-market:YES"


# -- opportunities ---------------------------------------------------- #


def test_opportunity_projected_with_edge() -> None:
    ev = risk_support.opportunity(net_edge_total="2.50")
    view = build_dashboard(now=EVAL_TIME, opportunities=[ev])
    (ov,) = view.opportunities
    assert ov.has_opportunity is True
    assert ov.net_edge == Decimal("2.50")
    assert ov.net_edge_per_unit == Decimal("0.25")
    assert ov.stale is False


def test_stale_opportunity_flagged_when_over_max_data_age() -> None:
    ev = risk_support.opportunity(net_edge_total="1", has_edge=False)
    later = ev.evaluation_time + timedelta(minutes=10)
    view = build_dashboard(
        now=later, opportunities=[ev], max_data_age=timedelta(minutes=1)
    )
    (ov,) = view.opportunities
    assert ov.stale is True
    assert any(a.section == "opportunities" for a in view.alerts)


# -- orders / fills ------------------------------------------------- #


def test_orders_and_fills_are_flattened() -> None:
    view = build_dashboard(now=T0, orders=[order(order_id="a", filled="10")])
    (ov,) = view.orders
    assert ov.status == "filled"
    assert ov.filled_quantity == Decimal("10")
    assert ov.remaining_quantity == Decimal("0")
    assert ov.average_fill_price == Decimal("0.50")
    (fv,) = view.fills
    assert fv.order_id == "a"
    assert fv.liquidity == "taker"


def test_rejected_order_warns() -> None:
    view = build_dashboard(
        now=T0,
        orders=[
            order(order_id="r", status=OrderStatus.REJECTED, filled="0", reject_reason="no book")
        ],
    )
    assert any(
        a.section == "orders" and "rejected" in a.message and a.severity is Severity.WARN
        for a in view.alerts
    )
    assert view.healthy is True  # a rejected paper order is degraded, not a stop


# -- positions ---------------------------------------------------- #


def test_position_exposure_uses_explicit_mark() -> None:
    pos = risk_support.position(quantity="10", avg_price="0.40")
    view = build_dashboard(
        now=T0, positions=[pos], marks={pos.contract_id: Decimal("0.30")}
    )
    (pv,) = view.positions
    assert pv.mark == Decimal("0.30")
    assert pv.mark_is_cost_basis is False
    assert pv.exposure == Decimal("3.00")


def test_position_exposure_falls_back_to_cost_basis() -> None:
    pos = risk_support.position(quantity="-8", avg_price="0.25")
    view = build_dashboard(now=T0, positions=[pos])
    (pv,) = view.positions
    assert pv.mark == Decimal("0.25")
    assert pv.mark_is_cost_basis is True
    assert pv.exposure == Decimal("2.00")  # abs(-8) * 0.25


def test_position_without_mark_has_no_exposure() -> None:
    pos = risk_support.position(quantity="5", avg_price="0")
    view = build_dashboard(now=T0, positions=[pos])
    (pv,) = view.positions
    assert pv.mark is None
    assert pv.exposure is None


def test_stale_position_flagged() -> None:
    pos = risk_support.position(quantity="1", as_of=T0)
    view = build_dashboard(
        now=T0 + timedelta(hours=1), positions=[pos], max_data_age=timedelta(minutes=5)
    )
    assert view.positions[0].stale is True
    assert any(a.section == "positions" for a in view.alerts)


# -- pnl -------------------------------------------------------- #


def test_pnl_net_is_realized_plus_unrealized_minus_fees() -> None:
    view = build_dashboard(now=T0, pnl=[pnl_row(realized="2.00", unrealized="0.50", fees="0.10")])
    (pv,) = view.pnl
    assert pv.net == Decimal("2.40")


# -- leg risk ------------------------------------------------- #


def test_unhedged_leg_risk_warns() -> None:
    view = build_dashboard(now=T0, leg_risk=[risk_support.leg_risk(unhedged_quantity="5")])
    (lv,) = view.leg_risk
    assert lv.unhedged_quantity == Decimal("5")
    assert any(a.section == "leg_risk" and a.severity is Severity.WARN for a in view.alerts)


def test_both_terminal_leg_risk_does_not_warn() -> None:
    view = build_dashboard(
        now=T0, leg_risk=[risk_support.leg_risk(unhedged_quantity="5", both_terminal=True)]
    )
    assert not any(a.section == "leg_risk" for a in view.alerts)


# -- risk state --------------------------------------------- #


def test_kill_switch_is_alert() -> None:
    rm = RiskManager(RiskLimits())
    rm.kill("manual halt")
    view = build_dashboard(now=T0, risk=rm)
    assert view.risk.killed is True
    assert view.risk.kill_reason == "manual halt"
    assert view.healthy is False
    assert view.alerts[0].severity is Severity.ALERT
    assert view.alerts[0].section == "risk"


def test_consecutive_errors_and_daily_loss_warn() -> None:
    rm = RiskManager(RiskLimits())
    rm.record_error()
    rm.record_error()
    rm.record_realized_pnl(Decimal("-4.00"), at=T0)
    view = build_dashboard(now=T0, risk=rm)
    assert view.risk.consecutive_errors == 2
    assert view.risk.daily_loss == Decimal("4.00")
    sections = {(a.section, a.message.split()[0]) for a in view.alerts}
    assert ("risk", "2") in sections  # consecutive errors
    assert any("daily realized loss" in a.message for a in view.alerts)


def test_unhedged_pair_from_risk_snapshot_is_listed() -> None:
    rm = RiskManager(RiskLimits())
    rm.observe_leg_risk(risk_support.leg_risk(unhedged_quantity="3"), now=T0)
    view = build_dashboard(now=T0 + timedelta(minutes=1), risk=rm)
    assert len(view.risk.unhedged_pairs) == 1
    assert any("unhedged since" in a.message for a in view.alerts)


def test_last_risk_decision_rejected_surfaces_reasons() -> None:
    rm = RiskManager(RiskLimits())
    decision = rm.evaluate_opportunity(None, now=T0)  # allowed (no limits set)
    assert decision.allowed is True
    rm2 = RiskManager(RiskLimits(max_order_size=Decimal("1")))
    rejected = rm2.evaluate_order(risk_support.order(quantity="10"), now=T0)
    view = build_dashboard(now=T0, risk=rm2, last_risk_decision=rejected)
    assert view.risk.last_decision_allowed is False
    assert any("last risk decision REJECTED" in a.message for a in view.alerts)


# -- alert ordering + worst age --------------------------- #


def test_alerts_rank_alert_before_warn() -> None:
    rm = RiskManager(RiskLimits())
    rm.record_error()
    view = build_dashboard(
        now=AFTER_STALE,
        feeds=[feed()],  # stale -> ALERT
        risk=rm,  # consecutive error -> WARN
    )
    severities = [a.severity for a in view.alerts]
    assert severities == sorted(
        severities, key=lambda s: 0 if s is Severity.ALERT else 1
    )
    assert severities[0] is Severity.ALERT


def test_worst_data_age_is_the_max_nonnegative_age() -> None:
    pos = risk_support.position(quantity="1", as_of=T0)
    view = build_dashboard(
        now=T0 + timedelta(seconds=30), feeds=[feed()], positions=[pos]
    )
    assert view.worst_data_age == timedelta(seconds=30)


def test_render_marks_alert_and_stale_rows() -> None:
    view = build_dashboard(now=AFTER_STALE, feeds=[feed()])
    text = render_text(view)
    assert "[ALERT]" in text
    assert "[STALE]" in text
    assert "ATTENTION REQUIRED" in text
