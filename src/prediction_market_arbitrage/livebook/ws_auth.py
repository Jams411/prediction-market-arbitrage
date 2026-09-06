"""Pure builders for the authenticated market-data WebSocket handshakes and
subscribe commands (Milestone M2.1).

Everything here is deterministic given an injected timestamp and an injected
:class:`Signer`. No sockets, no ``cryptography`` import — the RSA-PSS (Kalshi) /
Ed25519 (Polymarket US) signature is produced by the caller's ``Signer`` and
passed back in.

Evidence (``docs/API_SOURCES.md`` K-WS-AUTH-*, P-WS-AUTH-*):

Kalshi — ``docs.kalshi.com/getting_started/quick_start_websockets`` +
``.../quick_start_authenticated_requests``:
- URL ``wss://external-api-ws.kalshi.com/trade-api/ws/v2`` (prod),
  ``wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`` (demo).
- Headers ``KALSHI-ACCESS-KEY`` / ``KALSHI-ACCESS-TIMESTAMP`` (ms) /
  ``KALSHI-ACCESS-SIGNATURE`` (base64).
- Sign message: ``timestamp + "GET" + "/trade-api/ws/v2"``; RSA-PSS(MGF1-SHA256,
  salt = digest length) over SHA-256.

Polymarket US — ``docs.polymarket.us/api-reference/websocket/overview`` +
``.../authentication``:
- URL ``wss://api.polymarket.us/v1/ws/markets``.
- Headers ``X-PM-Access-Key`` / ``X-PM-Timestamp`` (ms) / ``X-PM-Signature``
  (base64).
- Sign message: ``timestamp + "GET" + "/v1/ws/markets"``; Ed25519.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .credentials import KalshiCredentials, PolymarketUsCredentials
from .errors import LiveBookError
from .updates import require_aware_dt

# --------------------------------------------------------------------------- #
# Endpoints (verified from docs)
# --------------------------------------------------------------------------- #

KALSHI_WS_URL_PROD = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
KALSHI_WS_URL_DEMO = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
KALSHI_WS_SIGN_PATH = "/trade-api/ws/v2"

POLYMARKET_US_WS_MARKETS_URL = "wss://api.polymarket.us/v1/ws/markets"
POLYMARKET_US_WS_MARKETS_SIGN_PATH = "/v1/ws/markets"

KALSHI_ORDERBOOK_CHANNEL = "orderbook_delta"
POLYMARKET_US_MARKET_DATA_SUBSCRIPTION = "SUBSCRIPTION_TYPE_MARKET_DATA"


class Signer(Protocol):
    """Signs the handshake message with the venue's private key.

    ``sign`` returns the **raw** signature bytes (this module base64-encodes
    them). Implementations live in the caller's code so this package needs no
    cryptography dependency — e.g. a Kalshi signer wraps
    ``cryptography``'s RSA-PSS/SHA256, a Polymarket US signer wraps Ed25519.
    """

    def sign(self, message: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class Handshake:
    """Everything needed to open one authenticated WebSocket connection."""

    url: str
    headers: dict[str, str]


def _timestamp_ms(now: datetime) -> str:
    require_aware_dt(now, field="now")
    return str(int(now.timestamp() * 1000))


def _sign_b64(signer: Signer, message: str) -> str:
    raw = signer.sign(message.encode("utf-8"))
    if not isinstance(raw, bytes) or not raw:
        raise LiveBookError("Signer.sign must return non-empty bytes")
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------- #
# Kalshi
# --------------------------------------------------------------------------- #


def kalshi_ws_sign_message(timestamp_ms: str, *, sign_path: str = KALSHI_WS_SIGN_PATH) -> str:
    """``timestamp + "GET" + path`` — the exact string Kalshi signs."""
    return f"{timestamp_ms}GET{sign_path}"


def kalshi_ws_handshake(
    credentials: KalshiCredentials,
    signer: Signer,
    *,
    now: datetime,
    url: str = KALSHI_WS_URL_PROD,
    sign_path: str = KALSHI_WS_SIGN_PATH,
) -> Handshake:
    """Build the Kalshi WS :class:`Handshake` (URL + 3 ``KALSHI-ACCESS-*`` headers)."""
    timestamp = _timestamp_ms(now)
    signature = _sign_b64(signer, kalshi_ws_sign_message(timestamp, sign_path=sign_path))
    return Handshake(
        url=url,
        headers={
            "KALSHI-ACCESS-KEY": credentials.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        },
    )


def kalshi_subscribe_command(
    *, command_id: int, market_tickers: Sequence[str]
) -> dict[str, object]:
    """``{"id", "cmd": "subscribe", "params": {"channels": ["orderbook_delta"],
    "market_tickers": [...]}}`` (AsyncAPI ``subscribeCommand``)."""
    if not isinstance(command_id, int) or isinstance(command_id, bool) or command_id < 1:
        raise LiveBookError("kalshi_subscribe_command.command_id must be a positive int")
    tickers = [t for t in market_tickers]
    if not tickers or any(not isinstance(t, str) or not t for t in tickers):
        raise LiveBookError("kalshi_subscribe_command.market_tickers must be non-empty strings")
    return {
        "id": command_id,
        "cmd": "subscribe",
        "params": {"channels": [KALSHI_ORDERBOOK_CHANNEL], "market_tickers": tickers},
    }


# --------------------------------------------------------------------------- #
# Polymarket US
# --------------------------------------------------------------------------- #


def polymarket_us_ws_sign_message(
    timestamp_ms: str, *, sign_path: str = POLYMARKET_US_WS_MARKETS_SIGN_PATH
) -> str:
    """``timestamp + "GET" + path`` — the exact string Polymarket US signs."""
    return f"{timestamp_ms}GET{sign_path}"


def polymarket_us_ws_handshake(
    credentials: PolymarketUsCredentials,
    signer: Signer,
    *,
    now: datetime,
    url: str = POLYMARKET_US_WS_MARKETS_URL,
    sign_path: str = POLYMARKET_US_WS_MARKETS_SIGN_PATH,
) -> Handshake:
    """Build the Polymarket US Markets-WS :class:`Handshake` (URL + 3 ``X-PM-*`` headers)."""
    timestamp = _timestamp_ms(now)
    signature = _sign_b64(signer, polymarket_us_ws_sign_message(timestamp, sign_path=sign_path))
    return Handshake(
        url=url,
        headers={
            "X-PM-Access-Key": credentials.key_id,
            "X-PM-Timestamp": timestamp,
            "X-PM-Signature": signature,
        },
    )


def polymarket_us_subscribe_command(
    *, request_id: str, market_slugs: Sequence[str]
) -> dict[str, object]:
    """``{"subscribe": {"requestId", "subscriptionType":
    "SUBSCRIPTION_TYPE_MARKET_DATA", "marketSlugs": [...]}}`` (Markets-WS doc).

    The channel-specific "Markets WebSocket" page uses camelCase + the string
    enum; the API-overview page shows snake_case + an int enum. This follows the
    channel-specific page (P-WS-AUTH-03 records the discrepancy).
    """
    if not isinstance(request_id, str) or not request_id:
        raise LiveBookError("polymarket_us_subscribe_command.request_id must be a non-empty string")
    slugs = [s for s in market_slugs]
    if not slugs or any(not isinstance(s, str) or not s for s in slugs):
        raise LiveBookError(
            "polymarket_us_subscribe_command.market_slugs must be non-empty strings"
        )
    if len(slugs) > 100:
        raise LiveBookError(
            "polymarket_us_subscribe_command: at most 100 market slugs per subscription"
        )
    return {
        "subscribe": {
            "requestId": request_id,
            "subscriptionType": POLYMARKET_US_MARKET_DATA_SUBSCRIPTION,
            "marketSlugs": slugs,
        }
    }
