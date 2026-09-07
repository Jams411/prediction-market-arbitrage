"""Synthetic builders for the M2.2 recorder tests. Not collected by pytest."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.domain import (
    Contract,
    Market,
    OrderBook,
    PriceLevel,
    Venue,
)
from prediction_market_arbitrage.livebook import FeedHealth, HealthStatus

KALSHI_VENUE = Venue(id="kalshi", name="Kalshi")
REC_TS = datetime(2026, 3, 1, 9, 30, 0, 446134, tzinfo=UTC)
REC_AT = datetime(2026, 3, 1, 9, 30, 1, tzinfo=UTC)

# A high-precision value that a fixed-scale DECIMAL column could not hold.
WIDE_DECIMAL = Decimal("0.123456789012345678901234567890")


def kalshi_contract(outcome: str = "YES", *, ticker: str = "RECORDER-TEST-T1") -> Contract:
    market = Market(
        venue=KALSHI_VENUE, id=ticker, title="synthetic recorder market", close_time=None
    )
    return Contract(market=market, id=f"{ticker}:{outcome}", outcome=outcome)


def order_book(
    *,
    bids: list[tuple[str, str]],
    asks: list[tuple[str, str]],
    timestamp: datetime = REC_TS,
    outcome: str = "YES",
) -> OrderBook:
    return OrderBook(
        contract=kalshi_contract(outcome),
        bids=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in bids),
        asks=tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in asks),
        timestamp=timestamp,
    )


def feed_health(
    *,
    status: HealthStatus = HealthStatus.HEALTHY,
    reason: str = "",
    as_of: datetime = REC_TS,
    last_update: datetime | None = REC_TS,
    last_sequence: int | None = 7,
) -> FeedHealth:
    return FeedHealth(
        status=status,
        reason=reason,
        as_of=as_of,
        last_update=last_update,
        last_sequence=last_sequence,
    )
