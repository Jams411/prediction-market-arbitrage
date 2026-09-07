"""Build a deterministic, feature-rich M2.2 recording for the M3.3
paper-performance-report tests. Not collected by pytest.

Known answers (see ``test_perf_report.py``):
  - 5 opportunity evaluations: 3 positive-edge, 2 rejected
    (reasons "net edge <= 0" x1, "stale book" x1)
  - net_edge totals [2, 4, 1]; per-unit [0.2, 0.2, 0.1]; qty [10, 20, 10]
  - one depth-capped positive row
  - pair P1 has a 2-eval positive episode (duration 20s) then goes negative;
    pair P2 has a single positive observation (no duration)
  - 3 orders: 1 fully filled, 1 partially filled (4/10), 1 unfilled+rejected
  - 2 fills, both taker, fees 0.02 + 0.01
  - 2 order books with distinct depth
  - portfolio pnl series net = [0, 5, 2, 6.5]  -> peak 6.5, max drawdown 3
  - one 'contract'-scope pnl row that must be ignored for the portfolio report
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from arbitrage_support import kalshi_book, make_record, polymarket_book

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    EngineConfig,
    FixedPerUnitFeeModel,
)
from prediction_market_arbitrage.arbitrage.engine import OpportunityEvaluation
from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.recorder import (
    FillRow,
    OrderEventRow,
    PnlRow,
    PositionRow,
    Recorder,
)

SESSION_ID = "perf-report-test-session"
T0 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = Venue(id="kalshi", name="kalshi")


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _base_eval() -> OpportunityEvaluation:
    engine = ArbitrageEngine(
        config=EngineConfig(fee_model=FixedPerUnitFeeModel(Decimal("0.01")))
    )
    return engine.evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=T0,
        requested_quantity=Decimal("10"),
    )


def _eval(
    *,
    pair_id: str,
    eval_time: datetime,
    net_edge: str,
    qty: str,
    has_edge: bool,
    depth_capped: bool = False,
    rejection_reason: str = "",
) -> OpportunityEvaluation:
    return replace(
        _base_eval(),
        pair_id=pair_id,
        evaluation_time=eval_time,
        executable_quantity=Decimal(qty),
        depth_capped=depth_capped,
        net_edge=Decimal(net_edge),
        has_opportunity=has_edge,
        rejection_reason="" if has_edge else rejection_reason,
    )


def _book(
    asks: list[tuple[str, str]], bids: list[tuple[str, str]], ts: datetime
) -> OrderBook:
    market = Market(venue=_VENUE, id="PERF-T1", title="PERF-T1", close_time=None)
    contract = Contract(market=market, id="PERF-T1:YES", outcome="YES")
    return OrderBook(
        contract=contract,
        bids=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in bids),
        asks=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in asks),
        timestamp=ts,
    )


def build_perf_recording(database: str) -> str:
    """Write the known session to ``database``; return its ``session_id``."""
    rec = Recorder.open(database, session_id=SESSION_ID, opened_at=T0, label="perf")

    # -- opportunities -------------------------------------------------- #
    rec.record_opportunity(
        _eval(pair_id="P1", eval_time=at(10), net_edge="2", qty="10", has_edge=True),
        recorded_at=at(10),
    )
    rec.record_opportunity(
        _eval(
            pair_id="P1",
            eval_time=at(30),
            net_edge="4",
            qty="20",
            has_edge=True,
            depth_capped=True,
        ),
        recorded_at=at(30),
    )
    rec.record_opportunity(
        _eval(
            pair_id="P1",
            eval_time=at(40),
            net_edge="-1",
            qty="10",
            has_edge=False,
            rejection_reason="net edge <= 0",
        ),
        recorded_at=at(40),
    )
    rec.record_opportunity(
        _eval(
            pair_id="P2",
            eval_time=at(15),
            net_edge="0",
            qty="10",
            has_edge=False,
            rejection_reason="stale book",
        ),
        recorded_at=at(15),
    )
    rec.record_opportunity(
        _eval(pair_id="P2", eval_time=at(25), net_edge="1", qty="10", has_edge=True),
        recorded_at=at(25),
    )

    # -- orders + fills ---------------------------------------------- #
    _order(rec, "o-full", qty="10", statuses=["submitted", "filled"])
    rec.record_fill(
        FillRow(
            fill_id="f-full",
            order_id="o-full",
            venue="kalshi",
            contract_id="PERF-T1:YES",
            price=Decimal("0.41"),
            quantity=Decimal("10"),
            fee=Decimal("0.02"),
            filled_at=at(12),
            liquidity="taker",
        ),
        recorded_at=at(12),
    )
    _order(rec, "o-part", qty="10", statuses=["submitted", "partially_filled"])
    rec.record_fill(
        FillRow(
            fill_id="f-part",
            order_id="o-part",
            venue="kalshi",
            contract_id="PERF-T1:YES",
            price=Decimal("0.42"),
            quantity=Decimal("4"),
            fee=Decimal("0.01"),
            filled_at=at(22),
            liquidity="taker",
        ),
        recorded_at=at(22),
    )
    _order(rec, "o-none", qty="5", statuses=["submitted", "rejected"])

    # -- order books ----------------------------------------------- #
    rec.record_order_book(
        _book([("0.44", "10"), ("0.45", "5")], [("0.40", "20")], at(5)),
        recorded_at=at(5),
        source="rest_snapshot",
    )
    rec.record_order_book(
        _book([("0.46", "30")], [("0.39", "8"), ("0.38", "2")], at(35)),
        recorded_at=at(35),
        source="ws_delta",
    )

    # -- pnl ----------------------------------------------------- #
    for i, (r, u, f) in enumerate(
        [("0", "0", "0"), ("5", "0", "0"), ("5", "-3", "0"), ("8", "-1", "0.5")]
    ):
        rec.record_pnl(
            PnlRow(
                scope="portfolio",
                scope_id="acct",
                realized=Decimal(r),
                unrealized=Decimal(u),
                fees=Decimal(f),
                as_of=at(50 + i),
            ),
            recorded_at=at(50 + i),
        )
    rec.record_pnl(
        PnlRow(
            scope="contract",
            scope_id="PERF-T1:YES",
            realized=Decimal("99"),
            unrealized=Decimal("0"),
            fees=Decimal("0"),
            as_of=at(55),
        ),
        recorded_at=at(55),
    )
    rec.record_position(
        PositionRow(
            venue="kalshi",
            contract_id="PERF-T1:YES",
            quantity=Decimal("14"),
            avg_price=Decimal("0.414"),
            as_of=at(23),
        ),
        recorded_at=at(23),
    )

    rec.close()
    return SESSION_ID


def _order(rec: Recorder, order_id: str, *, qty: str, statuses: list[str]) -> None:
    for i, status in enumerate(statuses):
        rec.record_order_event(
            OrderEventRow(
                order_id=order_id,
                venue="kalshi",
                contract_id="PERF-T1:YES",
                side="buy",
                order_type="limit",
                quantity=Decimal(qty),
                status=status,
                event_time=at(10 + i),
                limit_price=Decimal("0.45"),
            ),
            recorded_at=at(10 + i),
        )
