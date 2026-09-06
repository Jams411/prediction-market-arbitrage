"""Kalshi REST market-data adapter (Milestone M1.2).

Read-only public market data only: market discovery, single market, and order
book. No authentication, trading, portfolio, WebSocket, or storage code.
"""

from __future__ import annotations

from .adapter import KalshiMarketDataAdapter
from .client import DEFAULT_TIMEOUT_SECONDS, DEMO_BASE_URL, PROD_BASE_URL, KalshiClient
from .errors import (
    KalshiError,
    KalshiHTTPError,
    KalshiPayloadError,
    KalshiTimeoutError,
    KalshiTransportError,
)
from .normalize import (
    KALSHI_VENUE,
    KalshiOrderBooks,
    MarketPage,
    build_contracts,
    parse_market,
    parse_market_page,
    parse_order_books,
)
from .transport import HttpResponse, Transport, UrllibTransport

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEMO_BASE_URL",
    "KALSHI_VENUE",
    "PROD_BASE_URL",
    "HttpResponse",
    "KalshiClient",
    "KalshiError",
    "KalshiHTTPError",
    "KalshiMarketDataAdapter",
    "KalshiOrderBooks",
    "KalshiPayloadError",
    "KalshiTimeoutError",
    "KalshiTransportError",
    "MarketPage",
    "Transport",
    "UrllibTransport",
    "build_contracts",
    "parse_market",
    "parse_market_page",
    "parse_order_books",
]
