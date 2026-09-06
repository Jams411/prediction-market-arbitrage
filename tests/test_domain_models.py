"""Deterministic unit tests for the M1.1 normalized domain models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from prediction_market_arbitrage.domain import (
    Contract,
    DomainValidationError,
    Market,
    MarketPair,
    Opportunity,
    OrderBook,
    PriceLevel,
    Venue,
    to_decimal,
)

TS = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 1, 1, 12, 0)  # noqa: DTZ001 - intentionally naive for tests


def _venue(vid: str = "kalshi", name: str = "Kalshi") -> Venue:
    return Venue(id=vid, name=name)


def _market(venue: Venue | None = None, mid: str = "mkt-1") -> Market:
    return Market(venue=venue or _venue(), id=mid, title="Example market", close_time=TS)


def _contract(
    outcome: str = "YES",
    cid: str = "ct-1",
    market: Market | None = None,
) -> Contract:
    return Contract(market=market or _market(), id=cid, outcome=outcome)


def _pair() -> MarketPair:
    left = _contract(cid="ct-L", market=_market(_venue("kalshi", "Kalshi"), "mkt-k"))
    right = _contract(
        cid="ct-R", market=_market(_venue("polymarket-us", "Polymarket US"), "mkt-p")
    )
    return MarketPair(id="pair-1", left=left, right=right, note="verified 2026-01-01")


def _level(price: str, quantity: str) -> PriceLevel:
    return PriceLevel(price=Decimal(price), quantity=Decimal(quantity))


# --------------------------------------------------------------------------- #
# Valid construction of every model
# --------------------------------------------------------------------------- #


def test_valid_construction_of_every_model() -> None:
    venue = _venue()
    market = _market(venue)
    contract = _contract(market=market)
    level = _level("0.40", "100")
    book = OrderBook(
        contract=contract,
        bids=(_level("0.40", "100"), _level("0.39", "50")),
        asks=(_level("0.41", "70"), _level("0.45", "30")),
        timestamp=TS,
    )
    pair = _pair()
    opp = Opportunity(
        id="opp-1", pair=pair, quantity=Decimal("10"), edge=Decimal("0.02"), timestamp=TS
    )

    assert contract.venue == venue
    assert level.price == Decimal("0.40")
    assert book.contract is contract
    assert pair.left != pair.right
    assert opp.pair is pair


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_id", ["", "   ", "\t\n"])
def test_empty_identifiers_are_rejected(bad_id: str) -> None:
    with pytest.raises(DomainValidationError):
        Venue(id=bad_id, name="Kalshi")
    with pytest.raises(DomainValidationError):
        Venue(id="kalshi", name=bad_id)
    with pytest.raises(DomainValidationError):
        Market(venue=_venue(), id=bad_id, title="t")
    with pytest.raises(DomainValidationError):
        Contract(market=_market(), id=bad_id, outcome="YES")
    with pytest.raises(DomainValidationError):
        Contract(market=_market(), id="ct-1", outcome=bad_id)


# --------------------------------------------------------------------------- #
# PriceLevel: quantity and probability-price boundaries
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("price", ["0", "0.0000", "0.5", "1", "1.0"])
def test_price_level_accepts_inclusive_probability_range(price: str) -> None:
    assert PriceLevel(price=Decimal(price), quantity=Decimal("1")).price == Decimal(price)


@pytest.mark.parametrize("price", ["-0.01", "1.01", "-1", "2"])
def test_price_level_rejects_prices_outside_range(price: str) -> None:
    with pytest.raises(DomainValidationError):
        PriceLevel(price=Decimal(price), quantity=Decimal("1"))


@pytest.mark.parametrize("quantity", ["0", "-1", "-0.0001"])
def test_price_level_rejects_non_positive_quantity(quantity: str) -> None:
    with pytest.raises(DomainValidationError):
        PriceLevel(price=Decimal("0.5"), quantity=Decimal(quantity))


# --------------------------------------------------------------------------- #
# Decimal discipline: no silent float/int coercion, no non-finite values
# --------------------------------------------------------------------------- #


def test_models_reject_float_input_without_coercion() -> None:
    with pytest.raises(DomainValidationError):
        PriceLevel(price=0.5, quantity=Decimal("1"))  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        PriceLevel(price=Decimal("0.5"), quantity=1.0)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        Opportunity(
            id="o", pair=_pair(), quantity=10, edge=0.02, timestamp=TS  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_models_reject_non_finite_decimal(value: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        PriceLevel(price=value, quantity=Decimal("1"))


def test_decimal_values_are_preserved_exactly() -> None:
    level = PriceLevel(price=Decimal("0.10"), quantity=Decimal("100.0"))
    assert isinstance(level.price, Decimal)
    assert str(level.price) == "0.10"  # trailing zero / exponent retained
    assert str(level.quantity) == "100.0"
    opp = Opportunity(
        id="o", pair=_pair(), quantity=Decimal("2.500"), edge=Decimal("0.0025"), timestamp=TS
    )
    assert str(opp.quantity) == "2.500"
    assert opp.edge == Decimal("0.0025")


# --------------------------------------------------------------------------- #
# Timezone-aware timestamp enforcement
# --------------------------------------------------------------------------- #


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(DomainValidationError):
        OrderBook(contract=_contract(), bids=(), asks=(), timestamp=NAIVE)
    with pytest.raises(DomainValidationError):
        Market(venue=_venue(), id="m", title="t", close_time=NAIVE)
    with pytest.raises(DomainValidationError):
        Opportunity(
            id="o", pair=_pair(), quantity=Decimal("1"), edge=Decimal("0.01"), timestamp=NAIVE
        )


def test_non_utc_aware_timestamp_is_accepted() -> None:
    tz = timezone(timedelta(hours=-5))
    aware = datetime(2026, 1, 1, 7, 0, tzinfo=tz)
    book = OrderBook(contract=_contract(), bids=(), asks=(), timestamp=aware)
    assert book.timestamp.utcoffset() == timedelta(hours=-5)


# --------------------------------------------------------------------------- #
# OrderBook: ordering, duplicates, crossed/locked, best bid/ask
# --------------------------------------------------------------------------- #


def test_best_bid_and_best_ask() -> None:
    book = OrderBook(
        contract=_contract(),
        bids=(_level("0.40", "10"), _level("0.39", "5")),
        asks=(_level("0.41", "7"), _level("0.50", "3")),
        timestamp=TS,
    )
    assert book.best_bid == _level("0.40", "10")
    assert book.best_ask == _level("0.41", "7")


def test_best_bid_and_best_ask_none_when_side_empty() -> None:
    book = OrderBook(contract=_contract(), bids=(), asks=(), timestamp=TS)
    assert book.best_bid is None
    assert book.best_ask is None


def test_order_book_rejects_unsorted_sides() -> None:
    with pytest.raises(DomainValidationError):
        OrderBook(
            contract=_contract(),
            bids=(_level("0.39", "1"), _level("0.40", "1")),  # ascending: wrong
            asks=(),
            timestamp=TS,
        )
    with pytest.raises(DomainValidationError):
        OrderBook(
            contract=_contract(),
            bids=(),
            asks=(_level("0.45", "1"), _level("0.44", "1")),  # descending: wrong
            timestamp=TS,
        )


def test_order_book_rejects_duplicate_price_levels() -> None:
    with pytest.raises(DomainValidationError):
        OrderBook(
            contract=_contract(),
            bids=(_level("0.40", "1"), _level("0.40", "2")),
            asks=(),
            timestamp=TS,
        )


def test_order_book_rejects_crossed_book() -> None:
    with pytest.raises(DomainValidationError):  # crossed: best bid > best ask
        OrderBook(
            contract=_contract(),
            bids=(_level("0.60", "1"),),
            asks=(_level("0.55", "1"),),
            timestamp=TS,
        )


def test_order_book_accepts_locked_book() -> None:
    # Locked: best bid == best ask is a permitted transient state.
    book = OrderBook(
        contract=_contract(),
        bids=(_level("0.50", "1"),),
        asks=(_level("0.50", "2"),),
        timestamp=TS,
    )
    assert book.best_bid is not None
    assert book.best_ask is not None
    assert book.best_bid.price == book.best_ask.price


def test_order_book_accepts_ordinary_uncrossed_book() -> None:
    book = OrderBook(
        contract=_contract(),
        bids=(_level("0.49", "1"), _level("0.48", "3")),
        asks=(_level("0.51", "1"), _level("0.52", "3")),
        timestamp=TS,
    )
    assert book.best_bid is not None
    assert book.best_ask is not None
    assert book.best_bid.price < book.best_ask.price


# --------------------------------------------------------------------------- #
# MarketPair
# --------------------------------------------------------------------------- #


def test_market_pair_rejects_identical_sides() -> None:
    contract = _contract()
    with pytest.raises(DomainValidationError):
        MarketPair(id="p", left=contract, right=contract)


def test_market_pair_rejects_empty_id() -> None:
    with pytest.raises(DomainValidationError):
        MarketPair(id="  ", left=_contract(cid="a"), right=_contract(cid="b"))


def test_market_pair_allows_distinct_cross_venue_contracts() -> None:
    pair = _pair()
    assert pair.left.venue != pair.right.venue


# --------------------------------------------------------------------------- #
# Opportunity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("quantity", ["0", "-1"])
def test_opportunity_rejects_non_positive_quantity(quantity: str) -> None:
    with pytest.raises(DomainValidationError):
        Opportunity(
            id="o",
            pair=_pair(),
            quantity=Decimal(quantity),
            edge=Decimal("0.01"),
            timestamp=TS,
        )


@pytest.mark.parametrize("edge", ["0", "-0.01"])
def test_opportunity_rejects_non_positive_edge(edge: str) -> None:
    with pytest.raises(DomainValidationError):
        Opportunity(
            id="o",
            pair=_pair(),
            quantity=Decimal("10"),
            edge=Decimal(edge),
            timestamp=TS,
        )


def test_opportunity_rejects_empty_id() -> None:
    with pytest.raises(DomainValidationError):
        Opportunity(
            id="", pair=_pair(), quantity=Decimal("1"), edge=Decimal("0.01"), timestamp=TS
        )


# --------------------------------------------------------------------------- #
# Equality / immutability semantics
# --------------------------------------------------------------------------- #


def test_value_equality_and_hashing() -> None:
    assert _venue() == _venue()
    assert hash(_venue()) == hash(_venue())
    assert _venue() != _venue("polymarket-us", "Polymarket US")
    assert _level("0.40", "10") == _level("0.40", "10")
    assert {_level("0.40", "10"), _level("0.40", "10")} == {_level("0.40", "10")}


def test_models_are_frozen() -> None:
    venue = _venue()
    with pytest.raises(FrozenInstanceError):
        venue.id = "other"  # type: ignore[misc]
    level = _level("0.40", "10")
    with pytest.raises(FrozenInstanceError):
        level.price = Decimal("0.41")  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# to_decimal boundary helper
# --------------------------------------------------------------------------- #


def test_to_decimal_accepts_decimal_int_and_str() -> None:
    assert to_decimal(Decimal("0.30"), field="x") == Decimal("0.30")
    assert to_decimal(3, field="x") == Decimal("3")
    assert to_decimal("0.30", field="x") == Decimal("0.30")
    assert str(to_decimal("0.30", field="x")) == "0.30"


@pytest.mark.parametrize(
    "bad",
    [0.1, True, "not-a-number", Decimal("NaN"), Decimal("Infinity")],
)
def test_to_decimal_rejects_float_bool_garbage_and_non_finite(bad: object) -> None:
    with pytest.raises(DomainValidationError):
        to_decimal(bad, field="x")  # type: ignore[arg-type]
