"""Synthetic builders for the M2.4 paper-broker tests. Not collected by pytest."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.paper_broker import OrderRequest

VENUE = Venue(id="kalshi", name="kalshi")
T0 = datetime(2026, 3, 2, 15, 0, 0, tzinfo=UTC)
CONTRACT_ID = "PB-T1:YES"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def contract(ticker: str = "PB-T1", outcome: str = "YES") -> Contract:
    market = Market(venue=VENUE, id=ticker, title=ticker, close_time=None)
    return Contract(market=market, id=f"{ticker}:{outcome}", outcome=outcome)


def book(
    *,
    bids: Sequence[tuple[str, str]] = (),
    asks: Sequence[tuple[str, str]] = (),
    timestamp: datetime,
    ticker: str = "PB-T1",
    outcome: str = "YES",
) -> OrderBook:
    return OrderBook(
        contract=contract(ticker, outcome),
        bids=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in bids),
        asks=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in asks),
        timestamp=timestamp,
    )


def request(
    order_id: str,
    *,
    side: str = "buy",
    order_type: str = "limit",
    quantity: str = "100",
    limit_price: str | None = "0.50",
    immediate_or_cancel: bool = False,
    contract_id: str = CONTRACT_ID,
    venue: str = "kalshi",
) -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        venue=venue,
        contract_id=contract_id,
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        limit_price=(
            None if (order_type == "market" or limit_price is None) else Decimal(limit_price)
        ),
        immediate_or_cancel=immediate_or_cancel,
    )
