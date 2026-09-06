"""High-level Kalshi market-data adapter: fetch + normalize in one call.

This is the object the rest of the system depends on. It is deliberately small
and replaceable (``docs/ARCHITECTURE.md``): swap the :class:`KalshiClient` or its
:class:`~.transport.Transport` for tests or for a different HTTP stack.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from prediction_market_arbitrage.domain import Market

from .client import KalshiClient
from .normalize import (
    KalshiOrderBooks,
    MarketPage,
    parse_market,
    parse_market_page,
    parse_order_books,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KalshiMarketDataAdapter:
    """Venue-neutral façade over Kalshi's public REST market data."""

    def __init__(
        self,
        client: KalshiClient | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client if client is not None else KalshiClient()
        self._clock = clock

    def list_markets(
        self,
        *,
        status: str | None = None,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        tickers: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> MarketPage:
        """Discover markets; returns normalized :class:`Market`s plus the page cursor."""
        payload = self._client.list_markets(
            status=status,
            series_ticker=series_ticker,
            event_ticker=event_ticker,
            tickers=tickers,
            limit=limit,
            cursor=cursor,
        )
        return parse_market_page(payload)

    def get_market(self, ticker: str) -> Market:
        """Fetch and normalize a single market's metadata."""
        return parse_market(self._client.get_market(ticker))

    def get_order_books(self, ticker: str, *, depth: int | None = None) -> KalshiOrderBooks:
        """Fetch a market + its order book and return the normalized YES/NO books.

        The book timestamp is this adapter's ``clock()`` reading taken after the
        responses are received (Kalshi sends no per-book server timestamp).
        """
        market = self.get_market(ticker)
        payload = self._client.get_market_orderbook(ticker, depth=depth)
        return parse_order_books(market, payload, observed_at=self._clock())
