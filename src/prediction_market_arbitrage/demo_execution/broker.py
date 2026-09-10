"""``KalshiDemoLiveBroker`` — a concrete :class:`~..live_broker.LiveBroker` that
actually submits, cancels, and reads orders **against Kalshi DEMO only** (M3.5).

It reuses the shipped safety wrapper unchanged: every call still runs
``LiveTradingGate.assert_live_allowed`` and, for submit,
``IdempotencyGuard.register`` *before* reaching the venue hooks here (see
``live_broker.interface``). What this class adds is the demo REST mapping — the
K-TR-05 create-order body, the K-TR-06 / K-TR-08 response → venue-neutral value
objects — over an injected :class:`~.transport.DemoTransport`.

Why a new class rather than making ``KalshiLiveBroker`` work: that class is,
by decision (D-023 / A-037), a boundary with **no** implemented operation
because no *production* order endpoint has primary evidence. The demo endpoints
*are* evidence-backed (K-TR-04..10, OBSERVED K-TR-OBS-26..33), and this class is
hard-pinned to the demo host by :func:`~.transport.assert_demo_host` at
construction, so it can never act on production. Production live trading remains
disabled (D-002); ``LIVE_TRADING`` is never read or set here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from prediction_market_arbitrage.live_broker import (
    CancelRequest,
    DuplicateOrderError,
    IdempotencyGuard,
    LiveBroker,
    LiveOrderAck,
    LiveOrderRequest,
    LiveOrderState,
    LiveOrderStatus,
    LivePosition,
    LiveTradingGate,
)

from .errors import DemoCapabilityError, DemoExecutionError
from .transport import DemoTransport, assert_demo_host

_TIME_IN_FORCE = {
    "gtc": "good_till_canceled",
    "ioc": "immediate_or_cancel",
    "fok": "fill_or_kill",
}
_SIDE = {"buy": "bid", "sell": "ask"}

_KALSHI_STATUS = {
    "executed": LiveOrderState.FILLED,
    "canceled": LiveOrderState.CANCELED,
    "cancelled": LiveOrderState.CANCELED,
}


def _plain(value: Decimal) -> str:
    """Fixed-point string with no exponent — Kalshi wants ``"1"`` / ``"0.01"``."""
    return format(value.normalize(), "f")


def _ticker_of(contract_id: str) -> str:
    """``"KXFOO-…:YES"`` -> ``"KXFOO-…"`` (the venue market ticker)."""
    head = contract_id.rsplit(":", 1)[0]
    if not head:
        raise DemoExecutionError(f"cannot derive a Kalshi ticker from contract_id {contract_id!r}")
    return head


def _to_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _str_map(body: Mapping[str, Any]) -> dict[str, str]:
    """Flatten a venue body to ``str``/``str`` for :attr:`LiveOrderAck.raw`
    (structural echo only; the orchestrator is responsible for sanitising
    anything it persists)."""
    return {str(k): str(v) for k, v in body.items() if not isinstance(v, (dict, list))}


@dataclass(frozen=True, slots=True)
class _SubmittedRef:
    order_id: str
    market_ticker: str


class KalshiDemoLiveBroker(LiveBroker):
    """Kalshi **DEMO** live broker. Host-pinned at construction."""

    venue = "kalshi"

    def __init__(
        self,
        transport: DemoTransport,
        *,
        gate: LiveTradingGate | None = None,
        idempotency: IdempotencyGuard | None = None,
    ) -> None:
        assert_demo_host(getattr(transport, "base_url", ""))
        super().__init__(gate=gate, idempotency=idempotency)
        self._transport = transport
        #: client_order_id -> (venue order_id, market_ticker), filled on submit so
        #: a later cancel / status read can route to the order's exchange shard.
        self._submitted: dict[str, _SubmittedRef] = {}

    # -- helpers ---------------------------------------------------------- #

    def _order_body(self, request: LiveOrderRequest) -> dict[str, Any]:
        if request.venue != self.venue:
            raise DemoExecutionError(
                f"request.venue {request.venue!r} is not {self.venue!r}"
            )
        body: dict[str, Any] = {
            "ticker": _ticker_of(request.contract_id),
            "side": _SIDE[request.side],
            "count": _plain(request.quantity),
            "time_in_force": _TIME_IN_FORCE[request.time_in_force],
            "self_trade_prevention_type": "maker",
            "client_order_id": request.client_order_id,
        }
        if request.order_type == "limit":
            assert request.limit_price is not None  # guaranteed by LiveOrderRequest
            body["price"] = _plain(request.limit_price)
        # `exchange_index` deliberately omitted -> Kalshi auto-routes by ticker
        # (K-TR-14); a `…-SHARDn-…` ticker lands on shard n.
        return body

    def _ref(self, client_order_id: str) -> _SubmittedRef:
        ref = self._submitted.get(client_order_id)
        if ref is None:
            raise DemoCapabilityError(
                f"no submitted order tracked for client_order_id {client_order_id!r} — "
                "cannot route a demo cancel / status read"
            )
        return ref

    # -- venue hooks (called by LiveBroker after gate + idempotency) ---- #

    def _do_submit(self, request: LiveOrderRequest, *, now: datetime) -> LiveOrderAck:
        resp = self._transport.create_order(self._order_body(request))
        if resp.status == 409:
            # venue-side dedupe (K-TR-07 / K-TR-OBS-29). The local IdempotencyGuard
            # already ran; this covers a key reused across processes.
            raise DuplicateOrderError(
                f"Kalshi demo rejected duplicate client_order_id "
                f"{request.client_order_id!r} (HTTP 409)"
            )
        if not resp.ok:
            return LiveOrderAck(
                client_order_id=request.client_order_id,
                venue_order_id=None,
                state=LiveOrderState.REJECTED,
                accepted=False,
                as_of=now,
                raw=_str_map(resp.body),
            )
        order_id = resp.body.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            # 2xx with no usable id -> we cannot track or cancel the order.
            raise DemoCapabilityError(
                f"Kalshi demo create returned HTTP {resp.status} without an 'order_id'; "
                "refusing to treat the order as placed"
            )
        ticker = _ticker_of(request.contract_id)
        self._submitted[request.client_order_id] = _SubmittedRef(order_id, ticker)
        fill_count = _to_decimal(resp.body.get("fill_count"))
        remaining = _to_decimal(resp.body.get("remaining_count"))
        return LiveOrderAck(
            client_order_id=request.client_order_id,
            venue_order_id=order_id,
            state=_submit_state(fill_count, remaining),
            accepted=True,
            as_of=now,
            raw=_str_map(resp.body),
        )

    def _do_cancel(self, request: CancelRequest, *, now: datetime) -> LiveOrderAck:
        ref = self._ref(request.client_order_id)
        order_id = request.venue_order_id or ref.order_id
        resp = self._transport.cancel_order(order_id, market_ticker=ref.market_ticker)
        return LiveOrderAck(
            client_order_id=request.client_order_id,
            venue_order_id=order_id,
            state=LiveOrderState.CANCELED if resp.ok else LiveOrderState.UNKNOWN,
            accepted=resp.ok,
            as_of=now,
            raw=_str_map(resp.body),
        )

    def _do_get_order(self, client_order_id: str, *, now: datetime) -> LiveOrderStatus:
        ref = self._ref(client_order_id)
        resp = self._transport.get_order(ref.order_id, market_ticker=ref.market_ticker)
        if not resp.ok:
            raise DemoCapabilityError(
                f"Kalshi demo order-status read returned HTTP {resp.status} for "
                f"{client_order_id!r} — state unavailable, failing closed"
            )
        order = resp.body.get("order")
        payload: Mapping[str, Any] = order if isinstance(order, Mapping) else resp.body
        raw_status = payload.get("status")
        filled = _to_decimal(payload.get("fill_count_fp"))
        remaining = _to_decimal(payload.get("remaining_count_fp"))
        if not isinstance(raw_status, str) or filled is None or remaining is None:
            raise DemoCapabilityError(
                f"Kalshi demo order-status for {client_order_id!r} is missing "
                "status / fill_count_fp / remaining_count_fp — ambiguous, failing closed"
            )
        state = _KALSHI_STATUS.get(raw_status)
        if state is None:  # 'resting'
            state = (
                LiveOrderState.PARTIALLY_FILLED if filled > 0 else LiveOrderState.SUBMITTED
            )
        return LiveOrderStatus(
            client_order_id=client_order_id,
            venue_order_id=ref.order_id,
            state=state,
            filled_quantity=filled,
            remaining_quantity=remaining,
            average_fill_price=None,  # not on the K-TR-08 order schema
            as_of=now,
        )

    def _do_get_positions(self, *, now: datetime) -> tuple[LivePosition, ...]:
        resp = self._transport.get_positions()
        if not resp.ok:
            raise DemoCapabilityError(
                f"Kalshi demo positions read returned HTTP {resp.status} — failing closed"
            )
        rows = resp.body.get("market_positions")
        if not isinstance(rows, list):
            raise DemoCapabilityError(
                "Kalshi demo positions body has no 'market_positions' array — ambiguous"
            )
        out: list[LivePosition] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise DemoCapabilityError("a market_positions row is not an object — ambiguous")
            ticker = row.get("ticker")
            quantity = _to_decimal(row.get("position_fp"))
            if not isinstance(ticker, str) or quantity is None:
                raise DemoCapabilityError(
                    "a market_positions row is missing ticker / position_fp — failing closed"
                )
            out.append(
                LivePosition(
                    venue=self.venue,
                    contract_id=ticker,
                    quantity=quantity,
                    average_price=None,
                    as_of=now,
                )
            )
        return tuple(out)


def _submit_state(
    fill_count: Decimal | None, remaining: Decimal | None
) -> LiveOrderState:
    """Map the K-TR-06 create response (which carries **no** lifecycle status)
    to a state, never assuming 'filled' without evidence."""
    if fill_count is None:
        return LiveOrderState.SUBMITTED  # no counts on the ack -> reconcile later
    if fill_count <= 0:
        return LiveOrderState.SUBMITTED
    if remaining is not None and remaining > 0:
        return LiveOrderState.PARTIALLY_FILLED
    return LiveOrderState.FILLED
