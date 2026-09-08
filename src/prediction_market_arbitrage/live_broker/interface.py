"""The venue-agnostic live-broker interface (Milestone M3.4).

:class:`LiveBroker` is the boundary the rest of the system would call to place,
cancel, and reconcile **real** orders. This module defines the shape and the
non-bypassable safety wrapper; it implements no venue.

Every public method of :class:`LiveBroker`:

1. checks the injected :class:`~.gate.LiveTradingGate` (default: disabled) —
   ``LiveTradingDisabledError`` if not armed;
2. for ``submit_order``, registers the ``client_order_id`` with the
   :class:`~.idempotency.IdempotencyGuard` — ``DuplicateOrderError`` on a repeat;
3. only then delegates to the subclass hook (``_do_*``).

A subclass therefore cannot forget the gate or the dedupe check. The concrete
venue subclasses (:mod:`.kalshi`, :mod:`.polymarket_us`) implement the hooks as
explicit ``UnsupportedLiveOperationError`` raises — no order endpoint has
primary evidence (``docs/API_SOURCES.md``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .errors import LiveBrokerError
from .gate import LiveTradingGate
from .idempotency import IdempotencyGuard
from .models import (
    CancelRequest,
    LiveOrderAck,
    LiveOrderRequest,
    LiveOrderStatus,
    LivePosition,
)


def _require_aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LiveBrokerError(f"{name} must be a timezone-aware datetime")
    return value


class LiveBroker(ABC):
    """Venue-agnostic submit / cancel / order-status / positions boundary.

    Subclasses set :attr:`venue` and implement the ``_do_*`` hooks. Construction
    defaults to a **disabled** gate, so a freshly built broker cannot trade.
    """

    #: Set by each concrete subclass (e.g. ``"kalshi"``).
    venue: str = ""

    def __init__(
        self,
        *,
        gate: LiveTradingGate | None = None,
        idempotency: IdempotencyGuard | None = None,
    ) -> None:
        if not self.venue:
            raise LiveBrokerError("LiveBroker subclass must set a non-empty `venue`")
        self._gate = gate if gate is not None else LiveTradingGate.disabled()
        self._idempotency = idempotency if idempotency is not None else IdempotencyGuard()

    @property
    def gate(self) -> LiveTradingGate:
        return self._gate

    @property
    def live_trading_active(self) -> bool:
        return self._gate.active

    # -- public boundary (gate + dedupe enforced here, once) ------------ #

    def submit_order(self, request: LiveOrderRequest, *, now: datetime) -> LiveOrderAck:
        if not isinstance(request, LiveOrderRequest):
            raise LiveBrokerError("submit_order requires a LiveOrderRequest")
        _require_aware(now, name="now")
        if request.venue != self.venue:
            raise LiveBrokerError(
                f"request.venue {request.venue!r} does not match broker venue {self.venue!r}"
            )
        self._gate.assert_live_allowed(operation="submit_order")
        self._idempotency.register(request.client_order_id)
        return self._do_submit(request, now=now)

    def cancel_order(self, request: CancelRequest, *, now: datetime) -> LiveOrderAck:
        if not isinstance(request, CancelRequest):
            raise LiveBrokerError("cancel_order requires a CancelRequest")
        _require_aware(now, name="now")
        self._gate.assert_live_allowed(operation="cancel_order")
        return self._do_cancel(request, now=now)

    def get_order(self, client_order_id: str, *, now: datetime) -> LiveOrderStatus:
        if not isinstance(client_order_id, str) or not client_order_id.strip():
            raise LiveBrokerError("client_order_id must be a non-empty string")
        _require_aware(now, name="now")
        self._gate.assert_live_allowed(operation="get_order")
        return self._do_get_order(client_order_id, now=now)

    def get_positions(self, *, now: datetime) -> tuple[LivePosition, ...]:
        _require_aware(now, name="now")
        self._gate.assert_live_allowed(operation="get_positions")
        return self._do_get_positions(now=now)

    # -- subclass hooks ------------------------------------------------- #

    @abstractmethod
    def _do_submit(self, request: LiveOrderRequest, *, now: datetime) -> LiveOrderAck: ...

    @abstractmethod
    def _do_cancel(self, request: CancelRequest, *, now: datetime) -> LiveOrderAck: ...

    @abstractmethod
    def _do_get_order(self, client_order_id: str, *, now: datetime) -> LiveOrderStatus: ...

    @abstractmethod
    def _do_get_positions(self, *, now: datetime) -> tuple[LivePosition, ...]: ...
