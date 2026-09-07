"""Deterministic live order-book state from REST snapshots + WebSocket updates
(Milestone M2.1).

- :mod:`.updates` — venue-neutral :class:`BookSnapshot` / :class:`BookDelta`.
- :mod:`.state` — :class:`LiveBook` (one contract's price->qty index) and
  :class:`LiveBookFeed` (connection + sequencing + staleness + fail-closed
  :class:`FeedHealth`).
- :mod:`.kalshi_ws` / :mod:`.polymarket_us_ws` — pure decoders from each venue's
  WebSocket market-data frames.
- :mod:`.credentials` / :mod:`.ws_auth` — config-injected redacted credentials
  and pure builders for the authenticated handshake + subscribe commands.
- :mod:`.transport` — the socket seam (:class:`WebSocketTransport` /
  :class:`SnapshotSource` protocols), :class:`BackoffPolicy`, and
  :class:`LiveBookConnection` (connect / subscribe / pump / reconnect / REST
  resync). No networked socket is implemented — see the blocker in
  ``docs/API_SOURCES.md``.

No wall-clock: a caller feeds an injected ``clock``/``datetime``. See
``docs/DECISIONS.md`` D-014 and ``docs/API_SOURCES.md`` (K-WS-*, P-WS-*).
"""

from __future__ import annotations

from . import kalshi_ws, polymarket_us_ws
from .credentials import (
    KalshiCredentials,
    PolymarketUsCredentials,
    kalshi_credentials_from_env,
    polymarket_us_credentials_from_env,
)
from .errors import LiveBookError
from .state import (
    TRADEABLE_MARKET_STATES,
    ApplyResult,
    DeltaOutcome,
    FeedHealth,
    HealthStatus,
    LiveBook,
    LiveBookFeed,
)
from .transport import (
    BackoffPolicy,
    LiveBookConnection,
    SnapshotSource,
    TransportClosed,
    WebSocketTransport,
    kalshi_frame_decoder,
    polymarket_us_frame_decoder,
)
from .updates import BookDelta, BookSnapshot, Side
from .ws_auth import (
    Handshake,
    Signer,
    kalshi_subscribe_command,
    kalshi_ws_handshake,
    kalshi_ws_sign_message,
    polymarket_us_subscribe_command,
    polymarket_us_ws_handshake,
    polymarket_us_ws_sign_message,
)
from .ws_transport import WebsocketsTransport

__all__ = [
    "TRADEABLE_MARKET_STATES",
    "ApplyResult",
    "BackoffPolicy",
    "BookDelta",
    "BookSnapshot",
    "DeltaOutcome",
    "FeedHealth",
    "Handshake",
    "HealthStatus",
    "KalshiCredentials",
    "LiveBook",
    "LiveBookConnection",
    "LiveBookError",
    "LiveBookFeed",
    "PolymarketUsCredentials",
    "Side",
    "Signer",
    "SnapshotSource",
    "TransportClosed",
    "WebSocketTransport",
    "WebsocketsTransport",
    "kalshi_credentials_from_env",
    "kalshi_frame_decoder",
    "kalshi_subscribe_command",
    "kalshi_ws",
    "kalshi_ws_handshake",
    "kalshi_ws_sign_message",
    "polymarket_us_credentials_from_env",
    "polymarket_us_frame_decoder",
    "polymarket_us_subscribe_command",
    "polymarket_us_ws",
    "polymarket_us_ws_handshake",
    "polymarket_us_ws_sign_message",
]
