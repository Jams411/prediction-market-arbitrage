"""Read-only value objects for the operational dashboard (Milestone M3.1).

Every field is a plain container derived from objects the earlier milestones
already produce (M1.4 registry, M1.5 opportunities, M2.1 feed health, M2.4
orders / fills / positions / leg risk, M2.5 risk snapshot). Nothing here holds
mutable state, opens I/O, reads a wall-clock, or submits an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum


class Severity(Enum):
    """How loudly a condition should be surfaced. ``ALERT`` means a human
    should look now; ``WARN`` is degraded-but-not-stopped; ``OK`` is nominal."""

    OK = "ok"
    WARN = "warn"
    ALERT = "alert"


@dataclass(frozen=True, slots=True)
class Alert:
    """One surfaced condition, already ranked by :class:`Severity`."""

    severity: Severity
    section: str
    message: str


@dataclass(frozen=True, slots=True)
class FeedView:
    """One live-book feed's health and derived WebSocket state."""

    venue: str
    contract_id: str
    status: str  # HealthStatus value
    ws_state: str  # connected | disconnected | resyncing | offline
    reason: str
    trading_enabled: bool
    last_update: datetime | None
    last_sequence: int | None
    data_age: timedelta | None
    max_staleness: timedelta
    stale: bool
    severity: Severity


@dataclass(frozen=True, slots=True)
class PairView:
    """One verified/curated market pair from the manual registry."""

    pair_id: str
    proposition: str
    status: str
    relation: str
    verified: bool
    kalshi_leg: str
    polymarket_us_leg: str


@dataclass(frozen=True, slots=True)
class OpportunityView:
    """One arbitrage-engine evaluation, with data-age staleness flagged."""

    pair_id: str
    relation: str
    has_opportunity: bool
    net_edge: Decimal
    net_edge_per_unit: Decimal
    executable_quantity: Decimal
    depth_capped: bool
    rejection_reason: str
    evaluation_time: datetime
    data_age: timedelta | None
    stale: bool


@dataclass(frozen=True, slots=True)
class OrderView:
    """One paper order's current lifecycle state."""

    order_id: str
    venue: str
    contract_id: str
    side: str
    order_type: str
    quantity: Decimal
    status: str
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal
    total_fees: Decimal
    terminal: bool
    reject_reason: str


@dataclass(frozen=True, slots=True)
class FillView:
    """One executed slice against a paper order."""

    fill_id: str
    order_id: str
    venue: str
    contract_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    liquidity: str
    filled_at: datetime


@dataclass(frozen=True, slots=True)
class PositionView:
    """One position snapshot plus its (best-effort) exposure valuation."""

    venue: str
    contract_id: str
    quantity: Decimal  # signed
    avg_price: Decimal
    mark: Decimal | None
    mark_is_cost_basis: bool
    exposure: Decimal | None
    as_of: datetime
    data_age: timedelta | None
    stale: bool


@dataclass(frozen=True, slots=True)
class PnlView:
    """One realized/unrealized PnL snapshot for a scope."""

    scope: str
    scope_id: str
    realized: Decimal
    unrealized: Decimal
    fees: Decimal
    net: Decimal
    as_of: datetime


@dataclass(frozen=True, slots=True)
class LegRiskView:
    """One measured one-legged exposure between two orders."""

    order_a_id: str
    order_b_id: str
    unhedged_quantity: Decimal
    unhedged_notional: Decimal | None
    both_terminal: bool
    as_of: datetime


@dataclass(frozen=True, slots=True)
class RiskView:
    """The risk manager's owned state at ``as_of``, plus the last verdict."""

    killed: bool
    kill_reason: str
    consecutive_errors: int
    daily_realized_pnl: Decimal
    daily_loss: Decimal
    unhedged_pairs: tuple[tuple[str, datetime], ...]
    last_decision_allowed: bool | None
    last_decision_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DashboardView:
    """The whole operational picture at one instant. Pure data — render it with
    :func:`prediction_market_arbitrage.dashboard.render_text` or read the fields
    directly."""

    as_of: datetime
    feeds: tuple[FeedView, ...]
    pairs: tuple[PairView, ...]
    opportunities: tuple[OpportunityView, ...]
    orders: tuple[OrderView, ...]
    fills: tuple[FillView, ...]
    positions: tuple[PositionView, ...]
    pnl: tuple[PnlView, ...]
    leg_risk: tuple[LegRiskView, ...]
    risk: RiskView
    alerts: tuple[Alert, ...]
    worst_data_age: timedelta | None

    @property
    def healthy(self) -> bool:
        """``True`` when nothing rose to :attr:`Severity.ALERT`."""
        return not any(a.severity is Severity.ALERT for a in self.alerts)
