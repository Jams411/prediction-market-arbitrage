"""Offline, fixture-driven tests for Kalshi -> domain normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from kalshi_support import load_fixture_json

from prediction_market_arbitrage.adapters.kalshi import (
    KALSHI_VENUE,
    KalshiOrderBooks,
    KalshiPayloadError,
    parse_market,
    parse_market_page,
    parse_order_books,
)
from prediction_market_arbitrage.domain import DomainValidationError, Market

OBSERVED_AT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
TICKER = "KXHIGHNY-26SEP06-T73"


def _single_market() -> Market:
    payload = load_fixture_json("market_single.json")
    market = payload["market"]
    assert isinstance(market, dict)
    return parse_market(market)


def _books(fixture: str = "orderbook.json") -> KalshiOrderBooks:
    return parse_order_books(
        _single_market(), load_fixture_json(fixture), observed_at=OBSERVED_AT
    )


# --------------------------------------------------------------------------- #
# Market list / single market
# --------------------------------------------------------------------------- #


def test_market_list_parsing() -> None:
    page = parse_market_page(load_fixture_json("markets_list.json"))

    assert len(page.markets) == 3
    assert page.cursor  # fixture carries a pagination cursor
    for market in page.markets:
        assert market.venue == KALSHI_VENUE
        assert market.venue.id == "kalshi"
        assert market.id  # raw Kalshi ticker preserved
        assert market.close_time is not None
        assert market.close_time.utcoffset() is not None  # timezone-aware


def test_individual_market_parsing() -> None:
    market = _single_market()
    assert market.id == TICKER
    assert market.title == "Will the maximum temperature be <73° on Sep 6, 2026?"
    assert market.close_time == datetime(2026, 9, 7, 5, 0, tzinfo=UTC)


def test_market_type_other_than_binary_is_rejected() -> None:
    payload = load_fixture_json("market_single.json")
    market = payload["market"]
    assert isinstance(market, dict)
    market["market_type"] = "scalar"
    with pytest.raises(KalshiPayloadError, match="market_type"):
        parse_market(market)


@pytest.mark.parametrize("missing", ["ticker", "title", "close_time", "market_type"])
def test_missing_required_market_field_fails_loudly(missing: str) -> None:
    payload = load_fixture_json("market_single.json")
    market = payload["market"]
    assert isinstance(market, dict)
    del market[missing]
    with pytest.raises(KalshiPayloadError):
        parse_market(market)


@pytest.mark.parametrize("bad_close", ["2026-09-07T05:00:00", "not-a-timestamp"])
def test_naive_or_malformed_close_time_rejected(bad_close: str) -> None:
    payload = load_fixture_json("market_single.json")
    market = payload["market"]
    assert isinstance(market, dict)
    market["close_time"] = bad_close
    with pytest.raises(KalshiPayloadError):
        parse_market(market)


# --------------------------------------------------------------------------- #
# Order book normalization
# --------------------------------------------------------------------------- #


def test_order_book_parsing_shape_and_contracts() -> None:
    books = _books()

    assert books.yes.contract.outcome == "YES"
    assert books.no.contract.outcome == "NO"
    assert books.yes.contract.id == f"{TICKER}:YES"
    assert books.no.contract.id == f"{TICKER}:NO"
    assert books.yes.timestamp == OBSERVED_AT
    # fixture: 20 YES bid levels, 54 NO bid levels
    assert len(books.yes.bids) == 20
    assert len(books.yes.asks) == 54  # implied from NO bids
    assert len(books.no.bids) == 54
    assert len(books.no.asks) == 20  # implied from YES bids


def test_order_book_bid_ordering_is_descending() -> None:
    books = _books()
    yes_prices = [level.price for level in books.yes.bids]
    assert yes_prices == sorted(yes_prices, reverse=True)
    assert books.yes.best_bid is not None
    assert books.yes.best_bid.price == Decimal("0.2000")


def test_decimal_preservation_no_float_coercion() -> None:
    books = _books()

    best_bid = books.yes.bids[0]
    worst_bid = books.yes.bids[-1]
    assert isinstance(best_bid.price, Decimal)
    assert isinstance(best_bid.quantity, Decimal)
    assert str(best_bid.price) == "0.2000"          # trailing zeros kept
    assert best_bid.quantity == Decimal("42.49")
    assert str(worst_bid.price) == "0.0100"
    assert str(worst_bid.quantity) == "1532.00"      # exact fixed-point string preserved


def test_complementary_price_normalization() -> None:
    """VERIFIED: YES ask == 1 - NO bid, NO ask == 1 - YES bid (binary market sums to $1)."""
    market_payload = load_fixture_json("market_single.json")["market"]
    assert isinstance(market_payload, dict)

    books = _books()

    assert books.yes.best_ask is not None
    assert books.no.best_ask is not None
    # best NO bid in fixture is 0.7900 -> YES best ask 0.2100
    assert books.yes.best_ask.price == Decimal("1") - Decimal("0.7900")
    assert books.yes.best_ask.price == Decimal("0.2100")
    # best YES bid in fixture is 0.2000 -> NO best ask 0.8000
    assert books.no.best_ask.price == Decimal("0.8000")
    # cross-check against the same market's quoted top-of-book asks
    assert str(books.yes.best_ask.price) == market_payload["yes_ask_dollars"]
    assert str(books.no.best_ask.price) == market_payload["no_ask_dollars"]
    # ask sizes are carried over from the opposing bid unchanged
    assert books.yes.asks[0].quantity == Decimal("68.00")


def test_empty_book_sides() -> None:
    books = parse_order_books(
        _single_market(), load_fixture_json("orderbook_empty.json"), observed_at=OBSERVED_AT
    )
    assert books.yes.bids == ()
    assert books.yes.asks == ()
    assert books.no.bids == ()
    assert books.no.asks == ()
    assert books.yes.best_bid is None
    assert books.yes.best_ask is None


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing orderbook_fp
        {"orderbook_fp": {"yes_dollars": [], "no_dollars": "oops"}},  # side not a list
        {"orderbook_fp": {"yes_dollars": [["0.5000"]], "no_dollars": []}},  # not a pair
        {"orderbook_fp": {"yes_dollars": [[0.5, "1.00"]], "no_dollars": []}},  # float, not str
        {"orderbook_fp": {"yes_dollars": [["bad", "1.00"]], "no_dollars": []}},  # unparseable
        {"orderbook_fp": {"yes_dollars": []}},  # missing no_dollars
    ],
)
def test_malformed_orderbook_payloads_raise(payload: dict[str, object]) -> None:
    with pytest.raises(KalshiPayloadError):
        parse_order_books(_single_market(), payload, observed_at=OBSERVED_AT)


def test_domain_validation_integration_crossed_book() -> None:
    """A crossed implied book must surface as a wrapped domain validation error."""
    payload = {
        "orderbook_fp": {
            "yes_dollars": [["0.6000", "10.00"]],  # YES bid 0.60
            "no_dollars": [["0.6000", "10.00"]],   # -> YES ask 1-0.60 = 0.40  => crossed
        }
    }
    with pytest.raises(KalshiPayloadError) as excinfo:
        parse_order_books(_single_market(), payload, observed_at=OBSERVED_AT)
    assert isinstance(excinfo.value.__cause__, DomainValidationError)
