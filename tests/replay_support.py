"""Build a deterministic M2.2 recording for the replay tests. Not collected by pytest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from arbitrage_support import EVAL_TIME, kalshi_book, make_record, polymarket_book

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    EngineConfig,
    FixedPerUnitFeeModel,
)
from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.livebook import FeedHealth, HealthStatus
from prediction_market_arbitrage.recorder import (
    FillRow,
    OrderEventRow,
    PnlRow,
    PositionRow,
    Recorder,
)

SESSION_ID = "replay-test-session"
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
WIDE = Decimal("0.123456789012345678901234567890")

_VENUE = Venue(id="kalshi", name="kalshi")


def _contract(outcome: str = "YES") -> Contract:
    market = Market(venue=_VENUE, id="REPLAY-T1", title="REPLAY-T1", close_time=None)
    return Contract(market=market, id=f"REPLAY-T1:{outcome}", outcome=outcome)


def _book(bids: list[tuple[str, str]], asks: list[tuple[str, str]], ts: datetime) -> OrderBook:
    return OrderBook(
        contract=_contract(),
        bids=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in bids),
        asks=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in asks),
        timestamp=ts,
    )


def build_recording(database: str) -> str:
    """Write one known session to ``database`` and return its ``session_id``.

    Deterministic: fixed inputs, injected timestamps, single-threaded. Two calls
    against fresh databases produce identical rows.
    """
    rec = Recorder.open(database, session_id=SESSION_ID, opened_at=T0, label="replay")

    rec.record_order_book(
        _book(
            [("0.40", "100"), ("0.38", str(WIDE))],
            [("0.44", "70.5")],
            T0 + timedelta(seconds=1),
        ),
        recorded_at=T0 + timedelta(seconds=1),
        source="rest_snapshot",
    )
    rec.record_order_book(
        _book([("0.41", "120")], [("0.45", "60")], T0 + timedelta(seconds=3)),
        recorded_at=T0 + timedelta(seconds=3),
        source="ws_delta",
    )

    engine = ArbitrageEngine(config=EngineConfig(fee_model=FixedPerUnitFeeModel(Decimal("0.01"))))
    evaluation = engine.evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=Decimal("10"),
    )
    rec.record_opportunity(evaluation, recorded_at=T0 + timedelta(seconds=2))

    rec.record_order_event(
        OrderEventRow(
            order_id="ord-1",
            venue="kalshi",
            contract_id="REPLAY-T1:YES",
            side="buy",
            order_type="limit",
            quantity=Decimal("10"),
            status="submitted",
            event_time=T0 + timedelta(seconds=2),
            limit_price=Decimal("0.41"),
        ),
        recorded_at=T0 + timedelta(seconds=2),
    )
    rec.record_fill(
        FillRow(
            fill_id="fill-1",
            order_id="ord-1",
            venue="kalshi",
            contract_id="REPLAY-T1:YES",
            price=Decimal("0.41"),
            quantity=Decimal("4"),
            fee=Decimal("0.0175"),
            filled_at=T0 + timedelta(seconds=4),
            liquidity="taker",
        ),
        recorded_at=T0 + timedelta(seconds=4),
    )
    rec.record_position(
        PositionRow(
            venue="kalshi",
            contract_id="REPLAY-T1:YES",
            quantity=Decimal("4"),
            avg_price=Decimal("0.41"),
            as_of=T0 + timedelta(seconds=4),
        ),
        recorded_at=T0 + timedelta(seconds=4),
    )
    rec.record_pnl(
        PnlRow(
            scope="portfolio",
            scope_id="all",
            realized=Decimal("0"),
            unrealized=Decimal("-0.04"),
            fees=Decimal("0.0175"),
            as_of=T0 + timedelta(seconds=5),
        ),
        recorded_at=T0 + timedelta(seconds=5),
    )

    rec.record_health_event(
        FeedHealth(
            status=HealthStatus.HEALTHY,
            reason="",
            as_of=T0 + timedelta(seconds=1),
            last_update=T0 + timedelta(seconds=1),
            last_sequence=7,
        ),
        venue="kalshi",
        contract_id="REPLAY-T1:YES",
        recorded_at=T0 + timedelta(seconds=1),
    )
    rec.record_health_event(
        FeedHealth(
            status=HealthStatus.DISCONNECTED,
            reason="socket disconnected",
            as_of=T0 + timedelta(seconds=6),
            last_update=None,
            last_sequence=None,
        ),
        venue="kalshi",
        contract_id="REPLAY-T1:YES",
        recorded_at=T0 + timedelta(seconds=6),
    )

    rec.close()
    return SESSION_ID
