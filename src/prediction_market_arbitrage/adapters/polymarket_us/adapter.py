"""High-level Polymarket US market-data adapter: fetch + normalize in one call.

The object the rest of the system depends on. Deliberately small and replaceable
(``docs/ARCHITECTURE.md``): swap the :class:`PolymarketClient` or its
:class:`~.transport.Transport` for tests or a different HTTP stack.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from prediction_market_arbitrage.domain import OrderBook

from .client import PolymarketClient
from .normalize import (
    Bbo,
    MarketPage,
    PolymarketMarket,
    parse_bbo,
    parse_market,
    parse_market_page,
    parse_order_book,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PolymarketMarketDataAdapter:
    """Venue-neutral façade over Polymarket US's public REST market data."""

    def __init__(
        self,
        client: PolymarketClient | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client if client is not None else PolymarketClient()
        self._clock = clock

    def list_markets(
        self,
        *,
        active: bool | None = None,
        closed: bool | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> MarketPage:
        """Discover markets; returns normalized markets (each with its two side contracts)."""
        payload = self._client.list_markets(
            active=active, closed=closed, archived=archived, limit=limit, offset=offset
        )
        return parse_market_page(payload)

    def get_market(self, slug: str) -> PolymarketMarket:
        """Fetch and normalize a single market by slug."""
        return parse_market(self._client.get_market_by_slug(slug))

    def get_order_book(self, slug: str) -> OrderBook:
        """Fetch a market + its book and return the normalized long-side :class:`OrderBook`.

        Timestamp comes from the book's ``transactTime``; the adapter's ``clock()``
        reading is the fallback only if that field is absent.
        """
        pm_market = self.get_market(slug)
        market_data = self._client.get_book(slug)
        return parse_order_book(pm_market, market_data, observed_at=self._clock())

    def get_bbo(self, slug: str) -> Bbo:
        """Fetch the best bid/offer for a market slug."""
        return parse_bbo(self._client.get_bbo(slug))
