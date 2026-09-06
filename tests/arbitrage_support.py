"""Synthetic builders for the arbitrage-engine tests (M1.5). Not collected by pytest.

Everything here is fake: obviously synthetic market ids, in-memory records that
bypass the registry file, and hand-built order books.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.domain import (
    Contract,
    Market,
    OrderBook,
    PriceLevel,
    Venue,
)
from prediction_market_arbitrage.registry import (
    REQUIRED_CHECKLIST_KEYS,
    MarketPairRecord,
    OutcomeRelation,
    PairStatus,
    VenueLeg,
)

KALSHI_VENUE = Venue(id="kalshi", name="Kalshi")
POLY_VENUE = Venue(id="polymarket_us", name="Polymarket US")
TS = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
EVAL_TIME = datetime(2026, 1, 2, 0, 1, tzinfo=UTC)

KALSHI_MARKET = "kalshi-test-market"
POLY_MARKET = "polymarket-test-market"


def _levels(pairs: Sequence[tuple[str, str]]) -> tuple[PriceLevel, ...]:
    return tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in pairs)


def make_record(
    *,
    pair_id: str = "pair-test",
    status: PairStatus = PairStatus.VERIFIED,
    relation: OutcomeRelation = OutcomeRelation.COMPLEMENTARY,
    kalshi_market: str = KALSHI_MARKET,
    kalshi_outcome: str = "YES",
    poly_market: str = POLY_MARKET,
    poly_outcome: str = "SHORT",
) -> MarketPairRecord:
    """A synthetic pair record built directly (bypasses the registry file)."""
    return MarketPairRecord(
        pair_id=pair_id,
        proposition="synthetic test proposition — not a real market",
        status=status,
        relation=relation,
        kalshi=VenueLeg(
            venue="kalshi",
            market_id=kalshi_market,
            outcome=kalshi_outcome,
            sources=("https://example.test/kalshi-rules",),
        ),
        polymarket_us=VenueLeg(
            venue="polymarket_us",
            market_id=poly_market,
            outcome=poly_outcome,
            sources=("https://example.test/polymarket-rules",),
        ),
        settlement_notes="synthetic",
        known_differences=(),
        known_differences_reviewed=True,
        checklist=tuple((key, True) for key in REQUIRED_CHECKLIST_KEYS),
        reviewer="tester",
        verified_at=datetime(2026, 1, 1, tzinfo=UTC),
        live_use_eligible=False,
        blocking_reason="synthetic test record — never live",
        notes="",
    )


def kalshi_book(
    asks: Sequence[tuple[str, str]],
    *,
    market: str = KALSHI_MARKET,
    outcome: str = "YES",
    contract_outcome: str | None = None,
    timestamp: datetime = TS,
) -> OrderBook:
    contract = Contract(
        market=Market(venue=KALSHI_VENUE, id=market, title="synthetic", close_time=None),
        id=f"{market}:{outcome}",
        outcome=contract_outcome if contract_outcome is not None else outcome,
    )
    return OrderBook(contract=contract, bids=(), asks=_levels(asks), timestamp=timestamp)


def polymarket_book(
    asks: Sequence[tuple[str, str]],
    *,
    market: str = POLY_MARKET,
    outcome: str = "SHORT",
    contract_outcome: str | None = None,
    timestamp: datetime = TS,
) -> OrderBook:
    contract = Contract(
        market=Market(venue=POLY_VENUE, id=market, title="synthetic", close_time=None),
        id=f"{market}:{outcome}",
        outcome=contract_outcome if contract_outcome is not None else outcome,
    )
    return OrderBook(contract=contract, bids=(), asks=_levels(asks), timestamp=timestamp)
