"""Plain-text rendering of a :class:`DashboardView` (Milestone M3.1).

Deterministic: the same view always renders the same string. No colour codes —
unhealthy / stale rows are marked with a leading ``[ALERT]`` / ``[WARN]`` /
``[STALE]`` token so the state is obvious in any terminal or log.
"""

from __future__ import annotations

from datetime import timedelta

from .models import DashboardView, Severity

_RULE = "=" * 72


def render_text(view: DashboardView) -> str:
    """Render ``view`` as a sectioned plain-text report."""
    lines: list[str] = []
    overall = "HEALTHY" if view.healthy else "ATTENTION REQUIRED"
    lines.append(_RULE)
    lines.append(f"OPERATIONAL DASHBOARD  —  {view.as_of.isoformat()}  —  {overall}")
    worst = _fmt_age(view.worst_data_age)
    lines.append(f"worst data age: {worst}")
    lines.append(_RULE)

    lines.append("")
    lines.append(f"ALERTS ({len(view.alerts)})")
    if not view.alerts:
        lines.append("  none")
    for alert in view.alerts:
        lines.append(f"  [{alert.severity.value.upper()}] {alert.section}: {alert.message}")

    lines.append("")
    lines.append(f"FEEDS / WEBSOCKET ({len(view.feeds)})")
    if not view.feeds:
        lines.append("  none")
    for f in view.feeds:
        lines.append(
            f"  {_mark(f.severity, f.stale)} {f.venue}/{f.contract_id}  "
            f"status={f.status} ws={f.ws_state} trading_enabled={f.trading_enabled} "
            f"seq={f.last_sequence} age={_fmt_age(f.data_age)}/{_fmt_age(f.max_staleness)}"
            + (f"  {f.reason}" if f.reason else "")
        )

    lines.append("")
    lines.append(f"VERIFIED / CURATED PAIRS ({len(view.pairs)})")
    if not view.pairs:
        lines.append("  none")
    for p in view.pairs:
        tag = "VERIFIED" if p.verified else p.status
        lines.append(
            f"  [{tag}] {p.pair_id}  {p.relation}  "
            f"kalshi={p.kalshi_leg}  polymarket_us={p.polymarket_us_leg}"
        )
        lines.append(f"      {p.proposition}")

    lines.append("")
    lines.append(f"OPPORTUNITIES ({len(view.opportunities)})")
    if not view.opportunities:
        lines.append("  none")
    for op in view.opportunities:
        state = "OPP" if op.has_opportunity else "no-opp"
        stale = " [STALE]" if op.stale else ""
        lines.append(
            f"  [{state}]{stale} {op.pair_id}  net_edge={op.net_edge} "
            f"edge/unit={op.net_edge_per_unit} qty={op.executable_quantity} "
            f"depth_capped={op.depth_capped} age={_fmt_age(op.data_age)}"
            + (
                f"  {op.rejection_reason}"
                if not op.has_opportunity and op.rejection_reason
                else ""
            )
        )

    lines.append("")
    lines.append(f"PAPER ORDERS ({len(view.orders)})")
    if not view.orders:
        lines.append("  none")
    for ordv in view.orders:
        flag = "[!] " if ordv.status == "rejected" else ""
        lines.append(
            f"  {flag}{ordv.order_id}  {ordv.venue}/{ordv.contract_id} {ordv.side} "
            f"{ordv.order_type} {ordv.status}  filled={ordv.filled_quantity}/{ordv.quantity} "
            f"avg={ordv.average_fill_price} fees={ordv.total_fees}"
            + (f"  {ordv.reject_reason}" if ordv.reject_reason else "")
        )

    lines.append("")
    lines.append(f"FILLS ({len(view.fills)})")
    if not view.fills:
        lines.append("  none")
    for fill in view.fills:
        lines.append(
            f"  {fill.fill_id}  order={fill.order_id} {fill.venue}/{fill.contract_id} "
            f"{fill.quantity} @ {fill.price}  fee={fill.fee} {fill.liquidity} "
            f"{fill.filled_at.isoformat()}"
        )

    lines.append("")
    lines.append(f"POSITIONS ({len(view.positions)})")
    if not view.positions:
        lines.append("  none")
    for pos in view.positions:
        stale = " [STALE]" if pos.stale else ""
        basis = " (cost-basis approx)" if pos.mark_is_cost_basis else ""
        mark = "n/a" if pos.mark is None else f"{pos.mark}{basis}"
        exposure = "n/a" if pos.exposure is None else str(pos.exposure)
        lines.append(
            f"  {pos.venue}/{pos.contract_id}{stale}  qty={pos.quantity} avg={pos.avg_price} "
            f"mark={mark} exposure={exposure} age={_fmt_age(pos.data_age)}"
        )

    lines.append("")
    lines.append(f"PnL ({len(view.pnl)})")
    if not view.pnl:
        lines.append("  none")
    for row in view.pnl:
        lines.append(
            f"  {row.scope}:{row.scope_id}  realized={row.realized} "
            f"unrealized={row.unrealized} fees={row.fees} net={row.net}"
        )

    lines.append("")
    lines.append(f"LEG RISK ({len(view.leg_risk)})")
    if not view.leg_risk:
        lines.append("  none")
    for lr in view.leg_risk:
        unhedged = lr.unhedged_quantity != 0 and not lr.both_terminal
        flag = "[!] " if unhedged else ""
        notional = "n/a" if lr.unhedged_notional is None else str(lr.unhedged_notional)
        lines.append(
            f"  {flag}{lr.order_a_id}/{lr.order_b_id}  unhedged_qty={lr.unhedged_quantity} "
            f"notional={notional} both_terminal={lr.both_terminal}"
        )

    lines.append("")
    lines.append("RISK STATE")
    r = view.risk
    kill = f"ENGAGED ({r.kill_reason})" if r.killed else "clear"
    lines.append(f"  kill switch: {kill}")
    lines.append(f"  consecutive errors: {r.consecutive_errors}")
    lines.append(
        f"  daily realized PnL: {r.daily_realized_pnl}  (loss magnitude {r.daily_loss})"
    )
    if r.unhedged_pairs:
        for key, since in r.unhedged_pairs:
            lines.append(f"  unhedged: {key} since {since.isoformat()}")
    else:
        lines.append("  unhedged pairs: none")
    if r.last_decision_allowed is None:
        lines.append("  last decision: n/a")
    else:
        verdict = "ALLOWED" if r.last_decision_allowed else "REJECTED"
        lines.append(f"  last decision: {verdict}")
        for reason in r.last_decision_reasons:
            lines.append(f"      - {reason}")

    lines.append(_RULE)
    return "\n".join(lines)


def _mark(severity: Severity, stale: bool) -> str:
    if stale:
        return "[STALE]"
    if severity is Severity.ALERT:
        return "[ALERT]"
    if severity is Severity.WARN:
        return "[WARN] "
    return "[ ok  ]"


def _fmt_age(age: timedelta | None) -> str:
    if age is None:
        return "n/a"
    total = age.total_seconds()
    return f"{total:.3f}s"
