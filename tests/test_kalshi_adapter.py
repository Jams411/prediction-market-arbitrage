"""Offline tests for the KalshiMarketDataAdapter façade and architecture boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from kalshi_support import FakeTransport, load_fixture_bytes

import prediction_market_arbitrage.domain as domain_pkg
from prediction_market_arbitrage.adapters.kalshi import (
    HttpResponse,
    KalshiClient,
    KalshiMarketDataAdapter,
    KalshiTimeoutError,
)

BASE = "https://example.test/trade-api/v2"
TICKER = "KXHIGHNY-26SEP06-T73"
FIXED_CLOCK = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _adapter() -> KalshiMarketDataAdapter:
    transport = FakeTransport(
        routes=[
            ("/orderbook", HttpResponse(200, load_fixture_bytes("orderbook.json"))),
            (f"/markets/{TICKER}", HttpResponse(200, load_fixture_bytes("market_single.json"))),
            ("/markets", HttpResponse(200, load_fixture_bytes("markets_list.json"))),
        ]
    )
    client = KalshiClient(base_url=BASE, transport=transport, timeout=5.0)
    return KalshiMarketDataAdapter(client, clock=lambda: FIXED_CLOCK)


def test_adapter_get_market() -> None:
    market = _adapter().get_market(TICKER)
    assert market.id == TICKER
    assert market.venue.id == "kalshi"


def test_adapter_list_markets() -> None:
    page = _adapter().list_markets(status="open", limit=3)
    assert len(page.markets) == 3
    assert all(m.venue.id == "kalshi" for m in page.markets)


def test_adapter_get_order_books_uses_injected_clock() -> None:
    books = _adapter().get_order_books(TICKER)
    assert books.yes.timestamp == FIXED_CLOCK
    assert books.no.timestamp == FIXED_CLOCK
    assert books.yes.best_bid is not None
    assert books.yes.best_bid.price == Decimal("0.2000")
    assert books.yes.best_ask is not None
    assert books.yes.best_ask.price == Decimal("0.2100")


def test_adapter_propagates_timeout() -> None:
    transport = FakeTransport(raises=KalshiTimeoutError("timed out"))
    adapter = KalshiMarketDataAdapter(
        KalshiClient(base_url=BASE, transport=transport, timeout=5.0),
        clock=lambda: FIXED_CLOCK,
    )
    with pytest.raises(KalshiTimeoutError):
        adapter.get_market(TICKER)


def test_domain_layer_does_not_import_adapter_code() -> None:
    """ARCHITECTURE boundary: core domain must not depend on venue adapters."""
    domain_root = Path(domain_pkg.__file__).parent
    for py_file in domain_root.rglob("*.py"):
        source = py_file.read_text()
        assert "adapters" not in source, py_file
        assert "kalshi" not in source.lower(), py_file
