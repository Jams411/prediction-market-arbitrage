"""Deterministic risk manager (Milestone M2.5).

Consumes the objects the earlier milestones already produce — an M1.5
:class:`OpportunityEvaluation`, an M2.1 :class:`FeedHealth`, M2.4
:class:`PaperBroker` positions (:class:`PositionRow`) and
:class:`LegRiskSnapshot` — plus a config-injected :class:`RiskLimits`, and
returns an explicit :class:`RiskDecision` (allow / reject + every failing
reason).

Fail-closed rule: a limit that is **set** but whose required input is **missing
or unhealthy** produces a rejection, never a skipped check. Pure and
deterministic: every method takes an injected timezone-aware ``now``; the only
mutable state (kill switch, error streak, daily-PnL ledger, unhedged timers)
lives in :class:`RiskState` and every mutation is timestamp-driven.

No strategy logic: the manager never decides *what* to trade, only vetoes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from prediction_market_arbitrage.arbitrage import OpportunityEvaluation
from prediction_market_arbitrage.livebook import FeedHealth
from prediction_market_arbitrage.paper_broker import LegRiskSnapshot, OrderRequest
from prediction_market_arbitrage.recorder import PositionRow

from .decision import RiskDecision
from .errors import RiskError
from .limits import RiskLimits
from .state import RiskState

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """Inspectable risk state at a point in time."""

    as_of: datetime
    killed: bool
    kill_reason: str
    consecutive_errors: int
    daily_realized_pnl: Decimal
    daily_loss: Decimal
    unhedged_pairs: tuple[tuple[str, datetime], ...]


class RiskManager:
    """Enforces :class:`RiskLimits`. One instance per trading process."""

    def __init__(self, limits: RiskLimits, state: RiskState | None = None) -> None:
        if not isinstance(limits, RiskLimits):
            raise RiskError("RiskManager requires a RiskLimits")
        self._limits = limits
        self._state = state if state is not None else RiskState()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def state(self) -> RiskState:
        return self._state

    # -- state control (delegates; every mutation is timestamp-driven) -- #

    def kill(self, reason: str) -> None:
        self._state.engage_kill_switch(reason)

    def resume(self) -> None:
        self._state.release_kill_switch()

    def record_error(self) -> int:
        return self._state.record_error()

    def record_success(self) -> None:
        self._state.record_success()

    def record_realized_pnl(self, amount: Decimal, *, at: datetime) -> None:
        self._state.record_realized_pnl(amount, at=at)

    def observe_leg_risk(
        self, leg: LegRiskSnapshot, *, now: datetime, pair_key: str | None = None
    ) -> None:
        """Update the unhedged timer for a leg pair without making an order
        decision."""
        _require_aware(now, name="now")
        key = pair_key or self._leg_key(leg)
        if self._is_unhedged(leg):
            self._state.note_unhedged(key, at=now)
        else:
            self._state.note_hedged(key)

    # -- decisions ------------------------------------------------- #

    def evaluate_opportunity(
        self,
        opportunity: OpportunityEvaluation | None,
        *,
        now: datetime,
        health: FeedHealth | None = None,
    ) -> RiskDecision:
        """Gate an opportunity before it is sized into an order — the
        session-wide checks plus edge / data-age."""
        _require_aware(now, name="now")
        reasons: list[str] = []
        checks: list[str] = []
        self._check_kill(reasons, checks)
        self._check_consecutive_errors(reasons, checks)
        self._check_daily_loss(reasons, checks, now)
        self._check_min_edge(reasons, checks, opportunity)
        self._check_feed_health(reasons, checks, health, now)
        return RiskDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            checks_run=tuple(checks),
            as_of=now,
        )

    def evaluate_order(
        self,
        request: OrderRequest,
        *,
        now: datetime,
        positions: Mapping[str, PositionRow] | None = None,
        marks: Mapping[str, Decimal] | None = None,
        opportunity: OpportunityEvaluation | None = None,
        health: FeedHealth | None = None,
        leg: LegRiskSnapshot | None = None,
        leg_pair_key: str | None = None,
    ) -> RiskDecision:
        """Allow or reject one order. Every configured limit is checked; missing
        or unhealthy required inputs fail closed."""
        if not isinstance(request, OrderRequest):
            raise RiskError("evaluate_order requires an OrderRequest")
        _require_aware(now, name="now")
        reasons: list[str] = []
        checks: list[str] = []

        self._check_kill(reasons, checks)
        self._check_consecutive_errors(reasons, checks)
        self._check_daily_loss(reasons, checks, now)
        self._check_order_size(reasons, checks, request)
        self._check_min_edge(reasons, checks, opportunity)
        self._check_feed_health(reasons, checks, health, now)
        projected = self._check_position(reasons, checks, request, positions)
        self._check_exposure(reasons, checks, request, positions, marks, projected)
        self._check_unhedged_time(reasons, checks, leg, leg_pair_key, now)

        return RiskDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            checks_run=tuple(checks),
            as_of=now,
        )

    def snapshot(self, *, now: datetime) -> RiskSnapshot:
        _require_aware(now, name="now")
        day = now.date()
        return RiskSnapshot(
            as_of=now,
            killed=self._state.killed,
            kill_reason=self._state.kill_reason,
            consecutive_errors=self._state.consecutive_errors,
            daily_realized_pnl=self._state.daily_realized_pnl(day),
            daily_loss=self._state.daily_loss(day),
            unhedged_pairs=self._state.unhedged_pairs(),
        )

    # -- individual checks ------------------------------------- #

    def _check_kill(self, reasons: list[str], checks: list[str]) -> None:
        checks.append("kill_switch")
        if self._state.killed:
            reasons.append(f"kill switch engaged: {self._state.kill_reason}")

    def _check_consecutive_errors(self, reasons: list[str], checks: list[str]) -> None:
        limit = self._limits.max_consecutive_errors
        if limit is None:
            return
        checks.append("consecutive_errors")
        count = self._state.consecutive_errors
        if count >= limit:
            reasons.append(f"{count} consecutive errors reached limit {limit}")

    def _check_daily_loss(self, reasons: list[str], checks: list[str], now: datetime) -> None:
        limit = self._limits.max_daily_loss
        if limit is None:
            return
        checks.append("max_daily_loss")
        loss = self._state.daily_loss(now.date())
        if loss >= limit:
            reasons.append(f"daily realized loss {loss} reached limit {limit}")

    def _check_order_size(
        self, reasons: list[str], checks: list[str], request: OrderRequest
    ) -> None:
        limit = self._limits.max_order_size
        if limit is None:
            return
        checks.append("max_order_size")
        if request.quantity > limit:
            reasons.append(f"order quantity {request.quantity} exceeds max {limit}")

    def _check_min_edge(
        self,
        reasons: list[str],
        checks: list[str],
        opportunity: OpportunityEvaluation | None,
    ) -> None:
        limit = self._limits.min_net_edge_per_unit
        if limit is None:
            return
        checks.append("min_net_edge_per_unit")
        if opportunity is None:
            reasons.append("min-net-edge limit set but no opportunity evaluation provided")
            return
        if not opportunity.has_opportunity:
            reasons.append(
                f"opportunity has no positive edge ({opportunity.rejection_reason})"
            )
            return
        edge = opportunity.net_edge_per_unit
        if edge < limit:
            reasons.append(f"net edge/unit {edge} below minimum {limit}")

    def _check_feed_health(
        self,
        reasons: list[str],
        checks: list[str],
        health: FeedHealth | None,
        now: datetime,
    ) -> None:
        require_age = self._limits.max_data_age is not None
        if not require_age and health is None:
            return
        checks.append("feed_health")
        if health is None:
            reasons.append("max-data-age limit set but no market-data health provided")
            return
        if not health.trading_enabled:
            reasons.append(f"feed not healthy: {health.status.value} ({health.reason})")
        if require_age:
            reference = health.last_update or health.as_of
            age = now - reference
            if age.total_seconds() < 0:
                reasons.append("market-data health timestamp is in the future")
            elif age > self._limits.max_data_age:  # type: ignore[operator]
                reasons.append(
                    f"market-data age {age} exceeds max {self._limits.max_data_age}"
                )

    def _check_position(
        self,
        reasons: list[str],
        checks: list[str],
        request: OrderRequest,
        positions: Mapping[str, PositionRow] | None,
    ) -> Decimal | None:
        limit = self._limits.max_position
        signed_now = self._current_signed(positions, request.contract_id)
        delta = request.quantity if request.side == "buy" else -request.quantity
        projected = None if signed_now is None else signed_now + delta
        if limit is None:
            return projected
        checks.append("max_position")
        if positions is None:
            reasons.append("max-position limit set but no positions provided")
            return None
        assert projected is not None
        if abs(projected) > limit:
            reasons.append(
                f"projected position {projected} for {request.contract_id} exceeds max {limit}"
            )
        return projected

    def _check_exposure(
        self,
        reasons: list[str],
        checks: list[str],
        request: OrderRequest,
        positions: Mapping[str, PositionRow] | None,
        marks: Mapping[str, Decimal] | None,
        projected_for_order_contract: Decimal | None,
    ) -> None:
        limit = self._limits.max_exposure
        if limit is None:
            return
        checks.append("max_exposure")
        if positions is None:
            reasons.append("max-exposure limit set but no positions provided")
            return

        contract_ids = set(positions) | {request.contract_id}
        total = _ZERO
        for contract_id in sorted(contract_ids):
            if contract_id == request.contract_id:
                quantity = (
                    projected_for_order_contract
                    if projected_for_order_contract is not None
                    else self._current_signed(positions, contract_id) or _ZERO
                )
            else:
                quantity = positions[contract_id].quantity
            mark = self._mark_for(contract_id, positions, marks, request)
            if mark is None:
                reasons.append(f"cannot value {contract_id} for exposure (no mark or avg price)")
                return
            total += abs(quantity) * mark
        if total > limit:
            reasons.append(f"projected exposure {total} exceeds max {limit}")

    def _check_unhedged_time(
        self,
        reasons: list[str],
        checks: list[str],
        leg: LegRiskSnapshot | None,
        leg_pair_key: str | None,
        now: datetime,
    ) -> None:
        limit = self._limits.max_unhedged_time
        if limit is None:
            return
        checks.append("max_unhedged_time")
        if leg is None:
            reasons.append("max-unhedged-time limit set but no leg-risk snapshot provided")
            return
        key = leg_pair_key or self._leg_key(leg)
        if not self._is_unhedged(leg):
            self._state.note_hedged(key)
            return
        since = self._state.note_unhedged(key, at=now)
        duration = now - since
        if duration > limit:
            reasons.append(f"leg pair {key} unhedged for {duration} exceeds max {limit}")

    # -- helpers ------------------------------------------------- #

    @staticmethod
    def _current_signed(
        positions: Mapping[str, PositionRow] | None, contract_id: str
    ) -> Decimal | None:
        if positions is None:
            return None
        row = positions.get(contract_id)
        return _ZERO if row is None else row.quantity

    @staticmethod
    def _mark_for(
        contract_id: str,
        positions: Mapping[str, PositionRow],
        marks: Mapping[str, Decimal] | None,
        request: OrderRequest,
    ) -> Decimal | None:
        if marks is not None and contract_id in marks:
            return marks[contract_id]
        row = positions.get(contract_id)
        if row is not None and row.avg_price > _ZERO:
            # Deterministic fallback approximation only (A-034): cost basis is
            # not a conservative bound and can understate exposure after an
            # adverse move. A live caller must pass current `marks`.
            return row.avg_price
        if contract_id == request.contract_id and request.limit_price is not None:
            return request.limit_price
        return None

    @staticmethod
    def _is_unhedged(leg: LegRiskSnapshot) -> bool:
        return leg.unhedged_quantity != _ZERO and not leg.both_terminal

    @staticmethod
    def _leg_key(leg: LegRiskSnapshot) -> str:
        return f"{leg.order_a_id}|{leg.order_b_id}"


def _require_aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RiskError(f"{name} must be a timezone-aware datetime")
    return value
