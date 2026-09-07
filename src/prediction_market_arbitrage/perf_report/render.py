"""Plain-text rendering of a :class:`PerfReport` (Milestone M3.3).

Deterministic. A ``None`` aggregate renders as ``n/a`` with the reason it is
missing — never as ``0``. A real ``0`` count / value renders as ``0``.
"""

from __future__ import annotations

from decimal import Decimal

from .models import DepthStats, PerfReport, Stats

_RULE = "=" * 72
_NA = "n/a"


def render_text(report: PerfReport) -> str:
    """Render ``report`` as a sectioned plain-text summary."""
    lines: list[str] = [
        _RULE,
        f"PAPER PERFORMANCE REPORT  —  session {report.session_id}",
        _RULE,
        "",
        "RECORDED STREAMS",
    ]
    for kind, count in report.stream_counts:
        lines.append(f"  {kind:<14} {count}")

    o = report.opportunities
    lines += [
        "",
        "OPPORTUNITIES",
        f"  observed:        {o.observed}",
        f"  positive edge:   {o.positive_edge}",
        f"  rejected:        {o.rejected}",
    ]
    if o.rejection_reasons:
        lines.append("  rejection reasons:")
        for reason, count in o.rejection_reasons:
            lines.append(f"    {count:>4}  {reason}")
    lines += [
        f"  net edge (total)    {_stats(o.net_edge_total)}",
        f"  net edge (per unit) {_stats(o.net_edge_per_unit)}",
        f"  executable qty      {_stats(o.executable_quantity)}",
        f"  depth-capped:        {o.depth_capped_count}"
        + (
            f"  ({_pct(o.depth_capped_fraction)} of positive-edge)"
            if o.depth_capped_fraction is not None
            else f"  ({_NA} — no positive-edge opportunities)"
        ),
    ]

    d = report.opportunity_duration
    lines += [
        "",
        "OPPORTUNITY DURATION  (derived: consecutive positive-edge evals per pair)",
        f"  episodes:                 {d.episodes}",
        f"  episodes with a duration: {d.episodes_with_duration}",
        f"  single-observation only:  {d.single_observation_episodes}",
        f"  duration seconds          {_stats(d.duration_seconds)}",
    ]

    t = report.trades
    lines += [
        "",
        "PAPER TRADES",
        f"  orders:            {t.orders}",
        f"  fully filled:      {t.fully_filled}",
        f"  partially filled:  {t.partially_filled}",
        f"  unfilled:          {t.unfilled}",
        f"  fill rate:         {_ratio(t.fill_rate)}",
        f"  partial-fill rate: {_ratio(t.partial_fill_rate)}",
        f"  filled qty ratio:  {_ratio(t.filled_quantity_ratio)}",
    ]
    if t.final_status_counts:
        lines.append("  final status:")
        for status, count in t.final_status_counts:
            lines.append(f"    {count:>4}  {status}")
    lines.append(f"  fills:             {t.fills}")
    if t.fill_liquidity_counts:
        lines.append(
            "  fill liquidity:    "
            + ", ".join(f"{liq}={count}" for liq, count in t.fill_liquidity_counts)
        )
    lines.append(
        f"  fill fees total:   {t.fill_fees_total if t.fill_fees_total is not None else _NA}"
    )

    lines += ["", "AVAILABLE DEPTH  (from recorded order books)"]
    lines += _depth_lines(report.depth)

    p = report.pnl
    scope = f"{p.scope}" + (f":{p.scope_id}" if p.scope_id else "")
    lines += ["", f"PAPER PnL / DRAWDOWN  (scope {scope})"]
    if p.samples == 0:
        lines.append(f"  {_NA} — no recorded pnl rows for this scope")
    else:
        lines += [
            f"  samples:        {p.samples}",
            f"  final realized: {p.final_realized}",
            f"  final unrealized: {p.final_unrealized}",
            f"  final fees:      {p.final_fees}",
            f"  final net:       {p.final_net}",
            f"  peak net:        {p.peak_net}",
            f"  max drawdown:    {p.max_drawdown}",
        ]

    lines += [
        "",
        "LEG RISK",
        f"  {_NA} — {report.leg_risk.note}",
    ]

    lines += ["", "UNAVAILABLE / NOT RECORDED"]
    if report.unavailable:
        lines += [f"  - {item}" for item in report.unavailable]
    else:
        lines.append("  none")

    lines.append(_RULE)
    return "\n".join(lines)


def _stats(s: Stats) -> str:
    if s.count == 0:
        return f"n={s.count}  (mean/median {_NA} — no data)"
    return (
        f"n={s.count}  mean={s.mean}  median={s.median}  "
        f"min={s.minimum}  max={s.maximum}"
    )


def _depth_lines(depth: DepthStats) -> list[str]:
    if depth.order_books == 0:
        return [f"  {_NA} — no order books recorded for this session"]
    return [
        f"  order books:     {depth.order_books}",
        f"  best ask size    {_stats(depth.best_ask_size)}",
        f"  best bid size    {_stats(depth.best_bid_size)}",
        f"  total ask size   {_stats(depth.total_ask_size)}",
        f"  total bid size   {_stats(depth.total_bid_size)}",
    ]


def _ratio(value: Decimal | None) -> str:
    return _NA if value is None else f"{value}"


def _pct(fraction: Decimal | None) -> str:
    if fraction is None:
        return _NA
    return f"{(fraction * 100).quantize(Decimal('0.1'))}%"
