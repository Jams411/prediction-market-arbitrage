"""Config-injected risk limits (Milestone M2.5).

Every limit is optional (``None`` disables that check) and Decimal- or
time-based. A limit that is **set** but whose required input is **absent** makes
the risk manager fail closed (reject), never skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .errors import RiskError

_ZERO = Decimal(0)


def _pos_decimal(value: Decimal | None, *, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise RiskError(f"{name} must be a finite Decimal or None")
    if value <= _ZERO:
        raise RiskError(f"{name} must be > 0")


def _nonneg_decimal(value: Decimal | None, *, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise RiskError(f"{name} must be a finite Decimal or None")
    if value < _ZERO:
        raise RiskError(f"{name} must be >= 0")


def _pos_timedelta(value: timedelta | None, *, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise RiskError(f"{name} must be a positive timedelta or None")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """All limits the M2.5 risk manager enforces. ``None`` disables a check."""

    #: Max absolute signed position per contract (quantity units).
    max_position: Decimal | None = None
    #: Max portfolio exposure = sum over contracts of ``|position| * mark``.
    max_exposure: Decimal | None = None
    #: Max quantity on a single order.
    max_order_size: Decimal | None = None
    #: Minimum required ``OpportunityEvaluation.net_edge_per_unit``.
    min_net_edge_per_unit: Decimal | None = None
    #: Max age of the market-data health / book feeding the decision.
    max_data_age: timedelta | None = None
    #: Max wall time a leg pair may remain unhedged before new orders are blocked.
    max_unhedged_time: timedelta | None = None
    #: Block once this many consecutive errors have been recorded.
    max_consecutive_errors: int | None = None
    #: Block once realized loss for the current UTC day reaches this magnitude.
    max_daily_loss: Decimal | None = None

    def __post_init__(self) -> None:
        _pos_decimal(self.max_position, name="RiskLimits.max_position")
        _pos_decimal(self.max_exposure, name="RiskLimits.max_exposure")
        _pos_decimal(self.max_order_size, name="RiskLimits.max_order_size")
        _nonneg_decimal(self.min_net_edge_per_unit, name="RiskLimits.min_net_edge_per_unit")
        _pos_timedelta(self.max_data_age, name="RiskLimits.max_data_age")
        _pos_timedelta(self.max_unhedged_time, name="RiskLimits.max_unhedged_time")
        _pos_decimal(self.max_daily_loss, name="RiskLimits.max_daily_loss")
        if self.max_consecutive_errors is not None:
            if (
                isinstance(self.max_consecutive_errors, bool)
                or not isinstance(self.max_consecutive_errors, int)
                or self.max_consecutive_errors < 1
            ):
                raise RiskError("RiskLimits.max_consecutive_errors must be an int >= 1 or None")
