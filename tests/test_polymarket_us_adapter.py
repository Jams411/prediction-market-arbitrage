"""Offline tests for PolymarketMarketDataAdapter and the architecture boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from polymarket_us_support import FakeTransport, load_fixture_bytes

import prediction_market_arbitrage.domain as domain_pkg
from prediction_market_arbitrage.adapters.polymarket_us import (
    HttpResponse,
    PolymarketClient,
    PolymarketMarketDataAdapter,
    PolymarketTimeoutError,
)

BASE = "https://gateway.example.test/v1"
SLUG = "tec-mlb-nlchamp-2026-09-27-mil"
FIXED_CLOCK = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _adapter() -> PolymarketMarketDataAdapter:
    transport = FakeTransport(
        routes=[
            ("/bbo", HttpResponse(200, load_fixture_bytes("bbo.json"))),
            ("/book", HttpResponse(200, load_fixture_bytes("orderbook.json"))),
            (f"/market/slug/{SLUG}", HttpResponse(200, load_fixture_bytes("market_single.json"))),
            ("/markets", HttpResponse(200, load_fixture_bytes("markets_list.json"))),
        ]
    )
    client = PolymarketClient(base_url=BASE, transport=transport, timeout=5.0)
    return PolymarketMarketDataAdapter(client, clock=lambda: FIXED_CLOCK)


def test_adapter_get_market() -> None:
    pm = _adapter().get_market(SLUG)
    assert pm.market.id == SLUG
    assert pm.market.venue.id == "polymarket_us"
    assert pm.long_contract.outcome == "Yes"


def test_adapter_list_markets() -> None:
    page = _adapter().list_markets(active=True, closed=False, limit=3)
    assert len(page.markets) == 3
    assert all(pm.market.venue.id == "polymarket_us" for pm in page.markets)


def test_adapter_get_order_book_uses_book_transact_time() -> None:
    book = _adapter().get_order_book(SLUG)
    # book timestamp comes from transactTime, not the injected clock
    assert book.timestamp == datetime(2026, 9, 6, 0, 57, 41, 446134, tzinfo=UTC)
    assert book.timestamp != FIXED_CLOCK
    assert book.best_bid is not None and book.best_bid.price == Decimal("0.2650")
    assert book.best_ask is not None and book.best_ask.price == Decimal("0.3820")


def test_adapter_get_bbo() -> None:
    bbo = _adapter().get_bbo(SLUG)
    assert bbo.market_slug == SLUG
    assert bbo.best_bid == Decimal("0.2650")
    assert bbo.best_ask == Decimal("0.3820")


def test_adapter_propagates_timeout() -> None:
    transport = FakeTransport(raises=PolymarketTimeoutError("timed out"))
    adapter = PolymarketMarketDataAdapter(
        PolymarketClient(base_url=BASE, transport=transport, timeout=5.0),
        clock=lambda: FIXED_CLOCK,
    )
    with pytest.raises(PolymarketTimeoutError):
        adapter.get_market(SLUG)


def test_domain_layer_does_not_import_adapter_code() -> None:
    """ARCHITECTURE boundary: core domain must not depend on venue adapters."""
    domain_root = Path(domain_pkg.__file__).parent
    for py_file in domain_root.rglob("*.py"):
        source = py_file.read_text().lower()
        assert "adapters" not in source, py_file
        assert "polymarket" not in source, py_file
        assert "kalshi" not in source, py_file
