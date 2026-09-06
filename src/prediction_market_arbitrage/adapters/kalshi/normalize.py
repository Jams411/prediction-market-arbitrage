"""Pure functions that map Kalshi JSON payloads to venue-neutral domain models.

No I/O here. Every monetary/price/size string is converted through
:func:`prediction_market_arbitrage.domain.to_decimal` (explicit Decimal, never
``float``). Timestamps are parsed as timezone-aware ``datetime``.

Order-book mapping (see ``docs/API_SOURCES.md`` for the evidence trail):

Kalshi's ``/markets/{ticker}/orderbook`` returns only *bids*, in
``orderbook_fp.yes_dollars`` and ``orderbook_fp.no_dollars``. Each entry is
``[price_dollars_str, count_str]``, listed in **ascending** price order, so the
best (highest) bid is the **last** element.

For a binary market the two sides are complementary and sum to $1, so an ask on
one side is implied by a bid on the other:

    YES ask price  == 1 - (NO bid price)      NO ask price == 1 - (YES bid price)
    (ask size       == the corresponding bid's size)

Worked example (from ``tests/fixtures/kalshi/orderbook.json``):
    best YES bid = 0.2000  -> NO  book best ask = 1 - 0.2000 = 0.8000
    best NO  bid = 0.7900  -> YES book best ask = 1 - 0.7900 = 0.2100
which matches the same market's ``yes_ask_dollars`` / ``no_ask_dollars``.

So each normalized :class:`~prediction_market_arbitrage.domain.OrderBook`:
    YES book: bids = YES bids (desc);  asks = 1 - NO bids  (asc)
    NO  book: bids = NO bids  (desc);  asks = 1 - YES bids (asc)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from prediction_market_arbitrage.domain import (
    Contract,
    DomainValidationError,
    Market,
    OrderBook,
    PriceLevel,
    Venue,
    to_decimal,
)

from .errors import KalshiPayloadError

KALSHI_VENUE = Venue(id="kalshi", name="Kalshi")
_ONE = Decimal(1)
_BINARY_MARKET_TYPE = "binary"


@dataclass(frozen=True, slots=True)
class MarketPage:
    """One page of ``GET /markets`` results."""

    markets: tuple[Market, ...]
    cursor: str | None


@dataclass(frozen=True, slots=True)
class KalshiOrderBooks:
    """The YES and NO normalized books derived from one Kalshi orderbook payload."""

    yes: OrderBook
    no: OrderBook


# --------------------------------------------------------------------------- #
# Markets
# --------------------------------------------------------------------------- #


def parse_market(payload: Mapping[str, object]) -> Market:
    """Normalize one Kalshi ``market`` object into a :class:`Market`."""
    ticker = _require_str(payload, "ticker", ctx="market")
    title = _require_str(payload, "title", ctx="market")
    market_type = _require_str(payload, "market_type", ctx=f"market {ticker}")
    if market_type != _BINARY_MARKET_TYPE:
        raise KalshiPayloadError(
            f"market {ticker}: unsupported market_type {market_type!r}; "
            f"only {_BINARY_MARKET_TYPE!r} is normalized in M1.2"
        )
    close_time = _parse_timestamp(
        _require_str(payload, "close_time", ctx=f"market {ticker}"),
        ctx=f"market {ticker}.close_time",
    )
    try:
        return Market(venue=KALSHI_VENUE, id=ticker, title=title, close_time=close_time)
    except DomainValidationError as exc:  # pragma: no cover - guarded by checks above
        raise KalshiPayloadError(f"market {ticker}: failed domain validation: {exc}") from exc


def parse_market_page(payload: Mapping[str, object]) -> MarketPage:
    """Normalize a ``GET /markets`` response into a :class:`MarketPage`."""
    raw_markets = payload.get("markets")
    if not isinstance(raw_markets, list):
        raise KalshiPayloadError("markets response: missing or non-list 'markets' field")
    markets = tuple(
        parse_market(_as_mapping(item, ctx=f"markets[{index}]"))
        for index, item in enumerate(raw_markets)
    )
    raw_cursor = payload.get("cursor")
    cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
    return MarketPage(markets=markets, cursor=cursor)


def build_contracts(market: Market) -> tuple[Contract, Contract]:
    """Return the (YES, NO) contracts for a binary Kalshi market.

    The venue ticker is preserved in each contract id for traceability.
    """
    yes = Contract(market=market, id=f"{market.id}:YES", outcome="YES")
    no = Contract(market=market, id=f"{market.id}:NO", outcome="NO")
    return yes, no


# --------------------------------------------------------------------------- #
# Order book
# --------------------------------------------------------------------------- #


def parse_order_books(
    market: Market,
    payload: Mapping[str, object],
    *,
    observed_at: datetime,
) -> KalshiOrderBooks:
    """Normalize an ``orderbook`` payload into YES and NO :class:`OrderBook`s.

    ``observed_at`` is the caller's timezone-aware capture time; Kalshi's payload
    carries no server timestamp for the book itself.
    """
    book = _require_mapping(payload, "orderbook_fp", ctx="orderbook")
    yes_bids_raw = _parse_levels(book, "yes_dollars", ctx="orderbook.yes_dollars")
    no_bids_raw = _parse_levels(book, "no_dollars", ctx="orderbook.no_dollars")

    yes_contract, no_contract = build_contracts(market)
    try:
        yes_book = OrderBook(
            contract=yes_contract,
            bids=_bid_levels(yes_bids_raw),
            asks=_implied_ask_levels(no_bids_raw),
            timestamp=observed_at,
        )
        no_book = OrderBook(
            contract=no_contract,
            bids=_bid_levels(no_bids_raw),
            asks=_implied_ask_levels(yes_bids_raw),
            timestamp=observed_at,
        )
    except DomainValidationError as exc:
        raise KalshiPayloadError(
            f"orderbook for {market.id}: failed domain validation: {exc}"
        ) from exc
    return KalshiOrderBooks(yes=yes_book, no=no_book)


def _bid_levels(ascending_raw: Sequence[tuple[Decimal, Decimal]]) -> tuple[PriceLevel, ...]:
    """Kalshi lists bids ascending (best last); the domain wants strictly descending."""
    return tuple(
        PriceLevel(price=price, quantity=size) for price, size in reversed(ascending_raw)
    )


def _implied_ask_levels(
    opposite_bids_ascending: Sequence[tuple[Decimal, Decimal]],
) -> tuple[PriceLevel, ...]:
    """Asks implied by the opposite side's bids: price = 1 - bid, size unchanged.

    Opposite bids are ascending, so ``1 - price`` is descending; reverse to get
    the ascending ask order the domain requires.
    """
    return tuple(
        PriceLevel(price=_ONE - price, quantity=size)
        for price, size in reversed(opposite_bids_ascending)
    )


# --------------------------------------------------------------------------- #
# Field extraction helpers — every missing/mistyped field fails loudly
# --------------------------------------------------------------------------- #


def _as_mapping(value: object, *, ctx: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise KalshiPayloadError(f"{ctx}: expected an object, got {type(value).__name__}")
    return value


def _require(payload: Mapping[str, object], key: str, *, ctx: str) -> object:
    if key not in payload:
        raise KalshiPayloadError(f"{ctx}: missing required field {key!r}")
    return payload[key]


def _require_str(payload: Mapping[str, object], key: str, *, ctx: str) -> str:
    value = _require(payload, key, ctx=ctx)
    if not isinstance(value, str) or not value:
        raise KalshiPayloadError(f"{ctx}: field {key!r} must be a non-empty string")
    return value


def _require_mapping(payload: Mapping[str, object], key: str, *, ctx: str) -> Mapping[str, object]:
    return _as_mapping(_require(payload, key, ctx=ctx), ctx=f"{ctx}.{key}")


def _parse_levels(
    book: Mapping[str, object], key: str, *, ctx: str
) -> tuple[tuple[Decimal, Decimal], ...]:
    raw = _require(book, key, ctx=ctx)
    if not isinstance(raw, list):
        raise KalshiPayloadError(f"{ctx}: expected a list of [price, size] pairs")
    levels: list[tuple[Decimal, Decimal]] = []
    for index, element in enumerate(raw):
        if not isinstance(element, list) or len(element) != 2:
            raise KalshiPayloadError(f"{ctx}[{index}]: expected a 2-element [price, size] pair")
        price_raw, size_raw = element[0], element[1]
        if not isinstance(price_raw, str) or not isinstance(size_raw, str):
            raise KalshiPayloadError(
                f"{ctx}[{index}]: price and size must be strings (got "
                f"{type(price_raw).__name__}, {type(size_raw).__name__})"
            )
        levels.append(
            (
                _decimal(price_raw, ctx=f"{ctx}[{index}].price"),
                _decimal(size_raw, ctx=f"{ctx}[{index}].size"),
            )
        )
    return tuple(levels)


def _decimal(raw: str, *, ctx: str) -> Decimal:
    try:
        return to_decimal(raw, field=ctx)
    except DomainValidationError as exc:
        raise KalshiPayloadError(f"{ctx}: {exc}") from exc


def _parse_timestamp(raw: str, *, ctx: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise KalshiPayloadError(f"{ctx}: malformed timestamp {raw!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KalshiPayloadError(f"{ctx}: timestamp {raw!r} is not timezone-aware")
    return parsed
