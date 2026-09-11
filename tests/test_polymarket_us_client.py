"""Offline tests for the Polymarket US REST client (HTTP concerns only)."""

from __future__ import annotations

import pytest
from polymarket_us_support import FakeTransport, json_response, load_fixture_bytes

from prediction_market_arbitrage.adapters.polymarket_us import (
    HttpResponse,
    PolymarketClient,
    PolymarketHTTPError,
    PolymarketPayloadError,
    PolymarketTimeoutError,
    PolymarketTransportError,
)

BASE = "https://gateway.example.test/v1"


def _client(transport: FakeTransport) -> PolymarketClient:
    return PolymarketClient(base_url=BASE, transport=transport, timeout=5.0)


def test_list_markets_builds_query_and_returns_object() -> None:
    body = json_response(200, {"markets": []})
    transport = FakeTransport(routes=[("/markets", body)])
    result = _client(transport).list_markets(active=True, closed=False, limit=3)

    assert result == {"markets": []}
    url = transport.calls[0]
    assert url.startswith(f"{BASE}/markets?")
    assert "active=true" in url
    assert "closed=false" in url
    assert "limit=3" in url
    assert "archived" not in url  # None params dropped


def test_get_market_by_slug_unwraps_market() -> None:
    transport = FakeTransport(
        routes=[("/market/slug/", json_response(200, {"market": {"slug": "abc"}}))]
    )
    assert _client(transport).get_market_by_slug("abc") == {"slug": "abc"}


def test_list_events_builds_public_parent_metadata_query() -> None:
    body = json_response(200, {"events": []})
    transport = FakeTransport(routes=[("/events", body)])

    result = _client(transport).list_events(
        active=True, closed=False, archived=False, limit=100, offset=200
    )

    assert result == {"events": []}
    url = transport.calls[0]
    assert url.startswith(f"{BASE}/events?")
    assert "active=true" in url
    assert "closed=false" in url
    assert "archived=false" in url
    assert "limit=100" in url
    assert "offset=200" in url


def test_get_book_unwraps_market_data() -> None:
    transport = FakeTransport(
        routes=[("/book", json_response(200, {"marketData": {"marketSlug": "abc"}}))]
    )
    assert _client(transport).get_book("abc") == {"marketSlug": "abc"}


def test_get_bbo_path() -> None:
    transport = FakeTransport(
        routes=[("/bbo", json_response(200, {"marketData": {"marketSlug": "abc"}}))]
    )
    _client(transport).get_bbo("abc")
    assert transport.calls[0] == f"{BASE}/markets/abc/bbo"


def test_missing_wrapper_key_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/book", json_response(200, {"nope": 1}))])
    with pytest.raises(PolymarketPayloadError):
        _client(transport).get_book("abc")


@pytest.mark.parametrize("slug", ["", "   "])
def test_blank_slug_rejected(slug: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        _client(FakeTransport()).get_book(slug)


def test_http_404_extracts_grpc_code() -> None:
    transport = FakeTransport(
        routes=[("/market/slug/", HttpResponse(404, load_fixture_bytes("error_not_found.json")))]
    )
    with pytest.raises(PolymarketHTTPError) as excinfo:
        _client(transport).get_market_by_slug("missing")
    assert excinfo.value.status == 404
    assert excinfo.value.code == 5


def test_http_500_raises_http_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(500, b"upstream boom"))])
    with pytest.raises(PolymarketHTTPError) as excinfo:
        _client(transport).list_markets()
    assert excinfo.value.status == 500


def test_invalid_json_body_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(200, b"{not json"))])
    with pytest.raises(PolymarketPayloadError):
        _client(transport).list_markets()


def test_non_object_json_body_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(200, b"[1,2,3]"))])
    with pytest.raises(PolymarketPayloadError):
        _client(transport).list_markets()


def test_timeout_propagates() -> None:
    transport = FakeTransport(raises=PolymarketTimeoutError("timed out"))
    with pytest.raises(PolymarketTimeoutError):
        _client(transport).get_book("abc")


def test_transport_error_propagates() -> None:
    transport = FakeTransport(raises=PolymarketTransportError("connection refused"))
    with pytest.raises(PolymarketTransportError):
        _client(transport).get_market_by_slug("abc")


def test_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PolymarketClient(base_url=BASE, transport=FakeTransport(), timeout=0)
