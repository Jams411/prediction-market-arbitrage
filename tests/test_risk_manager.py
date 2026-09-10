"""Deterministic offline tests for the M2.5 risk manager."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from risk_support import CONTRACT_ID, T0, at, health, leg_risk, opportunity, order, position

from prediction_market_arbitrage.livebook import HealthStatus
from prediction_market_arbitrage.risk import RiskError, RiskLimits, RiskManager

D = Decimal


def _mgr(**limit_kwargs: object) -> RiskManager:
    return RiskManager(RiskLimits(**limit_kwargs))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# kill switch
# --------------------------------------------------------------------------- #


def test_kill_switch_blocks_everything() -> None:
    mgr = _mgr()
    assert mgr.evaluate_order(order(), now=at(0)).allowed is True
    mgr.kill("manual halt")
    decision = mgr.evaluate_order(order(), now=at(1))
    assert decision.rejected
    assert any("kill switch engaged: manual halt" in r for r in decision.reasons)
    mgr.resume()
    assert mgr.evaluate_order(order(), now=at(2)).allowed is True


# --------------------------------------------------------------------------- #
# consecutive errors
# --------------------------------------------------------------------------- #


def test_consecutive_error_limit() -> None:
    mgr = _mgr(max_consecutive_errors=3)
    mgr.record_error()
    mgr.record_error()
    assert mgr.evaluate_order(order(), now=at(0)).allowed is True
    mgr.record_error()
    assert mgr.evaluate_order(order(), now=at(1)).rejected
    mgr.record_success()
    assert mgr.evaluate_order(order(), now=at(2)).allowed is True


# --------------------------------------------------------------------------- #
# max daily loss
# --------------------------------------------------------------------------- #


def test_max_daily_loss_is_per_utc_day() -> None:
    mgr = _mgr(max_daily_loss=D("100"))
    mgr.record_realized_pnl(D("-60"), at=at(0))
    assert mgr.evaluate_order(order(), now=at(1)).allowed is True
    mgr.record_realized_pnl(D("-45"), at=at(2))
    rej = mgr.evaluate_order(order(), now=at(3))
    assert rej.rejected and any("daily realized loss 105" in r for r in rej.reasons)
    # next UTC day resets
    next_day = T0 + timedelta(days=1)
    assert mgr.evaluate_order(order(), now=next_day).allowed is True


# --------------------------------------------------------------------------- #
# max order size
# --------------------------------------------------------------------------- #


def test_max_order_size_uses_strict_greater_than() -> None:
    mgr = _mgr(max_order_size=D("50"))
    assert mgr.evaluate_order(order(quantity="50"), now=at(0)).allowed is True
    assert mgr.evaluate_order(order(quantity="50.0001"), now=at(0)).rejected


# --------------------------------------------------------------------------- #
# minimum net edge
# --------------------------------------------------------------------------- #


def test_min_net_edge_per_unit() -> None:
    mgr = _mgr(min_net_edge_per_unit=D("0.02"))
    assert mgr.evaluate_order(
        order(), now=at(0), opportunity=opportunity(net_edge_total="0.30")
    ).allowed is True  # 0.03/unit
    assert mgr.evaluate_order(
        order(), now=at(0), opportunity=opportunity(net_edge_total="0.10")
    ).rejected  # 0.01/unit
    assert mgr.evaluate_order(
        order(), now=at(0), opportunity=opportunity(net_edge_total="1.0", has_edge=False)
    ).rejected


def test_min_net_edge_fails_closed_without_an_opportunity() -> None:
    mgr = _mgr(min_net_edge_per_unit=D("0.02"))
    decision = mgr.evaluate_order(order(), now=at(0))
    assert decision.rejected
    assert any("no opportunity evaluation provided" in r for r in decision.reasons)


# --------------------------------------------------------------------------- #
# max data age / feed health
# --------------------------------------------------------------------------- #


def test_max_data_age() -> None:
    mgr = _mgr(max_data_age=timedelta(seconds=5))
    fresh = health(last_update=at(0), as_of=at(0))
    assert mgr.evaluate_order(order(), now=at(3), health=fresh).allowed is True
    assert mgr.evaluate_order(order(), now=at(10), health=fresh).rejected


def test_max_data_age_fails_closed_without_health() -> None:
    mgr = _mgr(max_data_age=timedelta(seconds=5))
    decision = mgr.evaluate_order(order(), now=at(0))
    assert decision.rejected
    assert any("no market-data health provided" in r for r in decision.reasons)


def test_unhealthy_feed_is_rejected_even_without_a_data_age_limit() -> None:
    mgr = _mgr()
    stale = health(status=HealthStatus.STALE, reason="too old", last_update=at(0))
    decision = mgr.evaluate_order(order(), now=at(1), health=stale)
    assert decision.rejected
    assert any("feed not healthy: stale" in r for r in decision.reasons)
    # a healthy feed with no age limit passes
    assert mgr.evaluate_order(order(), now=at(1), health=health()).allowed is True


def test_future_dated_health_fails_closed() -> None:
    mgr = _mgr(max_data_age=timedelta(seconds=5))
    ahead = health(last_update=at(100), as_of=at(100))
    assert mgr.evaluate_order(order(), now=at(0), health=ahead).rejected


# --------------------------------------------------------------------------- #
# max position
# --------------------------------------------------------------------------- #


def test_max_position_uses_projected_signed_quantity() -> None:
    mgr = _mgr(max_position=D("100"))
    pos = {CONTRACT_ID: position(quantity="80")}
    assert mgr.evaluate_order(order(quantity="20"), now=at(0), positions=pos).allowed is True
    assert mgr.evaluate_order(order(quantity="30"), now=at(0), positions=pos).rejected
    # selling reduces the magnitude
    assert mgr.evaluate_order(
        order(side="sell", quantity="30"), now=at(0), positions=pos
    ).allowed is True


def test_max_position_fails_closed_without_positions() -> None:
    decision = _mgr(max_position=D("100")).evaluate_order(order(), now=at(0))
    assert decision.rejected
    assert any("no positions provided" in r for r in decision.reasons)


# --------------------------------------------------------------------------- #
# max exposure
# --------------------------------------------------------------------------- #


def test_max_exposure_sums_projected_notional_across_contracts() -> None:
    mgr = _mgr(max_exposure=D("100"))
    pos = {
        CONTRACT_ID: position(CONTRACT_ID, quantity="100", avg_price="0.40"),  # 40
        "RM-T2:YES": position("RM-T2:YES", quantity="50", avg_price="0.60"),  # 30
    }
    # buy 100 more of RM-T1 -> projected 200 * 0.40 = 80, + 30 = 110 -> reject
    assert mgr.evaluate_order(
        order(quantity="100", limit_price="0.40"), now=at(0), positions=pos
    ).rejected
    # buy 20 -> 120 * 0.40 = 48, + 30 = 78 -> allow
    assert mgr.evaluate_order(
        order(quantity="20", limit_price="0.40"), now=at(0), positions=pos
    ).allowed is True


def test_max_exposure_fails_closed_when_a_contract_cannot_be_valued() -> None:
    mgr = _mgr(max_exposure=D("100"))
    # the order's own contract is valued via its limit price; the held position
    # in RM-T2 has no avg price and no mark -> cannot be valued -> fail closed.
    pos = {"RM-T2:YES": position("RM-T2:YES", quantity="10", avg_price="0")}
    decision = mgr.evaluate_order(order(limit_price="0.40"), now=at(0), positions=pos)
    assert decision.rejected
    assert any("cannot value RM-T2:YES" in r for r in decision.reasons)


# --------------------------------------------------------------------------- #
# max unhedged time
# --------------------------------------------------------------------------- #


def test_max_unhedged_time_blocks_after_the_window() -> None:
    mgr = _mgr(max_unhedged_time=timedelta(seconds=10))
    unhedged = leg_risk(unhedged_quantity="5")
    # first sighting records the start; still inside the window
    assert mgr.evaluate_order(order(), now=at(0), leg=unhedged).allowed is True
    # 15s later, same pair still unhedged -> reject
    rej = mgr.evaluate_order(order(), now=at(15), leg=unhedged)
    assert rej.rejected and any("unhedged for" in r for r in rej.reasons)
    # once the pair is hedged again the timer clears
    hedged = leg_risk(unhedged_quantity="0")
    assert mgr.evaluate_order(order(), now=at(16), leg=hedged).allowed is True
    assert mgr.state.unhedged_since("legA|legB") is None


def test_unhedged_but_both_terminal_counts_as_hedged() -> None:
    mgr = _mgr(max_unhedged_time=timedelta(seconds=1))
    done = leg_risk(unhedged_quantity="5", both_terminal=True)
    assert mgr.evaluate_order(order(), now=at(0), leg=done).allowed is True
    assert mgr.evaluate_order(order(), now=at(100), leg=done).allowed is True


def test_max_unhedged_time_fails_closed_without_a_leg_snapshot() -> None:
    decision = _mgr(max_unhedged_time=timedelta(seconds=10)).evaluate_order(order(), now=at(0))
    assert decision.rejected
    assert any("no leg-risk snapshot provided" in r for r in decision.reasons)


# --------------------------------------------------------------------------- #
# decision shape / opportunity gate / determinism / misuse
# --------------------------------------------------------------------------- #


def test_decision_collects_every_failing_reason() -> None:
    mgr = _mgr(max_order_size=D("5"), min_net_edge_per_unit=D("0.10"))
    mgr.kill("halt")
    decision = mgr.evaluate_order(order(quantity="10"), now=at(0))
    assert decision.rejected
    assert len(decision.reasons) == 3  # kill + order size + missing opportunity
    assert "kill_switch" in decision.checks_run
    assert "max_position" not in decision.checks_run  # not configured


def test_fully_configured_happy_path_runs_all_checks() -> None:
    mgr = _mgr(
        max_position=D("1000"),
        max_exposure=D("1000"),
        max_order_size=D("100"),
        min_net_edge_per_unit=D("0.01"),
        max_data_age=timedelta(seconds=30),
        max_unhedged_time=timedelta(seconds=60),
        max_consecutive_errors=5,
        max_daily_loss=D("500"),
    )
    decision = mgr.evaluate_order(
        order(quantity="10"),
        now=at(1),
        positions={CONTRACT_ID: position(quantity="10", avg_price="0.45")},
        opportunity=opportunity(net_edge_total="0.50"),
        health=health(last_update=at(0), as_of=at(0)),
        leg=leg_risk(unhedged_quantity="0"),
    )
    assert decision.allowed is True
    assert set(decision.checks_run) >= {
        "kill_switch",
        "consecutive_errors",
        "max_daily_loss",
        "max_order_size",
        "min_net_edge_per_unit",
        "feed_health",
        "max_position",
        "max_exposure",
        "max_unhedged_time",
    }


def test_evaluate_opportunity_is_the_session_and_edge_subset() -> None:
    mgr = _mgr(min_net_edge_per_unit=D("0.02"), max_order_size=D("1"))
    good = mgr.evaluate_opportunity(opportunity(net_edge_total="0.30"), now=at(0))
    assert good.allowed is True
    assert "max_order_size" not in good.checks_run  # order-specific, not run here
    bad = mgr.evaluate_opportunity(opportunity(net_edge_total="0.05"), now=at(0))
    assert bad.rejected


def test_same_inputs_produce_the_same_decision() -> None:
    def run() -> tuple[object, ...]:
        mgr = _mgr(max_position=D("100"), min_net_edge_per_unit=D("0.02"))
        mgr.record_error()
        d1 = mgr.evaluate_order(
            order(quantity="40"),
            now=at(0),
            positions={CONTRACT_ID: position(quantity="70")},
            opportunity=opportunity(net_edge_total="0.10"),
        )
        d2 = mgr.evaluate_order(order(quantity="5"), now=at(1))
        return (d1.allowed, d1.reasons, d1.checks_run, d2.allowed, d2.reasons)

    assert run() == run()


def test_snapshot_reflects_state() -> None:
    mgr = _mgr(max_unhedged_time=timedelta(seconds=1))
    mgr.record_error()
    mgr.record_realized_pnl(D("-25"), at=at(0))
    mgr.observe_leg_risk(leg_risk(unhedged_quantity="3"), now=at(0))
    snap = mgr.snapshot(now=at(1))
    assert snap.consecutive_errors == 1
    assert snap.daily_loss == D("25")
    assert snap.unhedged_pairs == (("legA|legB", at(0)),)
    assert snap.killed is False


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(RiskError, match="timezone-aware"):
        _mgr().evaluate_order(order(), now=datetime(2026, 3, 3, 10))  # noqa: DTZ001


def test_bad_limits_raise() -> None:
    with pytest.raises(RiskError):
        RiskLimits(max_position=D("-1"))
    with pytest.raises(RiskError):
        RiskLimits(max_data_age=timedelta(seconds=-1))
    with pytest.raises(RiskError):
        RiskLimits(max_consecutive_errors=0)


def test_evaluate_order_requires_an_order_request() -> None:
    with pytest.raises(RiskError, match="OrderRequest"):
        _mgr().evaluate_order("not an order", now=at(0))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Real-money gate hardening (audit obs/realmoney-gates-9-11-15)
#   #11 Kill switch      — also gates evaluate_opportunity
#   #12 Position limits  — boundary is strict-greater-than, both signs
#   #13 Daily loss       — blocks AT the limit; never on a profit day
# The RiskManager veto is deterministic and fail-closed; it is NOT yet wired
# to an execution path (none exists — D-023), so these lock the check
# behaviour, not gate completion.
# --------------------------------------------------------------------------- #


def test_gate11_kill_switch_also_blocks_evaluate_opportunity() -> None:
    mgr = _mgr(min_net_edge_per_unit=D("0.01"))
    good = opportunity(net_edge_total="0.50")
    assert mgr.evaluate_opportunity(good, now=at(0)).allowed is True
    mgr.kill("panic")
    decision = mgr.evaluate_opportunity(good, now=at(1))
    assert decision.rejected
    assert any("kill switch engaged: panic" in r for r in decision.reasons)
    mgr.resume()
    assert mgr.evaluate_opportunity(good, now=at(2)).allowed is True


def test_gate12_position_limit_boundary_is_strict_greater_than_both_signs() -> None:
    mgr = _mgr(max_position=D("100"))
    pos = {CONTRACT_ID: position(quantity="90")}
    assert mgr.evaluate_order(  # projected 100 == limit -> allowed
        order(quantity="10"), now=at(0), positions=pos
    ).allowed is True
    assert mgr.evaluate_order(  # projected 101 -> rejected
        order(quantity="11"), now=at(0), positions=pos
    ).rejected
    assert mgr.evaluate_order(  # sell flips sign to -160, |.| > 100 -> rejected
        order(side="sell", quantity="250"), now=at(0), positions=pos
    ).rejected


def test_gate13_daily_loss_blocks_at_exactly_the_limit_and_not_on_a_profit_day() -> None:
    mgr = _mgr(max_daily_loss=D("100"))
    mgr.record_realized_pnl(D("-100"), at=at(0))
    assert mgr.evaluate_order(order(), now=at(1)).rejected  # loss == limit
    mgr.record_realized_pnl(D("300"), at=at(2))  # day now net +200
    assert mgr.evaluate_order(order(), now=at(3)).allowed is True
