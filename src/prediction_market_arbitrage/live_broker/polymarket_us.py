"""Polymarket US live-broker boundary (Milestone M3.4) — defined, not implemented.

``docs/API_SOURCES.md`` has primary evidence for Polymarket US **market data
only** (P-01..P-14 are ``/v1/markets*`` GETs; the WebSocket entries are the
market-data channel). There is **no** captured or documented request/response
shape for order placement, cancellation, order status, or positions — and
A-015 (slug-only identifiers sufficient for order routing / reconciliation) is
itself unresolved. Per the M3.4 rule, every operation is an explicit
:class:`UnsupportedLiveOperationError` rather than a guess.

Credentials are still accepted and held (isolated, redacted); nothing signs or
sends.
"""

from __future__ import annotations

from datetime import datetime

from .credentials import PolymarketUsTradingCredentials
from .errors import UnsupportedLiveOperationError
from .gate import LiveTradingGate
from .idempotency import IdempotencyGuard
from .interface import LiveBroker
from .models import CancelRequest, LiveOrderAck, LiveOrderRequest, LiveOrderStatus, LivePosition

_EVIDENCE_GAP = (
    "no primary evidence for a Polymarket US order-placement / cancel / "
    "order-status / positions endpoint in docs/API_SOURCES.md (P-* entries "
    "cover market data only); A-015 (slug-only order routing) is unresolved. "
    "Boundary defined for M3.4; intentionally not implemented. See "
    "docs/ASSUMPTIONS.md A-037 / docs/DECISIONS.md D-023."
)


class PolymarketUsLiveBroker(LiveBroker):
    """The Polymarket US implementation of :class:`LiveBroker`. All operations
    raise :class:`UnsupportedLiveOperationError` — see module docstring."""

    venue = "polymarket_us"

    def __init__(
        self,
        credentials: PolymarketUsTradingCredentials,
        *,
        gate: LiveTradingGate | None = None,
        idempotency: IdempotencyGuard | None = None,
    ) -> None:
        if not isinstance(credentials, PolymarketUsTradingCredentials):
            raise TypeError(
                "PolymarketUsLiveBroker requires PolymarketUsTradingCredentials"
            )
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
