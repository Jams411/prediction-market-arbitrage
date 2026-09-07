"""Synthetic builders for the M2.5 risk-manager tests. Not collected by pytest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from arbitrage_support import EVAL_TIME, kalshi_book, make_record, polymarket_book

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    EngineConfig,
    FixedPerUnitFeeModel,
)
from prediction_market_arbitrage.arbitrage.engine import OpportunityEvaluation
from prediction_market_arbitrage.livebook import FeedHealth, HealthStatus
from prediction_market_arbitrage.paper_broker import LegRiskSnapshot, OrderRequest
from prediction_market_arbitrage.recorder import PositionRow

T0 = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
CONTRACT_ID = "RM-T1:YES"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def order(
    *,
    order_id: str = "o1",
    side: str = "buy",
    quantity: str = "10",
    limit_price: str | None = "0.50",
    contract_id: str = CONTRACT_ID,
    order_type: str = "limit",
) -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        venue="kalshi",
        contract_id=contract_id,
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        limit_price=None if order_type == "market" or limit_price is None else Decimal(limit_price),
    )


def position(
    contract_id: str = CONTRACT_ID,
    *,
    quantity: str = "0",
    avg_price: str = "0.45",
    as_of: datetime = T0,
) -> PositionRow:
    return PositionRow(
        venue="kalshi",
        contract_id=contract_id,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        as_of=as_of,
    )


def health(
    *,
    status: HealthStatus = HealthStatus.HEALTHY,
    reason: str = "",
    as_of: datetime = T0,
    last_update: datetime | None = T0,
    last_sequence: int | None = 5,
) -> FeedHealth:
    return FeedHealth(
        status=status,
        reason=reason,
        as_of=as_of,
        last_update=last_update,
        last_sequence=last_sequence,
    )


def leg_risk(
    *,
    unhedged_quantity: str = "5",
    both_terminal: bool = False,
    as_of: datetime = T0,
    a_id: str = "legA",
    b_id: str = "legB",
) -> LegRiskSnapshot:
    q = Decimal(unhedged_quantity)
    return LegRiskSnapshot(
        as_of=as_of,
        order_a_id=a_id,
        order_b_id=b_id,
        a_filled_quantity=abs(q),
        b_filled_quantity=Decimal(0),
        unhedged_quantity=q,
        a_average_price=Decimal("0.45"),
        b_average_price=Decimal(0),
        hedge_completion_price=Decimal("0.55"),
        unhedged_notional=abs(q) * Decimal("0.55"),
        both_terminal=both_terminal,
    )


def opportunity(*, net_edge_total: str, has_edge: bool = True) -> OpportunityEvaluation:
    """A real engine result with the edge fields coerced for the test.

    ``executable_quantity`` is 10, so ``net_edge_per_unit == net_edge_total / 10``.
    """
    engine = ArbitrageEngine(config=EngineConfig(fee_model=FixedPerUnitFeeModel(Decimal("0.01"))))
    base = engine.evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=Decimal("10"),
    )
    from dataclasses import replace

    return replace(
        base,
        net_edge=Decimal(net_edge_total),
        has_opportunity=has_edge,
        rejection_reason="" if has_edge else "synthetic: no edge",
    )
