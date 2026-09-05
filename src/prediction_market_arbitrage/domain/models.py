"""Normalized, venue-neutral domain models (Milestone M1.1).

Scope: data containers and their construction-time invariants only. No arbitrage
arithmetic, execution, transport, or venue-specific fields. See ``docs/ROADMAP.md``
(M1.1) and ``docs/DECISIONS.md`` (D-005 Decimal arithmetic).

Design rules applied here:
- Every monetary value / price / quantity / edge is a :class:`decimal.Decimal`.
- ``float`` is never silently coerced; models require an explicit ``Decimal``.
- Timestamps must be timezone-aware.
- Models are frozen (immutable, hashable) and validate invariants in
  ``__post_init__``.
- Normalized probability-style prices live in the inclusive range ``[0, 1]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .validation import (
    DomainValidationError,
    as_decimal,
    require_aware,
    require_non_empty,
    require_positive,
    require_probability_price,
)


@dataclass(frozen=True, slots=True)
class Venue:
    """A trading venue (exchange). Identity is the stable ``id`` slug."""

    id: str
    name: str

    def __post_init__(self) -> None:
        require_non_empty(self.id, field="Venue.id")
        require_non_empty(self.name, field="Venue.name")


@dataclass(frozen=True, slots=True)
class Market:
    """A market on a venue that resolves to one of its contracts.

    ``close_time`` is optional; when present it must be timezone-aware.
    """

    venue: Venue
    id: str
    title: str
    close_time: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.venue, Venue):
            raise DomainValidationError("Market.venue: must be a Venue")
        require_non_empty(self.id, field="Market.id")
        require_non_empty(self.title, field="Market.title")
        if self.close_time is not None:
            require_aware(self.close_time, field="Market.close_time")


@dataclass(frozen=True, slots=True)
class Contract:
    """A single tradeable outcome within a market (e.g. a YES/NO leg).

    ``outcome`` is a free-form, venue-neutral label; no venue-specific encoding.
    """

    market: Market
    id: str
    outcome: str

    def __post_init__(self) -> None:
        if not isinstance(self.market, Market):
            raise DomainValidationError("Contract.market: must be a Market")
        require_non_empty(self.id, field="Contract.id")
        require_non_empty(self.outcome, field="Contract.outcome")

    @property
    def venue(self) -> Venue:
        """The venue this contract's market belongs to."""
        return self.market.venue


@dataclass(frozen=True, slots=True)
class PriceLevel:
    """One aggregated resting level: a normalized price and available quantity.

    ``price`` is a probability-style value in ``[0, 1]``. ``quantity`` is strictly
    positive; a zero-quantity level is not a level.
    """

    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        as_decimal(self.price, field="PriceLevel.price")
        as_decimal(self.quantity, field="PriceLevel.quantity")
        require_probability_price(self.price, field="PriceLevel.price")
        require_positive(self.quantity, field="PriceLevel.quantity")


@dataclass(frozen=True, slots=True)
class OrderBook:
    """A point-in-time normalized book for one contract.

    Invariants enforced at construction:
    - ``bids`` are ordered by strictly descending price (no duplicate prices).
    - ``asks`` are ordered by strictly ascending price (no duplicate prices).
    - the book is not crossed: when both sides are present,
      ``best_bid.price <= best_ask.price``. A locked book
      (``best_bid.price == best_ask.price``) is permitted as a valid transient
      state; only a truly crossed book (``best_bid.price > best_ask.price``) is
      rejected.
    - ``timestamp`` is timezone-aware.

    Executable-depth / fill-simulation logic is intentionally deferred to M1.5.
    """

    contract: Contract
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise DomainValidationError("OrderBook.contract: must be a Contract")
        _validate_side(self.bids, side="bids", descending=True)
        _validate_side(self.asks, side="asks", descending=False)
        require_aware(self.timestamp, field="OrderBook.timestamp")
        best_bid, best_ask = self.best_bid, self.best_ask
        if best_bid is not None and best_ask is not None and best_bid.price > best_ask.price:
            raise DomainValidationError(
                "OrderBook: crossed book "
                f"(best bid {best_bid.price} > best ask {best_ask.price})"
            )

    @property
    def best_bid(self) -> PriceLevel | None:
        """Highest bid, or ``None`` when there are no bids."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> PriceLevel | None:
        """Lowest ask, or ``None`` when there are no asks."""
        return self.asks[0] if self.asks else None


def _validate_side(levels: tuple[PriceLevel, ...], *, side: str, descending: bool) -> None:
    if not isinstance(levels, tuple):
        raise DomainValidationError(f"OrderBook.{side}: must be a tuple of PriceLevel")
    previous: Decimal | None = None
    for index, level in enumerate(levels):
        if not isinstance(level, PriceLevel):
            raise DomainValidationError(f"OrderBook.{side}[{index}]: must be a PriceLevel")
        if previous is not None:
            if level.price == previous:
                raise DomainValidationError(
                    f"OrderBook.{side}: duplicate price level {level.price}"
                )
            if descending and level.price > previous:
                raise DomainValidationError(
                    f"OrderBook.{side}: must be ordered by descending price"
                )
            if not descending and level.price < previous:
                raise DomainValidationError(
                    f"OrderBook.{side}: must be ordered by ascending price"
                )
        previous = level.price


@dataclass(frozen=True, slots=True)
class MarketPair:
    """A human-verified mapping between two contracts believed to be equivalent.

    Venue-neutral: the two sides may be cross-venue or same-market legs. The
    minimal invariant is that ``left`` and ``right`` are distinct contracts.
    Resolution-term equivalence is a human responsibility (D-006) recorded in
    ``note``.
    """

    id: str
    left: Contract
    right: Contract
    note: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.id, field="MarketPair.id")
        if not isinstance(self.left, Contract) or not isinstance(self.right, Contract):
            raise DomainValidationError("MarketPair.left/right: must be Contract instances")
        if self.left == self.right:
            raise DomainValidationError("MarketPair: left and right must be distinct contracts")


@dataclass(frozen=True, slots=True)
class Opportunity:
    """Normalized container for a strategy-emitted opportunity (no arithmetic).

    This is only the shape future strategy code (M1.5) fills in. ``quantity`` and
    ``edge`` are strictly positive normalized values; ``edge`` is a per-unit
    fraction. Computing ``edge`` is out of scope for M1.1.
    """

    id: str
    pair: MarketPair
    quantity: Decimal
    edge: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.id, field="Opportunity.id")
        if not isinstance(self.pair, MarketPair):
            raise DomainValidationError("Opportunity.pair: must be a MarketPair")
        as_decimal(self.quantity, field="Opportunity.quantity")
        as_decimal(self.edge, field="Opportunity.edge")
        require_positive(self.quantity, field="Opportunity.quantity")
        require_positive(self.edge, field="Opportunity.edge")
        require_aware(self.timestamp, field="Opportunity.timestamp")
