"""Offline tests for the Kalshi REST client (HTTP concerns only)."""

from __future__ import annotations

import pytest
from kalshi_support import FakeTransport, json_response, load_fixture_bytes

from prediction_market_arbitrage.adapters.kalshi import (
    HttpResponse,
    KalshiClient,
    KalshiHTTPError,
    KalshiPayloadError,
    KalshiTimeoutError,
    KalshiTransportError,
)

BASE = "https://example.test/trade-api/v2"


def _client(transport: FakeTransport) -> KalshiClient:
    return KalshiClient(base_url=BASE, transport=transport, timeout=5.0)


def test_list_markets_builds_query_string_and_returns_object() -> None:
    body = json_response(200, {"markets": [], "cursor": ""})
    transport = FakeTransport(routes=[("/markets", body)])
    result = _client(transport).list_markets(status="open", limit=3, series_ticker="KXHIGHNY")

    assert result == {"markets": [], "cursor": ""}
    url = transport.calls[0]
    assert url.startswith(f"{BASE}/markets?")
    assert "status=open" in url
    assert "limit=3" in url
    assert "series_ticker=KXHIGHNY" in url
    assert "event_ticker" not in url  # None params are dropped


def test_get_market_unwraps_market_object() -> None:
    transport = FakeTransport(
        routes=[("/markets/", json_response(200, {"market": {"ticker": "T"}}))]
    )
    assert _client(transport).get_market("T") == {"ticker": "T"}


def test_get_market_missing_market_key_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/markets/", json_response(200, {"nope": 1}))])
    with pytest.raises(KalshiPayloadError):
        _client(transport).get_market("T")


def test_orderbook_path_and_depth_param() -> None:
    body = json_response(200, {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
    transport = FakeTransport(routes=[("/orderbook", body)])
    _client(transport).get_market_orderbook("KXHIGHNY-26SEP06-T73", depth=10)
    url = transport.calls[0]
    assert url.startswith(f"{BASE}/markets/KXHIGHNY-26SEP06-T73/orderbook")
    assert "depth=10" in url


@pytest.mark.parametrize("ticker", ["", "   "])
def test_blank_ticker_rejected(ticker: str) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError, match="ticker"):
        _client(transport).get_market(ticker)


def test_http_500_raises_http_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(500, b"upstream boom"))])
    with pytest.raises(KalshiHTTPError) as excinfo:
        _client(transport).list_markets()
    assert excinfo.value.status == 500


def test_http_404_extracts_kalshi_error_code() -> None:
    transport = FakeTransport(
        routes=[("/markets/", HttpResponse(404, load_fixture_bytes("error_not_found.json")))]
    )
    with pytest.raises(KalshiHTTPError) as excinfo:
        _client(transport).get_market("NOPE-DOES-NOT-EXIST")
    assert excinfo.value.status == 404
    assert excinfo.value.code == "not_found"


def test_invalid_json_body_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(200, b"{not json"))])
    with pytest.raises(KalshiPayloadError):
        _client(transport).list_markets()


def test_non_object_json_body_is_payload_error() -> None:
    transport = FakeTransport(routes=[("/markets", HttpResponse(200, b"[1, 2, 3]"))])
    with pytest.raises(KalshiPayloadError):
        _client(transport).list_markets()


def test_timeout_from_transport_propagates() -> None:
    transport = FakeTransport(raises=KalshiTimeoutError("timed out"))
    with pytest.raises(KalshiTimeoutError):
        _client(transport).list_markets()


def test_transport_error_propagates() -> None:
    transport = FakeTransport(raises=KalshiTransportError("connection refused"))
    with pytest.raises(KalshiTransportError):
        _client(transport).get_market("T")


def test_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout"):
        KalshiClient(base_url=BASE, transport=FakeTransport(), timeout=0)
