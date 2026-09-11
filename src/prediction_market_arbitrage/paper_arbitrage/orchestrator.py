"""Small deterministic glue path for a verified, two-leg paper lifecycle.

This module is offline only: every dependency is an in-memory calculation,
paper broker, or local recorder. It performs no network or authentication I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from prediction_market_arbitrage.arbitrage import ArbitrageEngine, OpportunityEvaluation
from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.livebook import FeedHealth
from prediction_market_arbitrage.paper_broker import Order, OrderRequest, PaperBroker
from prediction_market_arbitrage.recorder import (
    OrderEventRow,
    PaperLifecycleRow,
    PnlRow,
    PositionRow,
    Recorder,
    RiskDecisionRow,
)
from prediction_market_arbitrage.registry import MarketPairRegistry
from prediction_market_arbitrage.risk import RiskDecision, RiskManager

_ZERO = Decimal(0)


class PaperArbitrageError(RuntimeError):
    """The offline lifecycle failed closed before producing complete evidence."""


@dataclass(frozen=True, slots=True)
class PaperArbitrageResult:
    lifecycle_id: str
    opportunity_id: int
    evaluation: OpportunityEvaluation
    opportunity_risk: RiskDecision
    order_risks: tuple[RiskDecision, RiskDecision]
    orders: tuple[Order, Order]
    positions: tuple[PositionRow, PositionRow]
    exposure: Decimal
    pnl: PnlRow


class PaperArbitrageOrchestrator:
    """Compose existing deterministic primitives for exactly one matched pair."""

    def __init__(
        self,
        *,
        registry: MarketPairRegistry,
        engine: ArbitrageEngine,
        risk: RiskManager,
        broker: PaperBroker,
        recorder: Recorder,
    ) -> None:
        self._registry = registry
        self._engine = engine
        self._risk = risk
        self._broker = broker
        self._recorder = recorder

    def run(
        self,
        *,
        lifecycle_id: str,
        pair_id: str,
        kalshi_book: OrderBook,
        polymarket_us_book: OrderBook,
        evaluation_time: datetime,
        requested_quantity: Decimal,
        health: FeedHealth | None = None,
    ) -> PaperArbitrageResult:
        """Evaluate, risk-gate, fill, account for, and record one paper pair."""
        self._recorder.record_order_book(
            kalshi_book, recorded_at=evaluation_time, source="synthetic"
        )
        self._recorder.record_order_book(
            polymarket_us_book, recorded_at=evaluation_time, source="synthetic"
        )
        evaluation = self._engine.evaluate_from_registry(
            self._registry,
            pair_id,
            kalshi_book,
            polymarket_us_book,
            evaluation_time=evaluation_time,
            requested_quantity=requested_quantity,
        )
        opportunity_id = self._recorder.record_opportunity(evaluation, recorded_at=evaluation_time)
        if not evaluation.has_opportunity:
            raise PaperArbitrageError(f"no opportunity: {evaluation.rejection_reason}")

        opportunity_risk = self._risk.evaluate_opportunity(
            evaluation, now=evaluation_time, health=health
        )
        self._record_risk(lifecycle_id, "opportunity", opportunity_risk, None)
        opportunity_risk.raise_if_rejected()

        requests = self._requests(lifecycle_id, evaluation)
        self._recorder.record_paper_lifecycle(
            PaperLifecycleRow(
                lifecycle_id=lifecycle_id,
                pair_id=pair_id,
                opportunity_id=opportunity_id,
                order_a_id=requests[0].order_id,
                order_b_id=requests[1].order_id,
                created_at=evaluation_time,
            ),
            recorded_at=evaluation_time,
        )
        for request in requests:
            self._recorder.record_order_event(
                self._order_row(request, "new", evaluation_time),
                recorded_at=evaluation_time,
            )

        positions: dict[str, PositionRow] = {}
        marks = {
            requests[0].contract_id: requests[0].limit_price,
            requests[1].contract_id: requests[1].limit_price,
        }
        order_risks = tuple(
            self._risk.evaluate_order(
                request,
                now=evaluation_time,
                positions=positions,
                marks={key: value for key, value in marks.items() if value is not None},
                opportunity=evaluation,
                health=health,
            )
            for request in requests
        )
        for request, decision in zip(requests, order_risks, strict=True):
            self._record_risk(lifecycle_id, "order", decision, request.order_id)
        for decision in order_risks:
            decision.raise_if_rejected()

        for request in requests:
            self._broker.submit(request, at=evaluation_time)
        self._broker.advance(
            at=evaluation_time,
            books={
                kalshi_book.contract.id: kalshi_book,
                polymarket_us_book.contract.id: polymarket_us_book,
            },
        )
        orders = (
            self._broker.order(requests[0].order_id),
            self._broker.order(requests[1].order_id),
        )
        for order in orders:
            for row in order.event_rows():
                self._recorder.record_order_event(row, recorded_at=row.event_time)
            for fill in order.fills:
                self._recorder.record_fill(fill.to_row(), recorded_at=fill.filled_at)

        resulting_positions = tuple(
            self._broker.position(request.contract_id, as_of=evaluation_time)
            for request in requests
        )
        if any(order.filled_quantity != evaluation.executable_quantity for order in orders):
            raise PaperArbitrageError("both paper legs must fill the evaluated quantity")
        for position in resulting_positions:
            self._recorder.record_position(position, recorded_at=evaluation_time)

        exposure = sum(
            (abs(position.quantity) * position.avg_price for position in resulting_positions),
            _ZERO,
        )
        acquisition_cost = sum(
            (fill.price * fill.quantity for order in orders for fill in order.fills), _ZERO
        )
        fees = sum((order.total_fees for order in orders), _ZERO)
        matched_quantity = min(position.quantity for position in resulting_positions)
        pnl = PnlRow(
            scope="pair",
            scope_id=pair_id,
            realized=_ZERO,
            unrealized=matched_quantity - acquisition_cost,
            fees=fees,
            as_of=evaluation_time,
        )
        self._recorder.record_pnl(pnl, recorded_at=evaluation_time)
        return PaperArbitrageResult(
            lifecycle_id=lifecycle_id,
            opportunity_id=opportunity_id,
            evaluation=evaluation,
            opportunity_risk=opportunity_risk,
            order_risks=(order_risks[0], order_risks[1]),
            orders=orders,
            positions=(resulting_positions[0], resulting_positions[1]),
            exposure=exposure,
            pnl=pnl,
        )

    def _record_risk(
        self,
        lifecycle_id: str,
        stage: str,
        decision: RiskDecision,
        order_id: str | None,
    ) -> None:
        self._recorder.record_risk_decision(
            RiskDecisionRow(
                lifecycle_id=lifecycle_id,
                stage=stage,
                order_id=order_id,
                allowed=decision.allowed,
                checks_run=decision.checks_run,
                reasons=decision.reasons,
                as_of=decision.as_of,
            ),
            recorded_at=decision.as_of,
        )

    @staticmethod
    def _requests(
        lifecycle_id: str, evaluation: OpportunityEvaluation
    ) -> tuple[OrderRequest, OrderRequest]:
        legs = (evaluation.leg_a, evaluation.leg_b)
        return tuple(
            OrderRequest(
                order_id=f"{lifecycle_id}:leg-{label}",
                venue=leg.venue,
                contract_id=leg.contract_id,
                side="buy",
                order_type="limit",
                quantity=evaluation.executable_quantity,
                limit_price=max(fill.price for fill in leg.fills),
            )
            for label, leg in zip(("a", "b"), legs, strict=True)
        )  # type: ignore[return-value]

    @staticmethod
    def _order_row(request: OrderRequest, status: str, at: datetime) -> OrderEventRow:
        return OrderEventRow(
            order_id=request.order_id,
            venue=request.venue,
            contract_id=request.contract_id,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            status=status,
            event_time=at,
            limit_price=request.limit_price,
        )
