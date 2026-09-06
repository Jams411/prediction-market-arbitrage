"""Polymarket US REST market-data adapter (Milestone M1.3).

Read-only public market data only: market discovery, single market, order book,
and BBO. No authentication, trading, portfolio, WebSocket, or storage code.
"""

from __future__ import annotations

from .adapter import PolymarketMarketDataAdapter
from .client import DEFAULT_TIMEOUT_SECONDS, PROD_BASE_URL, PolymarketClient
from .errors import (
    PolymarketError,
    PolymarketHTTPError,
    PolymarketPayloadError,
    PolymarketTimeoutError,
    PolymarketTransportError,
)
from .normalize import (
    POLYMARKET_US_VENUE,
    Bbo,
    MarketPage,
    PolymarketMarket,
    parse_bbo,
    parse_market,
    parse_market_page,
    parse_order_book,
)
from .transport import HttpResponse, Transport, UrllibTransport

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "POLYMARKET_US_VENUE",
    "PROD_BASE_URL",
    "Bbo",
    "HttpResponse",
    "MarketPage",
    "PolymarketClient",
    "PolymarketError",
    "PolymarketHTTPError",
    "PolymarketMarket",
    "PolymarketMarketDataAdapter",
    "PolymarketPayloadError",
    "PolymarketTimeoutError",
    "PolymarketTransportError",
    "Transport",
    "UrllibTransport",
    "parse_bbo",
    "parse_market",
    "parse_market_page",
    "parse_order_book",
]
