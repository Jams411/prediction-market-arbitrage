"""Synthetic-only proof of the complete offline paper-arbitrage lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from prediction_market_arbitrage.arbitrage import ArbitrageEngine, EngineConfig
from prediction_market_arbitrage.arbitrage.fees import (
    KalshiTradingFeeModel,
    PolymarketUsTradingFeeModel,
    VenueFeeModel,
)
from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.livebook import FeedHealth, HealthStatus
from prediction_market_arbitrage.paper_arbitrage import PaperArbitrageOrchestrator
from prediction_market_arbitrage.paper_broker import PaperBroker, PaperBrokerConfig
from prediction_market_arbitrage.recorder import Recorder
from prediction_market_arbitrage.registry import REQUIRED_CHECKLIST_KEYS, load_registry_text
from prediction_market_arbitrage.replay import ReplaySession
from prediction_market_arbitrage.risk import RiskError, RiskLimits, RiskManager

D = Decimal
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
PAIR_ID = "synthetic-paper-pair"
LIFECYCLE_ID = "synthetic-lifecycle-001"
KALSHI_CONTRACT = "kalshi-synthetic-paper:YES"
POLY_CONTRACT = "polymarket-synthetic-paper:SHORT"


def _registry_toml() -> str:
    checklist = "\n".join(f"  {key} = true" for key in REQUIRED_CHECKLIST_KEYS)
    return f'''schema_version = 1
[[pair]]
pair_id = "{PAIR_ID}"
proposition = "synthetic proposition for deterministic paper testing only"
status = "VERIFIED"
relation = "COMPLEMENTARY"
settlement_notes = "synthetic complementary outcomes"
known_differences = []
known_differences_reviewed = true
reviewer = "synthetic-test"
verified_at = "2026-09-10T11:59:00Z"
live_use_eligible = false
blocking_reason = "synthetic test pair; never eligible for live use"
notes = "not real market evidence"
  [pair.kalshi]
  venue = "kalshi"
  market_id = "kalshi-synthetic-paper"
  outcome = "YES"
  sources = ["https://example.test/synthetic-kalshi-rules"]
  [pair.polymarket_us]
  venue = "polymarket_us"
  market_id = "polymarket-synthetic-paper"
  outcome = "SHORT"
  sources = ["https://example.test/synthetic-polymarket-rules"]
  [pair.checklist]
{checklist}
'''


def _book(venue_id: str, market_id: str, outcome: str, ask: str) -> OrderBook:
    venue = Venue(id=venue_id, name=venue_id)
    contract = Contract(
        market=Market(venue=venue, id=market_id, title="synthetic", close_time=None),
        id=f"{market_id}:{outcome}",
        outcome=outcome,
    )
    return OrderBook(
        contract=contract,
        bids=(PriceLevel(D("0.10"), D("5")),),
        asks=(PriceLevel(D(ask), D("5")),),
        timestamp=T0,
    )


def _components(database: str, *, max_order_size: str = "4"):  # type: ignore[no-untyped-def]
    registry = load_registry_text(_registry_toml(), source="synthetic-test.toml")
    fees = VenueFeeModel(
        {"kalshi": KalshiTradingFeeModel(), "polymarket_us": PolymarketUsTradingFeeModel()}
    )
    engine = ArbitrageEngine(
        EngineConfig(
            fee_model=fees,
            execution_buffer_per_unit=D("0.005"),
            slippage_reserve_per_unit=D("0.01"),
            max_quantity=D("4"),
            max_book_age=timedelta(seconds=1),
            max_cross_book_skew=timedelta(seconds=1),
            require_full_fill=True,
        )
    )
    risk = RiskManager(
        RiskLimits(
            max_position=D("4"),
            max_order_size=D(max_order_size),
            min_net_edge_per_unit=D("0.05"),
            max_data_age=timedelta(seconds=1),
        )
    )
    broker = PaperBroker(PaperBrokerConfig(fee_model=fees))
    recorder = Recorder.open(database, session_id="synthetic-session", opened_at=T0)
    return registry, engine, risk, broker, recorder


def _health() -> FeedHealth:
    return FeedHealth(
        status=HealthStatus.HEALTHY,
        reason="synthetic deterministic snapshot",
        as_of=T0,
        last_update=T0,
        last_sequence=1,
    )


def test_complete_synthetic_paper_lifecycle_is_recorded_and_reconciled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = str(tmp_path / "paper-lifecycle.duckdb")
    registry, engine, risk, broker, recorder = _components(database)
    assert registry.get(PAIR_ID) in registry.eligible()
    kalshi = _book("kalshi", "kalshi-synthetic-paper", "YES", "0.40")
    poly = _book("polymarket_us", "polymarket-synthetic-paper", "SHORT", "0.50")
    with recorder:
        result = PaperArbitrageOrchestrator(
            registry=registry, engine=engine, risk=risk, broker=broker, recorder=recorder
        ).run(
            lifecycle_id=LIFECYCLE_ID,
            pair_id=PAIR_ID,
            kalshi_book=kalshi,
            polymarket_us_book=poly,
            evaluation_time=T0,
            requested_quantity=D("4"),
            health=_health(),
        )

    evaluation = result.evaluation
    assert (
        evaluation.executable_quantity,
        evaluation.gross_total_cost,
        evaluation.fees,
        evaluation.execution_buffer,
        evaluation.slippage_reserve,
        evaluation.net_edge,
    ) == (D("4"), D("3.60"), D("0.13"), D("0.020"), D("0.04"), D("0.210"))
    assert evaluation.has_opportunity
    assert result.opportunity_risk.allowed and all(d.allowed for d in result.order_risks)
    assert [order.filled_quantity for order in result.orders] == [D("4"), D("4")]
    assert all(order.filled_quantity <= D("5") for order in result.orders)
    assert [(fill.price, fill.quantity) for order in result.orders for fill in order.fills] == [
        (D("0.40"), D("4")),
        (D("0.50"), D("4")),
    ]
    assert [(p.contract_id, p.quantity, p.avg_price) for p in result.positions] == [
        (KALSHI_CONTRACT, D("4"), D("0.40")),
        (POLY_CONTRACT, D("4"), D("0.50")),
    ]
    assert result.exposure == D("3.60")
    assert (result.pnl.realized, result.pnl.unrealized, result.pnl.fees) == (
        D("0"),
        D("0.40"),
        D("0.13"),
    )
    assert result.pnl.realized + result.pnl.unrealized - result.pnl.fees == D("0.27")

    with ReplaySession.open(database, session_id="synthetic-session") as replay:
        (lifecycle,) = tuple(replay.paper_lifecycles())
        (opportunity,) = tuple(replay.opportunities())
        decisions = tuple(replay.risk_decisions())
        orders = tuple(replay.order_events())
        fills = tuple(replay.fills())
        positions = tuple(replay.positions())
        (pnl,) = tuple(replay.pnl())
    assert lifecycle.pair_id == opportunity.pair_id == PAIR_ID
    assert lifecycle.opportunity_id == opportunity.row_id == result.opportunity_id
    assert {lifecycle.order_a_id, lifecycle.order_b_id} == {row.order_id for row in orders}
    assert len(decisions) == 3 and all(d.allowed for d in decisions)
    assert {d.order_id for d in decisions if d.stage == "order"} == {
        lifecycle.order_a_id,
        lifecycle.order_b_id,
    }
    filled_by_contract = {
        contract_id: sum((f.quantity for f in fills if f.contract_id == contract_id), D("0"))
        for contract_id in (KALSHI_CONTRACT, POLY_CONTRACT)
    }
    assert {(p.contract_id, p.quantity) for p in positions} == set(filled_by_contract.items())
    assert pnl.scope_id == PAIR_ID
    assert pnl.realized + pnl.unrealized - pnl.fees == D("0.27")


def test_order_risk_rejection_prevents_any_paper_submission(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry, engine, risk, broker, recorder = _components(
        str(tmp_path / "risk-reject.duckdb"), max_order_size="3"
    )
    with recorder, pytest.raises(RiskError, match="order quantity 4 exceeds max 3"):
        PaperArbitrageOrchestrator(
            registry=registry, engine=engine, risk=risk, broker=broker, recorder=recorder
        ).run(
            lifecycle_id=LIFECYCLE_ID,
            pair_id=PAIR_ID,
            kalshi_book=_book("kalshi", "kalshi-synthetic-paper", "YES", "0.40"),
            polymarket_us_book=_book(
                "polymarket_us", "polymarket-synthetic-paper", "SHORT", "0.50"
            ),
            evaluation_time=T0,
            requested_quantity=D("4"),
            health=_health(),
        )
    assert broker.orders() == ()
