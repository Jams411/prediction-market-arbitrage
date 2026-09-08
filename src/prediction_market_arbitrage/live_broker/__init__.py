"""Live-broker interface boundary (Milestone M3.4).

Defines a **venue-agnostic** submit / cancel / order-status / positions
interface (:class:`LiveBroker`), a non-bypassable **live-trading gate**
(disabled by default, armable only with an explicit awkward phrase — never
``"1"`` / ``"true"``), an interface-boundary **duplicate-order guard**, and
isolated, redacted **trading credentials**.

No venue operation is implemented: ``docs/API_SOURCES.md`` has primary evidence
for market data only, so :class:`KalshiLiveBroker` and
:class:`PolymarketUsLiveBroker` raise :class:`UnsupportedLiveOperationError` for
every call. ``LIVE_TRADING`` stays ``False`` by default; real-money trading
stays disabled (``docs/DECISIONS.md`` D-002 / D-023, ROADMAP "Real-money gate").
"""

from __future__ import annotations

from .credentials import (
    KalshiTradingCredentials,
    PolymarketUsTradingCredentials,
    kalshi_trading_credentials_from_env,
    polymarket_us_trading_credentials_from_env,
)
from .errors import (
    DuplicateOrderError,
    LiveBrokerCredentialError,
    LiveBrokerError,
    LiveTradingDisabledError,
    UnsupportedLiveOperationError,
)
from .gate import (
    LIVE_TRADING_ENABLED,
    LIVE_TRADING_ENV_VAR,
    REQUIRED_PHRASE,
    LiveTradingGate,
)
from .idempotency import IdempotencyGuard
from .interface import LiveBroker
from .kalshi import KalshiLiveBroker
from .models import (
    CancelRequest,
    LiveOrderAck,
    LiveOrderRequest,
    LiveOrderState,
    LiveOrderStatus,
    LivePosition,
)
from .polymarket_us import PolymarketUsLiveBroker

__all__ = [
    "LIVE_TRADING_ENABLED",
    "LIVE_TRADING_ENV_VAR",
    "REQUIRED_PHRASE",
    "CancelRequest",
    "DuplicateOrderError",
    "IdempotencyGuard",
    "KalshiLiveBroker",
    "KalshiTradingCredentials",
    "LiveBroker",
    "LiveBrokerCredentialError",
    "LiveBrokerError",
    "LiveOrderAck",
    "LiveOrderRequest",
    "LiveOrderState",
    "LiveOrderStatus",
    "LivePosition",
    "LiveTradingDisabledError",
    "LiveTradingGate",
    "PolymarketUsLiveBroker",
    "PolymarketUsTradingCredentials",
    "UnsupportedLiveOperationError",
    "kalshi_trading_credentials_from_env",
    "polymarket_us_trading_credentials_from_env",
]
