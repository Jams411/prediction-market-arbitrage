"""Fakes for the M3.4 live-broker interface tests. Not collected by pytest.

Nothing here talks to a venue. ``RecordingLiveBroker`` is a minimal
:class:`LiveBroker` whose ``_do_*`` hooks only record that they were reached — it
exists to prove the gate + idempotency wrapper runs *before* any venue call,
without needing a real (or guessed) venue implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.live_broker import (
    CancelRequest,
    LiveBroker,
    LiveOrderAck,
    LiveOrderRequest,
    LiveOrderState,
    LiveOrderStatus,
    LivePosition,
)

T0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

FAKE_KALSHI_KEY_ID = "kalshi-trading-key-id-0000"
FAKE_KALSHI_PEM = "-----BEGIN PRIVATE KEY-----\nNOT-A-REAL-TRADING-KEY\n-----END PRIVATE KEY-----\n"
FAKE_POLY_KEY_ID = "poly-trading-key-id-0000"
FAKE_POLY_SECRET = "cG9seS10cmFkaW5nLXNlY3JldC1ub3QtcmVhbA=="  # base64, obviously fake


def order_request(
    *,
    client_order_id: str = "cid-1",
    venue: str = "kalshi",
    side: str = "buy",
    quantity: str = "10",
    limit_price: str | None = "0.50",
    order_type: str = "limit",
) -> LiveOrderRequest:
    return LiveOrderRequest(
        client_order_id=client_order_id,
        venue=venue,
        contract_id="SYNTH-T1:YES",
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        limit_price=None if limit_price is None else Decimal(limit_price),
    )


class RecordingLiveBroker(LiveBroker):
    """A venue-less broker that records every ``_do_*`` it reaches."""

    venue = "kalshi"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.calls: list[str] = []

    def _do_submit(self, request: LiveOrderRequest, *, now: datetime) -> LiveOrderAck:
        self.calls.append(f"submit:{request.client_order_id}")
        return LiveOrderAck(
            client_order_id=request.client_order_id,
            venue_order_id="venue-1",
            state=LiveOrderState.SUBMITTED,
            accepted=True,
            as_of=now,
        )

    def _do_cancel(self, request: CancelRequest, *, now: datetime) -> LiveOrderAck:
        self.calls.append(f"cancel:{request.client_order_id}")
        return LiveOrderAck(
            client_order_id=request.client_order_id,
            venue_order_id=request.venue_order_id,
            state=LiveOrderState.CANCELED,
            accepted=True,
            as_of=now,
        )

    def _do_get_order(self, client_order_id: str, *, now: datetime) -> LiveOrderStatus:
        self.calls.append(f"get_order:{client_order_id}")
        return LiveOrderStatus(
            client_order_id=client_order_id,
            venue_order_id="venue-1",
            state=LiveOrderState.UNKNOWN,
            filled_quantity=Decimal(0),
            remaining_quantity=Decimal(0),
            average_fill_price=None,
            as_of=now,
        )

    def _do_get_positions(self, *, now: datetime) -> tuple[LivePosition, ...]:
        self.calls.append("get_positions")
        return ()
