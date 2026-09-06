"""Deterministic tests for the M2.1 authenticated-handshake / subscribe builders.

Sign-message strings and headers follow the Kalshi and Polymarket US docs
(``docs/API_SOURCES.md`` K-WS-AUTH-*, P-WS-AUTH-*). No socket, no real key — the
signature comes from a fake :class:`StaticSigner`.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from livebook_support import (
    FAKE_KALSHI_KEY_ID,
    FAKE_KALSHI_PEM,
    FAKE_POLY_KEY_ID,
    FAKE_POLY_SECRET,
    StaticSigner,
)

from prediction_market_arbitrage.livebook import (
    KalshiCredentials,
    LiveBookError,
    PolymarketUsCredentials,
    kalshi_subscribe_command,
    kalshi_ws_handshake,
    kalshi_ws_sign_message,
    polymarket_us_subscribe_command,
    polymarket_us_ws_handshake,
    polymarket_us_ws_sign_message,
)

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
NOW_MS = str(int(NOW.timestamp() * 1000))


def test_kalshi_sign_message_is_timestamp_get_path() -> None:
    assert kalshi_ws_sign_message(NOW_MS) == f"{NOW_MS}GET/trade-api/ws/v2"


def test_polymarket_us_sign_message_is_timestamp_get_path() -> None:
    assert polymarket_us_ws_sign_message(NOW_MS) == f"{NOW_MS}GET/v1/ws/markets"


def test_kalshi_handshake_assembles_url_and_three_headers() -> None:
    signer = StaticSigner(b"kalshi-sig")
    handshake = kalshi_ws_handshake(
        KalshiCredentials(api_key_id=FAKE_KALSHI_KEY_ID, private_key_pem=FAKE_KALSHI_PEM),
        signer,
        now=NOW,
    )
    assert handshake.url == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    assert handshake.headers == {
        "KALSHI-ACCESS-KEY": FAKE_KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": NOW_MS,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(b"kalshi-sig").decode("ascii"),
    }
    assert signer.signed == [f"{NOW_MS}GET/trade-api/ws/v2".encode()]


def test_polymarket_us_handshake_assembles_url_and_three_headers() -> None:
    signer = StaticSigner(b"poly-sig")
    handshake = polymarket_us_ws_handshake(
        PolymarketUsCredentials(key_id=FAKE_POLY_KEY_ID, secret_key=FAKE_POLY_SECRET),
        signer,
        now=NOW,
    )
    assert handshake.url == "wss://api.polymarket.us/v1/ws/markets"
    assert handshake.headers == {
        "X-PM-Access-Key": FAKE_POLY_KEY_ID,
        "X-PM-Timestamp": NOW_MS,
        "X-PM-Signature": base64.b64encode(b"poly-sig").decode("ascii"),
    }
    assert signer.signed == [f"{NOW_MS}GET/v1/ws/markets".encode()]


def test_handshake_rejects_naive_datetime() -> None:
    with pytest.raises(LiveBookError, match="timezone-aware"):
        kalshi_ws_handshake(
            KalshiCredentials(api_key_id=FAKE_KALSHI_KEY_ID, private_key_pem=FAKE_KALSHI_PEM),
            StaticSigner(),
            now=datetime(2026, 2, 1, 12, 0, 0),  # noqa: DTZ001
        )


def test_handshake_rejects_empty_signature() -> None:
    with pytest.raises(LiveBookError, match="non-empty bytes"):
        polymarket_us_ws_handshake(
            PolymarketUsCredentials(key_id=FAKE_POLY_KEY_ID, secret_key=FAKE_POLY_SECRET),
            StaticSigner(b""),
            now=NOW,
        )


def test_kalshi_subscribe_command_shape() -> None:
    assert kalshi_subscribe_command(command_id=1, market_tickers=["A-1", "B-2"]) == {
        "id": 1,
        "cmd": "subscribe",
        "params": {"channels": ["orderbook_delta"], "market_tickers": ["A-1", "B-2"]},
    }


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"command_id": 0, "market_tickers": ["A"]}, "positive int"),
        ({"command_id": 1, "market_tickers": []}, "non-empty strings"),
        ({"command_id": 1, "market_tickers": ["A", ""]}, "non-empty strings"),
    ],
)
def test_kalshi_subscribe_command_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(LiveBookError, match=match):
        kalshi_subscribe_command(**kwargs)  # type: ignore[arg-type]


def test_polymarket_us_subscribe_command_shape() -> None:
    assert polymarket_us_subscribe_command(request_id="r1", market_slugs=["s-1"]) == {
        "subscribe": {
            "requestId": "r1",
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketSlugs": ["s-1"],
        }
    }


def test_polymarket_us_subscribe_command_rejects_over_100_slugs() -> None:
    with pytest.raises(LiveBookError, match="at most 100"):
        polymarket_us_subscribe_command(
            request_id="r1", market_slugs=[f"s-{i}" for i in range(101)]
        )
