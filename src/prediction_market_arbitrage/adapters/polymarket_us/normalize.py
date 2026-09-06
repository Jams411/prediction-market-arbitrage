"""Pure functions that map Polymarket US JSON payloads to venue-neutral models.

No I/O here. Every price/qty string is converted through
:func:`prediction_market_arbitrage.domain.to_decimal` (explicit Decimal, never
``float`` — Polymarket embeds some genuine floats like ``orderPriceMinTickSize``
and ``feeCoefficient``, which this adapter never reads). Timestamps are parsed as
timezone-aware ``datetime``.

Market / book mapping (evidence trail in ``docs/API_SOURCES.md``)
---------------------------------------------------------------

A Polymarket US market is a **single binary market**. Its ``marketSides`` array
holds exactly two entries: one with ``long: true`` (the tradeable "long" side,
e.g. ``description: "Yes"`` or a team name) and one with ``long: false`` (its
complement). One market slug has **one** order book, quoted in the long side's
price space, with *explicit* ``bids`` and ``offers`` (unlike Kalshi, which is
bid-only — so there is no ``1 - x`` implied-ask step here).

    Polymarket US                               ->  domain
    market (/v1/market/slug/{slug})             ->  Market(id=slug, title=question,
                                                          close_time=endDate)
    marketSides[ long == true  ]                ->  Contract(id=f"{slug}:LONG",
                                                            outcome=side.description)
    marketSides[ long == false ]                ->  Contract(id=f"{slug}:SHORT",
                                                            outcome=side.description)
    /v1/markets/{slug}/book .bids / .offers     ->  ONE OrderBook(contract=LONG,
                                                                 bids=bids, asks=offers)
    book level {px:{value}, qty}                ->  PriceLevel(price=px.value, quantity=qty)
    book .transactTime                          ->  OrderBook.timestamp

Only the long-side book is returned by the API, so only the long-side
:class:`~prediction_market_arbitrage.domain.OrderBook` is produced. The short
:class:`~prediction_market_arbitrage.domain.Contract` is still materialized
(both sides are real, per ``marketSides``) for later market-pairing work.

Observed book ordering is bids high->low and offers low->high (matches the
``bbo`` endpoint), which is already the domain's required order — but this module
does not assume it: it sorts explicitly and rejects duplicate price levels.
"""

from __future__ import annotations

import re
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

from .errors import PolymarketPayloadError

POLYMARKET_US_VENUE = Venue(id="polymarket_us", name="Polymarket US")
_EXPECTED_CURRENCY = "USD"
# ISO-8601 fractional seconds longer than microseconds (Polymarket sends nanos).
_OVERLONG_FRACTION = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True, slots=True)
class PolymarketMarket:
    """A normalized market plus its two side contracts.

    ``long_contract`` is the side the order book is quoted in.
    """

    market: Market
    long_contract: Contract
    short_contract: Contract


@dataclass(frozen=True, slots=True)
class MarketPage:
    """One page of ``GET /markets`` results (Polymarket paginates by limit/offset)."""

    markets: tuple[PolymarketMarket, ...]


@dataclass(frozen=True, slots=True)
class Bbo:
    """Best bid / offer for a market slug. Either side may be absent."""

    market_slug: str
    best_bid: Decimal | None
    best_ask: Decimal | None


# --------------------------------------------------------------------------- #
# Markets
# --------------------------------------------------------------------------- #


def parse_market(payload: Mapping[str, object]) -> PolymarketMarket:
    """Normalize one Polymarket US ``market`` object."""
    slug = _require_str(payload, "slug", ctx="market")
    question = _require_str(payload, "question", ctx=f"market {slug}")
    close_time = _parse_timestamp(
        _require_str(payload, "endDate", ctx=f"market {slug}"),
        ctx=f"market {slug}.endDate",
    )

    long_side, short_side = _split_sides(payload, slug=slug)
    try:
        market = Market(
            venue=POLYMARKET_US_VENUE, id=slug, title=question, close_time=close_time
        )
        long_contract = Contract(
            market=market,
            id=f"{slug}:LONG",
            outcome=_require_str(long_side, "description", ctx=f"market {slug} long side"),
        )
        short_contract = Contract(
            market=market,
            id=f"{slug}:SHORT",
            outcome=_require_str(short_side, "description", ctx=f"market {slug} short side"),
        )
    except DomainValidationError as exc:
        raise PolymarketPayloadError(
            f"market {slug}: failed domain validation: {exc}"
        ) from exc
    return PolymarketMarket(
        market=market, long_contract=long_contract, short_contract=short_contract
    )


def parse_market_page(payload: Mapping[str, object]) -> MarketPage:
    """Normalize a ``GET /markets`` response into a :class:`MarketPage`."""
    raw_markets = payload.get("markets")
    if not isinstance(raw_markets, list):
        raise PolymarketPayloadError("markets response: missing or non-list 'markets' field")
    markets = tuple(
        parse_market(_as_mapping(item, ctx=f"markets[{index}]"))
        for index, item in enumerate(raw_markets)
    )
    return MarketPage(markets=markets)


def _split_sides(
    payload: Mapping[str, object], *, slug: str
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Return ``(long_side, short_side)``; require exactly one of each."""
    raw_sides = payload.get("marketSides")
    if not isinstance(raw_sides, list) or len(raw_sides) != 2:
        raise PolymarketPayloadError(
            f"market {slug}: expected exactly 2 marketSides, got "
            f"{len(raw_sides) if isinstance(raw_sides, list) else type(raw_sides).__name__}"
        )
    longs: list[Mapping[str, object]] = []
    shorts: list[Mapping[str, object]] = []
    for index, side in enumerate(raw_sides):
        side_map = _as_mapping(side, ctx=f"market {slug} marketSides[{index}]")
        is_long = side_map.get("long")
        if not isinstance(is_long, bool):
            raise PolymarketPayloadError(
                f"market {slug} marketSides[{index}]: 'long' must be a boolean"
            )
        (longs if is_long else shorts).append(side_map)
    if len(longs) != 1 or len(shorts) != 1:
        raise PolymarketPayloadError(
            f"market {slug}: expected exactly one long and one short marketSide"
        )
    return longs[0], shorts[0]


# --------------------------------------------------------------------------- #
# Order book
# --------------------------------------------------------------------------- #


def parse_order_book(
    pm_market: PolymarketMarket,
    market_data: Mapping[str, object],
    *,
    observed_at: datetime,
) -> OrderBook:
    """Normalize a ``book`` ``marketData`` object into one long-side :class:`OrderBook`.

    ``transactTime`` from the payload is used as the book timestamp when present;
    ``observed_at`` (the caller's timezone-aware capture time) is the documented
    fallback when the field is absent.
    """
    slug = pm_market.market.id
    book_slug = market_data.get("marketSlug")
    if isinstance(book_slug, str) and book_slug != slug:
        raise PolymarketPayloadError(
            f"orderbook: marketSlug {book_slug!r} does not match requested market {slug!r}"
        )

    bids_raw = _parse_levels(market_data, "bids", ctx=f"orderbook {slug}.bids")
    offers_raw = _parse_levels(market_data, "offers", ctx=f"orderbook {slug}.offers")

    bids = _sorted_levels(bids_raw, ctx=f"orderbook {slug}.bids", descending=True)
    asks = _sorted_levels(offers_raw, ctx=f"orderbook {slug}.offers", descending=False)

    timestamp = _book_timestamp(market_data, observed_at=observed_at, ctx=f"orderbook {slug}")

    try:
        return OrderBook(
            contract=pm_market.long_contract, bids=bids, asks=asks, timestamp=timestamp
        )
    except DomainValidationError as exc:
        raise PolymarketPayloadError(
            f"orderbook {slug}: failed domain validation: {exc}"
        ) from exc


def parse_bbo(market_data: Mapping[str, object]) -> Bbo:
    """Normalize a ``bbo`` ``marketData`` object. Used to cross-check the book."""
    slug = _require_str(market_data, "marketSlug", ctx="bbo")
    return Bbo(
        market_slug=slug,
        best_bid=_optional_amount(market_data.get("bestBid"), ctx="bbo.bestBid"),
        best_ask=_optional_amount(market_data.get("bestAsk"), ctx="bbo.bestAsk"),
    )


def _sorted_levels(
    raw: Sequence[tuple[Decimal, Decimal]], *, ctx: str, descending: bool
) -> tuple[PriceLevel, ...]:
    ordered = sorted(raw, key=lambda pair: pair[0], reverse=descending)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if earlier[0] == later[0]:
            raise PolymarketPayloadError(f"{ctx}: duplicate price level {earlier[0]}")
    return tuple(PriceLevel(price=price, quantity=size) for price, size in ordered)


def _book_timestamp(
    market_data: Mapping[str, object], *, observed_at: datetime, ctx: str
) -> datetime:
    raw = market_data.get("transactTime")
    if raw is None:
        return observed_at
    if not isinstance(raw, str):
        raise PolymarketPayloadError(f"{ctx}.transactTime: expected a string timestamp")
    return _parse_timestamp(raw, ctx=f"{ctx}.transactTime")


# --------------------------------------------------------------------------- #
# Field extraction helpers — every missing/mistyped field fails loudly
# --------------------------------------------------------------------------- #


def _as_mapping(value: object, *, ctx: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PolymarketPayloadError(f"{ctx}: expected an object, got {type(value).__name__}")
    return value


def _require(payload: Mapping[str, object], key: str, *, ctx: str) -> object:
    if key not in payload:
        raise PolymarketPayloadError(f"{ctx}: missing required field {key!r}")
    return payload[key]


def _require_str(payload: Mapping[str, object], key: str, *, ctx: str) -> str:
    value = _require(payload, key, ctx=ctx)
    if not isinstance(value, str) or not value:
        raise PolymarketPayloadError(f"{ctx}: field {key!r} must be a non-empty string")
    return value


def _parse_levels(
    market_data: Mapping[str, object], key: str, *, ctx: str
) -> tuple[tuple[Decimal, Decimal], ...]:
    raw = _require(market_data, key, ctx=ctx)
    if not isinstance(raw, list):
        raise PolymarketPayloadError(f"{ctx}: expected a list of book entries")
    levels: list[tuple[Decimal, Decimal]] = []
    for index, element in enumerate(raw):
        entry = _as_mapping(element, ctx=f"{ctx}[{index}]")
        px = _as_mapping(_require(entry, "px", ctx=f"{ctx}[{index}]"), ctx=f"{ctx}[{index}].px")
        value = px.get("value")
        currency = px.get("currency")
        qty = entry.get("qty")
        if not isinstance(value, str):
            raise PolymarketPayloadError(
                f"{ctx}[{index}].px.value: must be a string (got {type(value).__name__})"
            )
        if currency != _EXPECTED_CURRENCY:
            raise PolymarketPayloadError(
                f"{ctx}[{index}].px.currency: expected {_EXPECTED_CURRENCY!r}, got {currency!r}"
            )
        if not isinstance(qty, str):
            raise PolymarketPayloadError(
                f"{ctx}[{index}].qty: must be a string (got {type(qty).__name__})"
            )
        levels.append(
            (
                _decimal(value, ctx=f"{ctx}[{index}].px.value"),
                _decimal(qty, ctx=f"{ctx}[{index}].qty"),
            )
        )
    return tuple(levels)


def _optional_amount(value: object, *, ctx: str) -> Decimal | None:
    if value is None:
        return None
    amount = _as_mapping(value, ctx=ctx)
    raw_value = amount.get("value")
    currency = amount.get("currency")
    if not isinstance(raw_value, str):
        raise PolymarketPayloadError(f"{ctx}.value: must be a string")
    if currency != _EXPECTED_CURRENCY:
        raise PolymarketPayloadError(
            f"{ctx}.currency: expected {_EXPECTED_CURRENCY!r}, got {currency!r}"
        )
    return _decimal(raw_value, ctx=f"{ctx}.value")


def _decimal(raw: str, *, ctx: str) -> Decimal:
    try:
        return to_decimal(raw, field=ctx)
    except DomainValidationError as exc:
        raise PolymarketPayloadError(f"{ctx}: {exc}") from exc


def _parse_timestamp(raw: str, *, ctx: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    text = _OVERLONG_FRACTION.sub(r"\1", text, count=1)  # nanoseconds -> microseconds
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PolymarketPayloadError(f"{ctx}: malformed timestamp {raw!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolymarketPayloadError(f"{ctx}: timestamp {raw!r} is not timezone-aware")
    return parsed
