"""Assemble a :class:`DashboardView` from the objects the pipeline already
produces (Milestone M3.1).

Read-only and deterministic: every input is inspected, never mutated; the caller
injects ``now`` (timezone-aware); no wall-clock, no I/O, no order submission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.arbitrage.engine import OpportunityEvaluation
from prediction_market_arbitrage.livebook import HealthStatus
from prediction_market_arbitrage.livebook.state import LiveBookFeed
from prediction_market_arbitrage.paper_broker import Fill, LegRiskSnapshot, Order
from prediction_market_arbitrage.recorder import PnlRow, PositionRow
from prediction_market_arbitrage.registry import MarketPairRecord, MarketPairRegistry, PairStatus
from prediction_market_arbitrage.risk import RiskDecision, RiskManager

from .errors import DashboardError
from .models import (
    Alert,
    DashboardView,
    FeedView,
    FillView,
    LegRiskView,
    OpportunityView,
    OrderView,
    PairView,
    PnlView,
    PositionView,
    RiskView,
    Severity,
)

_ZERO = Decimal(0)

#: HealthStatus values that mean the socket itself is up (the problem, if any,
#: is with the data or the venue market, not the connection).
_SOCKET_UP = frozenset(
    {
        HealthStatus.HEALTHY,
        HealthStatus.STALE,
        HealthStatus.DESYNCED,
        HealthStatus.MARKET_NOT_OPEN,
    }
)
#: HealthStatus values that are expected/transient rather than a hard failure.
_SOFT_STATUSES = frozenset({HealthStatus.RESYNCING, HealthStatus.MARKET_NOT_OPEN})


def build_dashboard(
    *,
    now: datetime,
    feeds: Sequence[LiveBookFeed] = (),
    registry: MarketPairRegistry | None = None,
    opportunities: Sequence[OpportunityEvaluation] = (),
    orders: Sequence[Order] = (),
    positions: Sequence[PositionRow] = (),
    marks: Mapping[str, Decimal] | None = None,
    pnl: Sequence[PnlRow] = (),
    leg_risk: Sequence[LegRiskSnapshot] = (),
    risk: RiskManager | None = None,
    last_risk_decision: RiskDecision | None = None,
    max_data_age: timedelta | None = None,
) -> DashboardView:
    """Compose the current operational picture. Every section is optional; an
    omitted section renders empty."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise DashboardError("now must be a timezone-aware datetime")

    feed_views = tuple(_feed_view(feed, now) for feed in feeds)
    pair_views = tuple(_pair_view(record) for record in (registry.all() if registry else ()))
    opp_views = tuple(_opportunity_view(ev, now, max_data_age) for ev in opportunities)
    order_views = tuple(_order_view(order) for order in orders)
    fill_views = tuple(_fill_view(fill) for order in orders for fill in order.fills)
    position_views = tuple(_position_view(row, now, marks, max_data_age) for row in positions)
    pnl_views = tuple(_pnl_view(row) for row in pnl)
    leg_risk_views = tuple(_leg_risk_view(snap) for snap in leg_risk)
    risk_view = _risk_view(risk, last_risk_decision, now)

    alerts = _collect_alerts(
        feed_views, opp_views, order_views, position_views, leg_risk_views, risk_view
    )
    return DashboardView(
        as_of=now,
        feeds=feed_views,
        pairs=pair_views,
        opportunities=opp_views,
        orders=order_views,
        fills=fill_views,
        positions=position_views,
        pnl=pnl_views,
        leg_risk=leg_risk_views,
        risk=risk_view,
        alerts=alerts,
        worst_data_age=_worst_data_age(feed_views, opp_views, position_views),
    )


# --------------------------------------------------------------------------- #
# Per-section projections
# --------------------------------------------------------------------------- #


def _feed_view(feed: LiveBookFeed, now: datetime) -> FeedView:
    health = feed.health(now)
    last_update = health.last_update
    data_age = None if last_update is None else now - last_update
    stale = health.status is HealthStatus.STALE or (
        data_age is not None and (data_age < timedelta(0) or data_age > feed.max_staleness)
    )
    return FeedView(
        venue=feed.venue,
        contract_id=feed.contract.id,
        status=health.status.value,
        ws_state=_ws_state(health.status),
        reason=health.reason,
        trading_enabled=health.trading_enabled,
        last_update=last_update,
        last_sequence=health.last_sequence,
        data_age=data_age,
        max_staleness=feed.max_staleness,
        stale=stale,
        severity=_feed_severity(health.status, stale),
    )


def _ws_state(status: HealthStatus) -> str:
    if status is HealthStatus.DISCONNECTED:
        return "disconnected"
    if status is HealthStatus.RESYNCING:
        return "resyncing"
    if status is HealthStatus.UNINITIALIZED:
        return "offline"
    return "connected" if status in _SOCKET_UP else "unknown"


def _feed_severity(status: HealthStatus, stale: bool) -> Severity:
    if status is HealthStatus.HEALTHY:
        return Severity.OK
    if stale or status not in _SOFT_STATUSES:
        return Severity.ALERT
    return Severity.WARN


def _pair_view(rec: MarketPairRecord) -> PairView:
    return PairView(
        pair_id=rec.pair_id,
        proposition=rec.proposition,
        status=str(rec.status),
        relation=str(rec.relation),
        verified=rec.status is PairStatus.VERIFIED,
        kalshi_leg=f"{rec.kalshi.market_id}:{rec.kalshi.outcome}",
        polymarket_us_leg=f"{rec.polymarket_us.market_id}:{rec.polymarket_us.outcome}",
    )


def _opportunity_view(
    ev: OpportunityEvaluation, now: datetime, max_data_age: timedelta | None
) -> OpportunityView:
    age = now - ev.evaluation_time
    stale = max_data_age is not None and (age < timedelta(0) or age > max_data_age)
    return OpportunityView(
        pair_id=ev.pair_id,
        relation=str(ev.relation),
        has_opportunity=ev.has_opportunity,
        net_edge=ev.net_edge,
        net_edge_per_unit=ev.net_edge_per_unit,
        executable_quantity=ev.executable_quantity,
        depth_capped=ev.depth_capped,
        rejection_reason=ev.rejection_reason,
        evaluation_time=ev.evaluation_time,
        data_age=age,
        stale=stale,
    )


def _order_view(order: Order) -> OrderView:
    req = order.request
    return OrderView(
        order_id=order.order_id,
        venue=req.venue,
        contract_id=req.contract_id,
        side=req.side,
        order_type=req.order_type,
        quantity=req.quantity,
        status=order.status.value,
        filled_quantity=order.filled_quantity,
        remaining_quantity=order.remaining_quantity,
        average_fill_price=order.average_fill_price,
        total_fees=order.total_fees,
        terminal=order.status.is_terminal,
        reject_reason=order.reject_reason,
    )


def _fill_view(f: Fill) -> FillView:
    return FillView(
        fill_id=f.fill_id,
        order_id=f.order_id,
        venue=f.venue,
        contract_id=f.contract_id,
        price=f.price,
        quantity=f.quantity,
        fee=f.fee,
        liquidity=f.liquidity,
        filled_at=f.filled_at,
    )


def _position_view(
    row: PositionRow,
    now: datetime,
    marks: Mapping[str, Decimal] | None,
    max_data_age: timedelta | None,
) -> PositionView:
    explicit = marks is not None and row.contract_id in marks
    mark: Decimal | None
    if explicit:
        assert marks is not None
        mark = marks[row.contract_id]
        is_cost_basis = False
    elif row.avg_price > _ZERO:
        mark = row.avg_price
        is_cost_basis = True
    else:
        mark = None
        is_cost_basis = False
    exposure = None if mark is None else abs(row.quantity) * mark
    age = now - row.as_of
    stale = max_data_age is not None and (age < timedelta(0) or age > max_data_age)
    return PositionView(
        venue=row.venue,
        contract_id=row.contract_id,
        quantity=row.quantity,
        avg_price=row.avg_price,
        mark=mark,
        mark_is_cost_basis=is_cost_basis,
        exposure=exposure,
        as_of=row.as_of,
        data_age=age,
        stale=stale,
    )


def _pnl_view(row: PnlRow) -> PnlView:
    return PnlView(
        scope=row.scope,
        scope_id=row.scope_id,
        realized=row.realized,
        unrealized=row.unrealized,
        fees=row.fees,
        net=row.realized + row.unrealized - row.fees,
        as_of=row.as_of,
    )


def _leg_risk_view(snap: LegRiskSnapshot) -> LegRiskView:
    return LegRiskView(
        order_a_id=snap.order_a_id,
        order_b_id=snap.order_b_id,
        unhedged_quantity=snap.unhedged_quantity,
        unhedged_notional=snap.unhedged_notional,
        both_terminal=snap.both_terminal,
        as_of=snap.as_of,
    )


def _risk_view(
    risk: RiskManager | None, last_decision: RiskDecision | None, now: datetime
) -> RiskView:
    if risk is None:
        return RiskView(
            killed=False,
            kill_reason="",
            consecutive_errors=0,
            daily_realized_pnl=_ZERO,
            daily_loss=_ZERO,
            unhedged_pairs=(),
            last_decision_allowed=None if last_decision is None else last_decision.allowed,
            last_decision_reasons=() if last_decision is None else last_decision.reasons,
        )
    snap = risk.snapshot(now=now)
    return RiskView(
        killed=snap.killed,
        kill_reason=snap.kill_reason,
        consecutive_errors=snap.consecutive_errors,
        daily_realized_pnl=snap.daily_realized_pnl,
        daily_loss=snap.daily_loss,
        unhedged_pairs=snap.unhedged_pairs,
        last_decision_allowed=None if last_decision is None else last_decision.allowed,
        last_decision_reasons=() if last_decision is None else last_decision.reasons,
    )


# --------------------------------------------------------------------------- #
# Alerts — the "make unhealthy / stale obvious" surface
# --------------------------------------------------------------------------- #


def _collect_alerts(
    feeds: Sequence[FeedView],
    opportunities: Sequence[OpportunityView],
    orders: Sequence[OrderView],
    positions: Sequence[PositionView],
    leg_risk: Sequence[LegRiskView],
    risk: RiskView,
) -> tuple[Alert, ...]:
    alerts: list[Alert] = []

    if risk.killed:
        alerts.append(Alert(Severity.ALERT, "risk", f"kill switch engaged: {risk.kill_reason}"))

    for f in feeds:
        label = f"{f.venue}/{f.contract_id}"
        if f.stale:
            alerts.append(Alert(Severity.ALERT, "feeds", f"{label} feed STALE: {f.reason}"))
        elif f.severity is Severity.ALERT:
            alerts.append(
                Alert(Severity.ALERT, "feeds", f"{label} feed {f.status}: {f.reason}")
            )
        elif f.severity is Severity.WARN:
            alerts.append(
                Alert(Severity.WARN, "feeds", f"{label} feed {f.status}: {f.reason}")
            )

    if risk.consecutive_errors > 0:
        alerts.append(
            Alert(Severity.WARN, "risk", f"{risk.consecutive_errors} consecutive error(s)")
        )
    if risk.daily_loss > _ZERO:
        alerts.append(Alert(Severity.WARN, "risk", f"daily realized loss {risk.daily_loss}"))
    for key, since in risk.unhedged_pairs:
        alerts.append(
            Alert(Severity.WARN, "risk", f"pair {key} unhedged since {since.isoformat()}")
        )
    if risk.last_decision_allowed is False:
        alerts.append(
            Alert(
                Severity.WARN,
                "risk",
                "last risk decision REJECTED: " + "; ".join(risk.last_decision_reasons),
            )
        )

    for lr in leg_risk:
        if lr.unhedged_quantity != _ZERO and not lr.both_terminal:
            alerts.append(
                Alert(
                    Severity.WARN,
                    "leg_risk",
                    f"{lr.order_a_id}/{lr.order_b_id} unhedged qty {lr.unhedged_quantity}",
                )
            )

    for o in orders:
        if o.status == "rejected":
            alerts.append(
                Alert(Severity.WARN, "orders", f"order {o.order_id} rejected: {o.reject_reason}")
            )

    for op in opportunities:
        if op.stale:
            alerts.append(
                Alert(
                    Severity.WARN,
                    "opportunities",
                    f"{op.pair_id} evaluation stale (age {op.data_age})",
                )
            )
    for p in positions:
        if p.stale:
            alerts.append(
                Alert(
                    Severity.WARN,
                    "positions",
                    f"{p.venue}/{p.contract_id} position snapshot stale (age {p.data_age})",
                )
            )

    # ALERT before WARN; list.sort is stable so section order is preserved within
    # each severity band.
    alerts.sort(key=lambda a: 0 if a.severity is Severity.ALERT else 1)
    return tuple(alerts)


def _worst_data_age(
    feeds: Sequence[FeedView],
    opportunities: Sequence[OpportunityView],
    positions: Sequence[PositionView],
) -> timedelta | None:
    candidates: list[timedelta | None] = [f.data_age for f in feeds]
    candidates += [op.data_age for op in opportunities]
    candidates += [p.data_age for p in positions]
    ages = [age for age in candidates if age is not None and age >= timedelta(0)]
    return max(ages) if ages else None
