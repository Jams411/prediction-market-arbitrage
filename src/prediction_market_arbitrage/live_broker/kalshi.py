"""Kalshi live-broker boundary (Milestone M3.4) — defined, not implemented.

``docs/API_SOURCES.md`` has primary evidence for Kalshi **market data only**
(K-01..K-14 are ``/markets*`` GETs; the WebSocket entries are the market-data
``orderbook_delta`` channel). There is **no** captured or documented
request/response shape for order placement, cancellation, order status, or
portfolio/positions. Per the M3.4 rule, every operation is therefore an explicit
:class:`UnsupportedLiveOperationError` rather than a guess.

Credentials are still accepted and held (isolated, redacted) so the wiring shape
is ready; nothing signs or sends.
"""

from __future__ import annotations

from datetime import datetime

from .credentials import KalshiTradingCredentials
from .errors import UnsupportedLiveOperationError
from .gate import LiveTradingGate
from .idempotency import IdempotencyGuard
from .interface import LiveBroker
from .models import CancelRequest, LiveOrderAck, LiveOrderRequest, LiveOrderStatus, LivePosition

_EVIDENCE_GAP = (
    "no primary evidence for a Kalshi order-placement / cancel / order-status / "
    "positions endpoint in docs/API_SOURCES.md (K-* entries cover market data "
    "only). Boundary defined for M3.4; intentionally not implemented. See "
    "docs/ASSUMPTIONS.md A-037 / docs/DECISIONS.md D-023."
)


class KalshiLiveBroker(LiveBroker):
    """The Kalshi implementation of :class:`LiveBroker`. All operations raise
    :class:`UnsupportedLiveOperationError` — see module docstring."""

    venue = "kalshi"

    def __init__(
        self,
        credentials: KalshiTradingCredentials,
        *,
        gate: LiveTradingGate | None = None,
        idempotency: IdempotencyGuard | None = None,
    ) -> None:
        if not isinstance(credentials, KalshiTradingCredentials):
            raise TypeError("KalshiLiveBroker requires KalshiTradingCredentials")
        super().__init__(gate=gate, idempotency=idempotency)
        self._credentials = credentials

    def _unsupported(self, operation: str) -> UnsupportedLiveOperationError:
        return UnsupportedLiveOperationError(
            venue=self.venue, operation=operation, reason=_EVIDENCE_GAP
        )

    def _do_submit(self, request: LiveOrderRequest, *, now: datetime) -> LiveOrderAck:
        raise self._unsupported("submit_order")

    def _do_cancel(self, request: CancelRequest, *, now: datetime) -> LiveOrderAck:
        raise self._unsupported("cancel_order")

    def _do_get_order(self, client_order_id: str, *, now: datetime) -> LiveOrderStatus:
        raise self._unsupported("get_order")

    def _do_get_positions(self, *, now: datetime) -> tuple[LivePosition, ...]:
        raise self._unsupported("get_positions")
