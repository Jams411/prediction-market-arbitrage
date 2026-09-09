"""Assemble a :class:`PerfReport` from one recorded paper session (Milestone M3.3).

Read-only and deterministic: the only input is a
:class:`~prediction_market_arbitrage.replay.ReplaySession` (itself a read-only
view of an M2.2 recording). No wall-clock, no persistence write, no order
submission. A metric the recording cannot support is reported as ``None`` and
listed in :attr:`PerfReport.unavailable` — never silently as ``0``.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from prediction_market_arbitrage.recorder.models import PNL_SCOPES
from prediction_market_arbitrage.replay import (
    RecordedFill,
    RecordedLegRiskEvent,
    RecordedOpportunity,
    RecordedOrderBook,
    RecordedOrderEvent,
    RecordedPnl,
    ReplaySession,
)

from .errors import PerfReportError
from .models import (
    DepthStats,
    LegRiskStats,
    OpportunityDurationStats,
    OpportunityStats,
    PerfReport,
    PnlStats,
    Stats,
    TradeStats,
)

_ZERO = Decimal(0)
_MICRO = timedelta(microseconds=1)


def build_report(
    session: ReplaySession,
    *,
    pnl_scope: str = "portfolio",
    pnl_scope_id: str | None = None,
) -> PerfReport:
    """Compute the paper-performance report for ``session``."""
    if pnl_scope not in PNL_SCOPES:
        raise PerfReportError(
            f"pnl_scope {pnl_scope!r} must be one of {sorted(PNL_SCOPES)}"
        )

    opportunities = list(session.opportunities())
    order_events = list(session.order_events())
    fills = list(session.fills())
    order_books = list(session.order_books())
    pnl_rows = list(session.pnl())

    opp_stats = _opportunity_stats(opportunities)
    duration_stats = _duration_stats(opportunities)
    trade_stats = _trade_stats(order_events, fills)
    depth_stats = _depth_stats(order_books)
    pnl_stats = _pnl_stats(pnl_rows, pnl_scope, pnl_scope_id)

    unavailable: list[str] = []
    if session.has_leg_risk_stream():
        leg_risk_stats = _leg_risk_stats(list(session.leg_risk_events()))
    else:
        leg_risk_stats = LegRiskStats(
            note="this recording's database predates the leg_risk_events table"
        )
        unavailable.append(
            "leg-risk events (recording predates the leg_risk_events table)"
        )
    if opp_stats.positive_edge == 0:
        unavailable.append("mean/median net edge (no positive-edge opportunities recorded)")
    if duration_stats.episodes_with_duration == 0:
        unavailable.append("opportunity duration (no multi-evaluation episodes recorded)")
    if depth_stats.order_books == 0:
        unavailable.append("depth statistics (no order books recorded)")
    if pnl_stats.samples == 0:
        unavailable.append(f"paper PnL / drawdown (scope {pnl_scope!r} has no recorded rows)")

    return PerfReport(
        session_id=session.session_id,
        stream_counts=tuple(session.counts().items()),
        opportunities=opp_stats,
        opportunity_duration=duration_stats,
        trades=trade_stats,
        depth=depth_stats,
        pnl=pnl_stats,
        leg_risk=leg_risk_stats,
        unavailable=tuple(unavailable),
    )


# --------------------------------------------------------------------------- #
# Leg-risk events: recorder-backed one-legged exposure
# --------------------------------------------------------------------------- #


def _leg_risk_stats(events: list[RecordedLegRiskEvent]) -> LegRiskStats:
    """Deterministic aggregation of recorded one-legged-exposure events. A
    recording with the table but no rows returns ``recorded=True, events=0``
    (a real zero — both legs always filled)."""
    pairs = {(e.order_a_id, e.order_b_id) for e in events}
    abs_unhedged = [abs(e.unhedged_quantity) for e in events]
    notionals = [e.unhedged_notional for e in events if e.unhedged_notional is not None]
    return LegRiskStats(
        recorded=True,
        events=len(events),
        temporary_events=sum(1 for e in events if e.temporary),
        unresolved_events=sum(1 for e in events if e.unresolved),
        order_pairs_affected=len(pairs),
        max_abs_unhedged_quantity=max(abs_unhedged) if abs_unhedged else None,
        unhedged_notional=Stats.of(notionals),
        note="",
    )


# --------------------------------------------------------------------------- #
# Opportunities: observed vs rejected, edge, depth signal
# --------------------------------------------------------------------------- #


def _opportunity_stats(rows: list[RecordedOpportunity]) -> OpportunityStats:
    positive = [r for r in rows if r.has_opportunity]
    rejected = [r for r in rows if not r.has_opportunity]

    reasons = Counter(r.rejection_reason or "(unspecified)" for r in rejected)
    ranked = tuple(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))

    depth_capped = sum(1 for r in positive if r.depth_capped)
    fraction = (
        Decimal(depth_capped) / Decimal(len(positive)) if positive else None
    )

    return OpportunityStats(
        observed=len(rows),
        positive_edge=len(positive),
        rejected=len(rejected),
        rejection_reasons=ranked,
        net_edge_total=Stats.of([r.net_edge for r in positive]),
        net_edge_per_unit=Stats.of(
            [r.net_edge / r.executable_quantity for r in positive if r.executable_quantity > _ZERO]
        ),
        executable_quantity=Stats.of([r.executable_quantity for r in positive]),
        depth_capped_count=depth_capped,
        depth_capped_fraction=fraction,
    )


def _duration_stats(rows: list[RecordedOpportunity]) -> OpportunityDurationStats:
    """Group each ``pair_id``'s evaluations (time-ordered) into maximal runs of
    consecutive positive-edge rows; a run of >= 2 rows yields a duration."""
    by_pair: dict[str, list[RecordedOpportunity]] = {}
    for r in rows:
        by_pair.setdefault(r.pair_id, []).append(r)

    episodes = 0
    with_duration = 0
    single = 0
    durations: list[Decimal] = []

    for pair_rows in by_pair.values():
        ordered = sorted(pair_rows, key=lambda r: (r.evaluation_time, r.row_id))
        run: list[RecordedOpportunity] = []
        for r in ordered:
            if r.has_opportunity:
                run.append(r)
                continue
            if run:
                episodes += 1
                _close_run(run, durations)
                with_duration, single = _tally(run, with_duration, single)
                run = []
        if run:
            episodes += 1
            _close_run(run, durations)
            with_duration, single = _tally(run, with_duration, single)

    return OpportunityDurationStats(
        episodes=episodes,
        episodes_with_duration=with_duration,
        single_observation_episodes=single,
        duration_seconds=Stats.of(durations),
    )


def _close_run(run: list[RecordedOpportunity], durations: list[Decimal]) -> None:
    if len(run) >= 2:
        span = run[-1].evaluation_time - run[0].evaluation_time
        durations.append(Decimal(span // _MICRO) / Decimal(1_000_000))


def _tally(run: list[RecordedOpportunity], with_duration: int, single: int) -> tuple[int, int]:
    if len(run) >= 2:
        return with_duration + 1, single
    return with_duration, single + 1


# --------------------------------------------------------------------------- #
# Trades: fill / partial-fill outcomes
# --------------------------------------------------------------------------- #


def _trade_stats(
    events: list[RecordedOrderEvent], fills: list[RecordedFill]
) -> TradeStats:
    filled_by_order: dict[str, Decimal] = {}
    for f in fills:
        filled_by_order[f.order_id] = filled_by_order.get(f.order_id, _ZERO) + f.quantity

    ordered_qty: dict[str, Decimal] = {}
    final_status: dict[str, str] = {}
    final_row: dict[str, int] = {}
    for e in events:
        ordered_qty.setdefault(e.order_id, e.quantity)
        if e.row_id >= final_row.get(e.order_id, -1):
            final_row[e.order_id] = e.row_id
            final_status[e.order_id] = e.status

    orders = list(ordered_qty)
    fully = partial = unfilled = 0
    total_ordered = _ZERO
    total_filled = _ZERO
    for oid in orders:
        want = ordered_qty[oid]
        got = filled_by_order.get(oid, _ZERO)
        total_ordered += want
        total_filled += got
        if want > _ZERO and got >= want:
            fully += 1
        elif got > _ZERO:
            partial += 1
        else:
            unfilled += 1

    n = len(orders)
    return TradeStats(
        orders=n,
        fully_filled=fully,
        partially_filled=partial,
        unfilled=unfilled,
        fill_rate=Decimal(fully) / Decimal(n) if n else None,
        partial_fill_rate=Decimal(partial) / Decimal(n) if n else None,
        filled_quantity_ratio=(
            total_filled / total_ordered if total_ordered > _ZERO else None
        ),
        final_status_counts=_ranked(Counter(final_status.values())),
        fills=len(fills),
        fill_liquidity_counts=_ranked(Counter(f.liquidity for f in fills)),
        fill_fees_total=sum((f.fee for f in fills), _ZERO) if fills else None,
    )


# --------------------------------------------------------------------------- #
# Depth: from recorded order books
# --------------------------------------------------------------------------- #


def _depth_stats(books: list[RecordedOrderBook]) -> DepthStats:
    best_ask: list[Decimal] = []
    best_bid: list[Decimal] = []
    total_ask: list[Decimal] = []
    total_bid: list[Decimal] = []
    for rb in books:
        asks = rb.book.asks
        bids = rb.book.bids
        best_ask.append(asks[0].quantity if asks else _ZERO)
        best_bid.append(bids[0].quantity if bids else _ZERO)
        total_ask.append(sum((lvl.quantity for lvl in asks), _ZERO))
        total_bid.append(sum((lvl.quantity for lvl in bids), _ZERO))
    return DepthStats(
        order_books=len(books),
        best_ask_size=Stats.of(best_ask),
        best_bid_size=Stats.of(best_bid),
        total_ask_size=Stats.of(total_ask),
        total_bid_size=Stats.of(total_bid),
    )


# --------------------------------------------------------------------------- #
# PnL + drawdown
# --------------------------------------------------------------------------- #


def _pnl_stats(
    rows: list[RecordedPnl], scope: str, scope_id: str | None
) -> PnlStats:
    matched = [
        r for r in rows if r.scope == scope and (scope_id is None or r.scope_id == scope_id)
    ]
    if not matched:
        return PnlStats(
            scope=scope,
            scope_id=scope_id,
            samples=0,
            final_realized=None,
            final_unrealized=None,
            final_fees=None,
            final_net=None,
            peak_net=None,
            max_drawdown=None,
        )

    net_series = [r.realized + r.unrealized - r.fees for r in matched]
    peak = net_series[0]
    max_dd = _ZERO
    for value in net_series:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)

    distinct_ids = {r.scope_id for r in matched}
    last = matched[-1]
    return PnlStats(
        scope=scope,
        scope_id=next(iter(distinct_ids)) if len(distinct_ids) == 1 else None,
        samples=len(matched),
        final_realized=last.realized,
        final_unrealized=last.unrealized,
        final_fees=last.fees,
        final_net=last.realized + last.unrealized - last.fees,
        peak_net=max(net_series),
        max_drawdown=max_dd,
    )


def _ranked(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
