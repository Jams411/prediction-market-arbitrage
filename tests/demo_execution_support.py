"""Fakes for the M3.5 demo-execution tests. Not collected by pytest.

``FakeDemoTransport`` is an in-memory :class:`DemoTransport`: it records every
call and returns scripted :class:`DemoResponse`s. Nothing here touches a
network. The default ``base_url`` is a valid Kalshi **demo** host so the host
guard passes; tests that check the guard pass an explicit production URL.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from prediction_market_arbitrage.demo_execution import DemoResponse

T0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
DEMO_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
PROD_URL = "https://external-api.kalshi.com/trade-api/v2"

_Scripted = DemoResponse | list[DemoResponse] | Callable[..., DemoResponse]

_DEFAULT_CREATE = DemoResponse(
    201,
    {
        "order_id": "demo-ord-1",
        "client_order_id": "<echoed>",
        "fill_count": "0",
        "remaining_count": "1",
        "ts_ms": 1,
    },
)
_DEFAULT_CANCEL = DemoResponse(200, {"order_id": "demo-ord-1", "reduced_by": "1", "ts_ms": 2})
_DEFAULT_GET_ORDER = DemoResponse(
    200,
    {"order": {"status": "canceled", "fill_count_fp": "0", "remaining_count_fp": "0"}},
)
_DEFAULT_POSITIONS = DemoResponse(
    200, {"market_positions": [], "event_positions": [], "cursor": ""}
)
_DEFAULT_FILLS = DemoResponse(200, {"fills": [], "cursor": ""})


class FakeDemoTransport:
    """Scripted, call-recording :class:`DemoTransport`."""

    def __init__(
        self,
        *,
        base_url: str = DEMO_URL,
        create: _Scripted | None = None,
        cancel: _Scripted | None = None,
        get_order: _Scripted | None = None,
        positions: _Scripted | None = None,
        fills: _Scripted | None = None,
    ) -> None:
        self.base_url = base_url
        self._create = create if create is not None else _DEFAULT_CREATE
        self._cancel = cancel if cancel is not None else _DEFAULT_CANCEL
        self._get_order = get_order if get_order is not None else _DEFAULT_GET_ORDER
        self._positions = positions if positions is not None else _DEFAULT_POSITIONS
        self._fills = fills if fills is not None else _DEFAULT_FILLS
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def _resolve(scripted: _Scripted, **ctx: Any) -> DemoResponse:
        if isinstance(scripted, list):
            return scripted.pop(0)
        if callable(scripted):
            return scripted(**ctx)
        return scripted

    def create_order(self, body: Mapping[str, Any]) -> DemoResponse:
        self.calls.append(("create_order", dict(body)))
        return self._resolve(self._create, body=dict(body))

    def cancel_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        self.calls.append(("cancel_order", {"order_id": order_id, "market_ticker": market_ticker}))
        return self._resolve(self._cancel, order_id=order_id, market_ticker=market_ticker)

    def get_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        self.calls.append(("get_order", {"order_id": order_id, "market_ticker": market_ticker}))
        return self._resolve(self._get_order, order_id=order_id, market_ticker=market_ticker)

    def get_positions(self) -> DemoResponse:
        self.calls.append(("get_positions", {}))
        return self._resolve(self._positions)

    def get_fills(self) -> DemoResponse:
        self.calls.append(("get_fills", {}))
        return self._resolve(self._fills)

    # -- test helpers -------------------------------------------------- #

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


def money(value: str) -> Decimal:
    return Decimal(value)
