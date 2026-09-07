"""Value objects for the deterministic paper-performance report (Milestone M3.3).

Every aggregate is exact :class:`~decimal.Decimal`. A metric that the recorded
session does not support is ``None`` (rendered "n/a"), never ``0`` — a real
``0`` count / value and "not recorded" are kept distinct. Nothing here reads
persistence or a wall-clock; it is a pure projection of what
:class:`~prediction_market_arbitrage.replay.ReplaySession` already yields.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

_TWO = Decimal(2)


@dataclass(frozen=True, slots=True)
class Stats:
    """Count + mean/median/min/max over a set of exact values. The four
    aggregates are ``None`` when ``count == 0`` (no data), never ``0``."""

    count: int
    mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None

    @classmethod
    def of(cls, values: Sequence[Decimal]) -> Stats:
        if not values:
            return cls(count=0, mean=None, median=None, minimum=None, maximum=None)
        ordered = sorted(values)
        n = len(ordered)
        total = sum(ordered, Decimal(0))
        mid = n // 2
        median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / _TWO
        return cls(
            count=n,
            mean=total / Decimal(n),
            median=median,
            minimum=ordered[0],
            maximum=ordered[-1],
        )


@dataclass(frozen=True, slots=True)
class OpportunityStats:
    """Opportunities observed vs rejected, edge, and depth signals."""

    observed: int
    positive_edge: int
    rejected: int
    rejection_reasons: tuple[tuple[str, int], ...]  # (reason, count), most common first
    net_edge_total: Stats  # over positive-edge rows
    net_edge_per_unit: Stats  # over positive-edge rows with executable_quantity > 0
    executable_quantity: Stats  # over positive-edge rows
    depth_capped_count: int  # positive-edge rows flagged depth_capped
    depth_capped_fraction: Decimal | None  # None when positive_edge == 0


@dataclass(frozen=True, slots=True)
class OpportunityDurationStats:
    """Derived, best-effort: an *episode* is a maximal run of consecutive
    positive-edge evaluations for one ``pair_id`` (ordered by evaluation time).
    Its duration is ``last_eval_time - first_eval_time``; a single-observation
    episode carries no duration information and is counted separately."""

    episodes: int
    episodes_with_duration: int  # episodes of >= 2 evaluations
    single_observation_episodes: int
    duration_seconds: Stats  # over episodes_with_duration


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Paper orders and fill / partial-fill outcomes, derived from recorded
    order events + fills (filled quantity vs the order's quantity)."""

    orders: int
    fully_filled: int
    partially_filled: int
    unfilled: int
    fill_rate: Decimal | None  # fully_filled / orders; None when orders == 0
    partial_fill_rate: Decimal | None  # partially_filled / orders
    filled_quantity_ratio: Decimal | None  # sum(filled_qty) / sum(ordered_qty)
    final_status_counts: tuple[tuple[str, int], ...]  # last event status per order
    fills: int
    fill_liquidity_counts: tuple[tuple[str, int], ...]
    fill_fees_total: Decimal | None  # None when there are no fills


@dataclass(frozen=True, slots=True)
class DepthStats:
    """Available-depth statistics from recorded order books (top-of-book and
    total resting size per book side). ``None`` fields mean no order books were
    recorded for the session."""

    order_books: int
    best_ask_size: Stats
    best_bid_size: Stats
    total_ask_size: Stats
    total_bid_size: Stats


@dataclass(frozen=True, slots=True)
class PnlStats:
    """Paper PnL and drawdown from the recorded ``pnl`` stream for one scope.

    ``net`` at each sample is ``realized + unrealized - fees``. ``max_drawdown``
    is the largest peak-to-trough decline of the net series (``>= 0``; ``0`` when
    the series only rises). All value fields are ``None`` when the scope has no
    recorded rows."""

    scope: str
    scope_id: str | None
    samples: int
    final_realized: Decimal | None
    final_unrealized: Decimal | None
    final_fees: Decimal | None
    final_net: Decimal | None
    peak_net: Decimal | None
    max_drawdown: Decimal | None


@dataclass(frozen=True, slots=True)
class LegRiskStats:
    """Leg-risk events are **not** persisted by the M2.2 recorder (no table),
    so this is always ``recorded = False`` — reported as unavailable, not as
    ``0`` events."""

    recorded: bool = False
    note: str = (
        "the M2.2 recorder has no leg-risk table; leg-risk events are not "
        "persisted and cannot be reported from a recording"
    )


@dataclass(frozen=True, slots=True)
class PerfReport:
    """The whole deterministic paper-performance picture for one recorded
    session. Read the fields directly or render with
    :func:`prediction_market_arbitrage.perf_report.render_text`."""

    session_id: str
    stream_counts: tuple[tuple[str, int], ...]
    opportunities: OpportunityStats
    opportunity_duration: OpportunityDurationStats
    trades: TradeStats
    depth: DepthStats
    pnl: PnlStats
    leg_risk: LegRiskStats
    unavailable: tuple[str, ...] = field(default_factory=tuple)
