"""Thin Polymarket US REST client for public market data (M1.3).

Responsibilities: build URLs, perform the request via a :class:`Transport`,
translate HTTP/transport failures into :mod:`.errors`, and JSON-decode a 2xx
body into a plain ``dict``. No domain normalization — see :mod:`.normalize`.

Scope: read-only public market data only. No auth, orders, portfolio, or
WebSocket code.

Evidence (see ``docs/API_SOURCES.md``):
- Host ``https://gateway.polymarket.us`` ; endpoints under ``/v1``.
- Market-data endpoints are public (OpenAPI ``security: []``; official Python
  SDK README lists ``markets.list/retrieve_by_slug/book/bbo`` under
  "Public Endpoints (No Authentication)"). OBSERVED 2026-09-05: unauthenticated
  ``GET`` on ``/v1/markets``, ``/v1/market/slug/{slug}``,
  ``/v1/markets/{slug}/book`` and ``/v1/markets/{slug}/bbo`` all returned 200.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import cast

from .errors import PolymarketHTTPError, PolymarketPayloadError
from .transport import HttpResponse, Transport, UrllibTransport

PROD_BASE_URL = "https://gateway.polymarket.us/v1"
DEFAULT_TIMEOUT_SECONDS = 10.0

_JsonObject = dict[str, object]


class PolymarketClient:
    """Fetches raw JSON objects from the Polymarket US market-data REST API."""

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

    # -- public endpoints ---------------------------------------------------

    def list_markets(
        self,
        *,
        active: bool | None = None,
        closed: bool | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> _JsonObject:
        """``GET /markets`` — market discovery. Returns the raw ``{markets: [...]}`` object."""
        params: dict[str, object] = {
            "active": _bool_param(active),
            "closed": _bool_param(closed),
            "archived": _bool_param(archived),
            "limit": limit,
            "offset": offset,
        }
        return self._get_json("/markets", params)

    def get_market_by_slug(self, slug: str) -> _JsonObject:
        """``GET /market/slug/{slug}`` — returns the inner ``market`` object."""
        self._require_slug(slug)
        payload = self._get_json(f"/market/slug/{urllib.parse.quote(slug)}", None)
        return _unwrap(payload, "market", ctx=f"GET /market/slug/{slug}")

    def list_events(
        self,
        *,
        active: bool | None = None,
        closed: bool | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> _JsonObject:
        """``GET /events`` — public parent-event metadata with nested markets."""
        return self._get_json(
            "/events",
            {
                "active": _bool_param(active),
                "closed": _bool_param(closed),
                "archived": _bool_param(archived),
                "limit": limit,
                "offset": offset,
            },
        )

    def get_market_by_id(self, market_id: str) -> _JsonObject:
        """``GET /market/id/{id}`` — returns the inner ``market`` object."""
        if not market_id or not market_id.strip():
            raise ValueError("market_id must be a non-empty string")
        payload = self._get_json(f"/market/id/{urllib.parse.quote(market_id)}", None)
        return _unwrap(payload, "market", ctx=f"GET /market/id/{market_id}")

    def get_book(self, slug: str) -> _JsonObject:
        """``GET /markets/{slug}/book`` — returns the inner ``marketData`` object."""
        self._require_slug(slug)
        payload = self._get_json(f"/markets/{urllib.parse.quote(slug)}/book", None)
        return _unwrap(payload, "marketData", ctx=f"GET /markets/{slug}/book")

    def get_bbo(self, slug: str) -> _JsonObject:
        """``GET /markets/{slug}/bbo`` — returns the inner ``marketData`` object."""
        self._require_slug(slug)
        payload = self._get_json(f"/markets/{urllib.parse.quote(slug)}/bbo", None)
        return _unwrap(payload, "marketData", ctx=f"GET /markets/{slug}/bbo")

    # -- internals --------------------------------------------------------

    @staticmethod
    def _require_slug(slug: str) -> None:
        if not slug or not slug.strip():
            raise ValueError("slug must be a non-empty string")

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
            raise PolymarketPayloadError(
                f"GET {path}: response body is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise PolymarketPayloadError(
                f"GET {path}: expected a JSON object, got {type(parsed).__name__}"
            )
        return cast("_JsonObject", parsed)


def _bool_param(value: bool | None) -> str | None:
    if value is None:
        return None
    return "true" if value else "false"


def _unwrap(payload: _JsonObject, key: str, *, ctx: str) -> _JsonObject:
    inner = payload.get(key)
    if not isinstance(inner, dict):
        raise PolymarketPayloadError(f"{ctx}: response is missing the {key!r} object")
    return cast("_JsonObject", inner)


def _http_error(response: HttpResponse) -> PolymarketHTTPError:
    """Build a ``PolymarketHTTPError`` from the gRPC-style ``{code, message}`` body if present."""
    code: int | None = None
    message: str | None = None
    try:
        parsed: object = json.loads(response.body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        raw_code = parsed.get("code")
        raw_message = parsed.get("message")
        code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
        message = raw_message if isinstance(raw_message, str) else None
    return PolymarketHTTPError(status=response.status, code=code, message=message)
