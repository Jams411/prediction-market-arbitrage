"""Thin Kalshi REST client for public market data (M1.2).

Responsibilities: build URLs, perform the request via a :class:`Transport`,
translate HTTP/transport failures into :mod:`.errors`, and JSON-decode a 2xx
body into a plain ``dict``. It does **no** domain normalization — see
:mod:`.normalize`.

Scope: read-only market data only. No auth, orders, portfolio, or WebSocket code.

Evidence (see ``docs/API_SOURCES.md``):
- Public market-data endpoints require no authentication. OBSERVED 2026-09-05:
  unauthenticated ``GET`` on ``/markets``, ``/markets/{ticker}`` and
  ``/markets/{ticker}/orderbook`` all returned HTTP 200 against production.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import cast

from .errors import KalshiHTTPError, KalshiPayloadError
from .transport import HttpResponse, Transport, UrllibTransport

PROD_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
DEMO_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
DEFAULT_TIMEOUT_SECONDS = 10.0

_JsonObject = dict[str, object]


class KalshiClient:
    """Fetches raw JSON objects from the Kalshi market-data REST API."""

    def __init__(
        self,
        *,
        base_url: str = PROD_BASE_URL,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._transport: Transport = transport if transport is not None else UrllibTransport()
        self._timeout = timeout

    # -- public endpoints ------------------------------------------------------

    def list_markets(
        self,
        *,
        status: str | None = None,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        tickers: str | None = None,
        mve_filter: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> _JsonObject:
        """``GET /markets`` — market discovery. Returns the raw ``{markets, cursor}`` object."""
        return self._get_json(
            "/markets",
            {
                "status": status,
                "series_ticker": series_ticker,
                "event_ticker": event_ticker,
                "tickers": tickers,
                "mve_filter": mve_filter,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_market(self, ticker: str) -> _JsonObject:
        """``GET /markets/{ticker}`` — returns the inner ``market`` object."""
        self._require_ticker(ticker)
        payload = self._get_json(f"/markets/{urllib.parse.quote(ticker)}", None)
        market = payload.get("market")
        if not isinstance(market, dict):
            raise KalshiPayloadError(
                f"GET /markets/{ticker}: response is missing the 'market' object"
            )
        return cast("_JsonObject", market)

    def list_events(
        self,
        *,
        status: str | None = None,
        with_nested_markets: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> _JsonObject:
        """``GET /events`` — public parent-event metadata."""
        return self._get_json(
            "/events",
            {
                "status": status,
                "with_nested_markets": _bool_param(with_nested_markets),
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_market_orderbook(self, ticker: str, *, depth: int | None = None) -> _JsonObject:
        """``GET /markets/{ticker}/orderbook`` — returns the raw ``{orderbook_fp: ...}`` object."""
        self._require_ticker(ticker)
        return self._get_json(
            f"/markets/{urllib.parse.quote(ticker)}/orderbook",
            {"depth": depth},
        )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _require_ticker(ticker: str) -> None:
        if not ticker or not ticker.strip():
            raise ValueError("ticker must be a non-empty string")

    def _get_json(self, path: str, params: dict[str, object] | None) -> _JsonObject:
        url = f"{self._base_url}{path}"
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
            if query:
                url = f"{url}?{query}"

        response = self._transport.request("GET", url, timeout=self._timeout)

        if not 200 <= response.status < 300:
            raise _http_error(response)

        try:
            parsed: object = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise KalshiPayloadError(f"GET {path}: response body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise KalshiPayloadError(
                f"GET {path}: expected a JSON object, got {type(parsed).__name__}"
            )
        return cast("_JsonObject", parsed)


def _http_error(response: HttpResponse) -> KalshiHTTPError:
    """Build a ``KalshiHTTPError``, using Kalshi's ``{error:{code,message}}`` body when present."""
    code: str | None = None
    message: str | None = None
    try:
        parsed: object = json.loads(response.body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            raw_code = error.get("code")
            raw_message = error.get("message")
            code = raw_code if isinstance(raw_code, str) else None
            message = raw_message if isinstance(raw_message, str) else None
    return KalshiHTTPError(status=response.status, code=code, message=message)


def _bool_param(value: bool | None) -> str | None:
    if value is None:
        return None
    return "true" if value else "false"
