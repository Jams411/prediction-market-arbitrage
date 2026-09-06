"""Offline, fixture-driven tests for Polymarket US -> domain normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from polymarket_us_support import load_fixture_json, market_data, market_object

from prediction_market_arbitrage.adapters.polymarket_us import (
    POLYMARKET_US_VENUE,
    PolymarketMarket,
    PolymarketPayloadError,
    parse_bbo,
    parse_market,
    parse_market_page,
    parse_order_book,
)
from prediction_market_arbitrage.domain import DomainValidationError

OBSERVED_AT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
SLUG = "tec-mlb-nlchamp-2026-09-27-mil"


def _market() -> PolymarketMarket:
    return parse_market(market_object())


# --------------------------------------------------------------------------- #
# Market list / single market
# --------------------------------------------------------------------------- #


def test_market_list_parsing() -> None:
    page = parse_market_page(load_fixture_json("markets_list.json"))

    assert len(page.markets) == 3
    for pm in page.markets:
        assert pm.market.venue == POLYMARKET_US_VENUE
        assert pm.market.id  # raw slug preserved
        assert pm.market.close_time is not None
        assert pm.market.close_time.utcoffset() is not None
        assert pm.long_contract.outcome == "Yes"
        assert pm.short_contract.outcome == "No"
        assert pm.long_contract.id == f"{pm.market.id}:LONG"
        assert pm.short_contract.id == f"{pm.market.id}:SHORT"
        assert pm.long_contract.venue == POLYMARKET_US_VENUE


def test_individual_market_parsing() -> None:
    pm = _market()
    assert pm.market.id == SLUG
    assert pm.market.title == "National League Champion"
    assert pm.market.close_time == datetime(2026, 11, 6, 16, 20, 9, tzinfo=UTC)
    assert pm.long_contract.outcome == "Yes"
    assert pm.short_contract.outcome == "No"


@pytest.mark.parametrize("missing", ["slug", "question", "endDate", "marketSides"])
def test_missing_required_market_field_fails_loudly(missing: str) -> None:
    payload = market_object()
    del payload[missing]
    with pytest.raises(PolymarketPayloadError):
        parse_market(payload)


def test_market_sides_must_be_exactly_two() -> None:
    payload = market_object()
    sides = payload["marketSides"]
    assert isinstance(sides, list)
    payload["marketSides"] = sides[:1]
    with pytest.raises(PolymarketPayloadError, match="marketSides"):
        parse_market(payload)


def test_market_sides_need_one_long_one_short() -> None:
    payload = market_object()
    sides = payload["marketSides"]
    assert isinstance(sides, list) and isinstance(sides[0], dict) and isinstance(sides[1], dict)
    sides[1]["long"] = True  # two long sides, no short
    with pytest.raises(PolymarketPayloadError, match="long and one short"):
        parse_market(payload)


@pytest.mark.parametrize("bad_end", ["2026-11-06T16:20:09", "not-a-timestamp"])
def test_naive_or_malformed_end_date_rejected(bad_end: str) -> None:
    payload = market_object()
    payload["endDate"] = bad_end
    with pytest.raises(PolymarketPayloadError):
        parse_market(payload)


# --------------------------------------------------------------------------- #
# Order book normalization
# --------------------------------------------------------------------------- #


def test_order_book_parsing_shape_and_contract() -> None:
    book = parse_order_book(_market(), market_data("orderbook.json"), observed_at=OBSERVED_AT)

    assert book.contract.outcome == "Yes"
    assert book.contract.id == f"{SLUG}:LONG"
    assert len(book.bids) == 11
    assert len(book.asks) == 6


def test_order_book_ordering_from_source() -> None:
    book = parse_order_book(_market(), market_data("orderbook.json"), observed_at=OBSERVED_AT)
    bid_prices = [level.price for level in book.bids]
    ask_prices = [level.price for level in book.asks]
    assert bid_prices == sorted(bid_prices, reverse=True)
    assert ask_prices == sorted(ask_prices)
    assert book.best_bid is not None and book.best_bid.price == Decimal("0.2650")
    assert book.best_ask is not None and book.best_ask.price == Decimal("0.3820")


def test_order_book_sorts_unordered_input() -> None:
    """The adapter must not assume source order — it sorts explicitly."""
    payload: dict[str, object] = {
        "marketSlug": SLUG,
        "bids": [
            {"px": {"value": "0.10", "currency": "USD"}, "qty": "5"},
            {"px": {"value": "0.30", "currency": "USD"}, "qty": "5"},
            {"px": {"value": "0.20", "currency": "USD"}, "qty": "5"},
        ],
        "offers": [
            {"px": {"value": "0.80", "currency": "USD"}, "qty": "5"},
            {"px": {"value": "0.60", "currency": "USD"}, "qty": "5"},
        ],
    }
    book = parse_order_book(_market(), payload, observed_at=OBSERVED_AT)
    assert [level.price for level in book.bids] == [
        Decimal("0.30"),
        Decimal("0.20"),
        Decimal("0.10"),
    ]
    assert [level.price for level in book.asks] == [Decimal("0.60"), Decimal("0.80")]


def test_duplicate_price_level_rejected() -> None:
    payload: dict[str, object] = {
        "marketSlug": SLUG,
        "bids": [
            {"px": {"value": "0.20", "currency": "USD"}, "qty": "5"},
            {"px": {"value": "0.20", "currency": "USD"}, "qty": "7"},
        ],
        "offers": [],
    }
    with pytest.raises(PolymarketPayloadError, match="duplicate price level"):
        parse_order_book(_market(), payload, observed_at=OBSERVED_AT)


def test_decimal_preservation_no_float_coercion() -> None:
    book = parse_order_book(_market(), market_data("orderbook.json"), observed_at=OBSERVED_AT)
    best_bid = book.bids[0]
    assert isinstance(best_bid.price, Decimal)
    assert isinstance(best_bid.quantity, Decimal)
    assert str(best_bid.price) == "0.2650"
    assert str(best_bid.quantity) == "27.0000"  # exact fixed-point string preserved


def test_transact_time_is_book_timestamp_nanos_truncated() -> None:
    book = parse_order_book(_market(), market_data("orderbook.json"), observed_at=OBSERVED_AT)
    # fixture transactTime = "2026-09-06T00:57:41.446134874Z" (nanoseconds)
    assert book.timestamp == datetime(2026, 9, 6, 0, 57, 41, 446134, tzinfo=UTC)


def test_observed_at_used_when_transact_time_absent() -> None:
    payload: dict[str, object] = {"marketSlug": SLUG, "bids": [], "offers": []}
    book = parse_order_book(_market(), payload, observed_at=OBSERVED_AT)
    assert book.timestamp == OBSERVED_AT


@pytest.mark.parametrize("bad_ts", ["2026-09-06T00:57:41", "garbage", 12345])
def test_malformed_transact_time_rejected(bad_ts: object) -> None:
    payload: dict[str, object] = {
        "marketSlug": SLUG,
        "bids": [],
        "offers": [],
        "transactTime": bad_ts,
    }
    with pytest.raises(PolymarketPayloadError):
        parse_order_book(_market(), payload, observed_at=OBSERVED_AT)


def test_empty_book_sides() -> None:
    # orderbook_empty.json is a real capture from a different market; drop its
    # marketSlug so this test exercises empty sides, not the slug cross-check.
    payload = dict(market_data("orderbook_empty.json"))
    payload.pop("marketSlug", None)
    book = parse_order_book(_market(), payload, observed_at=OBSERVED_AT)
    assert book.bids == ()
    assert book.asks == ()
    assert book.best_bid is None
    assert book.best_ask is None


def test_marketslug_mismatch_rejected() -> None:
    payload = dict(market_data("orderbook.json"))
    payload["marketSlug"] = "some-other-slug"
    with pytest.raises(PolymarketPayloadError, match="does not match"):
        parse_order_book(_market(), payload, observed_at=OBSERVED_AT)


@pytest.mark.parametrize(
    "payload",
    [
        {"marketSlug": SLUG, "offers": []},  # missing bids
        {"marketSlug": SLUG, "bids": "nope", "offers": []},  # bids not a list
        {"marketSlug": SLUG, "bids": [["0.2", "5"]], "offers": []},  # entry not an object
        {"marketSlug": SLUG, "bids": [{"qty": "5"}], "offers": []},  # missing px
        {
            "marketSlug": SLUG,
            "bids": [{"px": {"value": 0.2, "currency": "USD"}, "qty": "5"}],  # float value
            "offers": [],
        },
        {
            "marketSlug": SLUG,
            "bids": [{"px": {"value": "0.2", "currency": "EUR"}, "qty": "5"}],  # wrong currency
            "offers": [],
        },
        {
            "marketSlug": SLUG,
            "bids": [{"px": {"value": "0.2", "currency": "USD"}, "qty": 5}],  # numeric qty
            "offers": [],
        },
        {
            "marketSlug": SLUG,
            "bids": [{"px": {"value": "abc", "currency": "USD"}, "qty": "5"}],  # bad decimal
            "offers": [],
        },
    ],
)
def test_malformed_book_payloads_raise(payload: dict[str, object]) -> None:
    with pytest.raises(PolymarketPayloadError):
        parse_order_book(_market(), payload, observed_at=OBSERVED_AT)


def test_domain_validation_integration_crossed_book() -> None:
    payload: dict[str, object] = {
        "marketSlug": SLUG,
        "bids": [{"px": {"value": "0.60", "currency": "USD"}, "qty": "5"}],
        "offers": [{"px": {"value": "0.40", "currency": "USD"}, "qty": "5"}],
    }
    with pytest.raises(PolymarketPayloadError) as excinfo:
        parse_order_book(_market(), payload, observed_at=OBSERVED_AT)
    assert isinstance(excinfo.value.__cause__, DomainValidationError)


# --------------------------------------------------------------------------- #
# BBO (cross-check)
# --------------------------------------------------------------------------- #


def test_bbo_parsing_matches_book_top() -> None:
    bbo = parse_bbo(market_data("bbo.json"))
    book = parse_order_book(_market(), market_data("orderbook.json"), observed_at=OBSERVED_AT)

    assert bbo.market_slug == SLUG
    assert bbo.best_bid == Decimal("0.2650")
    assert bbo.best_ask == Decimal("0.3820")
    assert book.best_bid is not None and bbo.best_bid == book.best_bid.price
    assert book.best_ask is not None and bbo.best_ask == book.best_ask.price


def test_bbo_absent_side_is_none() -> None:
    bbo = parse_bbo({"marketSlug": SLUG, "bestBid": {"value": "0.1", "currency": "USD"}})
    assert bbo.best_bid == Decimal("0.1")
    assert bbo.best_ask is None
