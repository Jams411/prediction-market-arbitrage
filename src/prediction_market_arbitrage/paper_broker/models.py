"""Value-objects for the deterministic paper broker (Milestone M2.4).

Immutable snapshots. The broker keeps mutable state internally and hands out a
frozen :class:`Order` on every query / event. Monetary fields are exact
:class:`~decimal.Decimal`; timestamps are timezone-aware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from prediction_market_arbitrage.recorder import FillRow, OrderEventRow

from .errors import PaperBrokerError

_ZERO = Decimal(0)
_ONE = Decimal(1)


class OrderStatus(Enum):
    """Order lifecycle state. Values match ``recorder.ORDER_STATUSES``."""

    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


def _require_decimal(value: object, *, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise PaperBrokerError(f"{field_name}: expected a finite Decimal")
    return value


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PaperBrokerError(f"{field_name}: expected a timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """A paper order to simulate. ``limit_price`` is required for a limit order
    and must be ``None`` for a market order."""

    order_id: str
    venue: str
    contract_id: str
    side: str  # 'buy' | 'sell'
    order_type: str  # 'limit' | 'market'
    quantity: Decimal
    limit_price: Decimal | None = None
    immediate_or_cancel: bool = False

    def __post_init__(self) -> None:
        for name in ("order_id", "venue", "contract_id"):
            if not getattr(self, name):
                raise PaperBrokerError(f"OrderRequest.{name} must be non-empty")
        if self.side not in ("buy", "sell"):
            raise PaperBrokerError("OrderRequest.side must be 'buy' or 'sell'")
        if self.order_type not in ("limit", "market"):
            raise PaperBrokerError("OrderRequest.order_type must be 'limit' or 'market'")
        _require_decimal(self.quantity, field_name="OrderRequest.quantity")
        if self.quantity <= _ZERO:
            raise PaperBrokerError("OrderRequest.quantity must be > 0")
        if self.order_type == "limit":
            if self.limit_price is None:
                raise PaperBrokerError("a limit order needs a limit_price")
            _require_decimal(self.limit_price, field_name="OrderRequest.limit_price")
            if not (_ZERO < self.limit_price < _ONE):
                raise PaperBrokerError("OrderRequest.limit_price must be in (0, 1)")
        elif self.limit_price is not None:
            raise PaperBrokerError("a market order must not carry a limit_price")


@dataclass(frozen=True, slots=True)
class Fill:
    """One executed slice against one order-book level."""

    fill_id: str
    order_id: str
    venue: str
    contract_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    liquidity: str
    filled_at: datetime
    level_index: int

    def to_row(self) -> FillRow:
        """The matching append-only :class:`recorder.FillRow`."""
        return FillRow(
            fill_id=self.fill_id,
            order_id=self.order_id,
            venue=self.venue,
            contract_id=self.contract_id,
            price=self.price,
            quantity=self.quantity,
            fee=self.fee,
            filled_at=self.filled_at,
            liquidity=self.liquidity,
        )


@dataclass(frozen=True, slots=True)
class StatusTransition:
    status: OrderStatus
    at: datetime
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Order:
    """Immutable snapshot of one order's state."""

    request: OrderRequest
    status: OrderStatus
    submitted_at: datetime
    effective_at: datetime
    fills: tuple[Fill, ...]
    transitions: tuple[StatusTransition, ...]
    terminal_at: datetime | None
    reject_reason: str = ""

    @property
    def order_id(self) -> str:
        return self.request.order_id

    @property
    def filled_quantity(self) -> Decimal:
        total = _ZERO
        for fill in self.fills:
            total += fill.quantity
        return total

    @property
    def remaining_quantity(self) -> Decimal:
        return self.request.quantity - self.filled_quantity

    @property
    def average_fill_price(self) -> Decimal:
        """Quantity-weighted average executed price (``0`` when nothing filled)."""
        filled = self.filled_quantity
        if filled <= _ZERO:
            return _ZERO
        notional = _ZERO
        for fill in self.fills:
            notional += fill.price * fill.quantity
        return notional / filled

    @property
    def total_fees(self) -> Decimal:
        total = _ZERO
        for fill in self.fills:
            total += fill.fee
        return total

    def event_rows(self) -> tuple[OrderEventRow, ...]:
        """One :class:`recorder.OrderEventRow` per status transition, in order."""
        return tuple(
            OrderEventRow(
                order_id=self.request.order_id,
                venue=self.request.venue,
                contract_id=self.request.contract_id,
                side=self.request.side,
                order_type=self.request.order_type,
                quantity=self.request.quantity,
                status=transition.status.value,
                event_time=transition.at,
                limit_price=self.request.limit_price,
                reason=transition.reason,
            )
            for transition in self.transitions
        )


@dataclass(frozen=True, slots=True)
class BrokerEvent:
    """Something the broker did on one ``advance`` step."""

    kind: str  # 'status' | 'fill'
    at: datetime
    order_id: str
    order: Order
    fill: Fill | None = None


@dataclass(frozen=True, slots=True)
class LegRiskSnapshot:
    """One-legged exposure between two orders that should fill together.

    ``unhedged_quantity`` = ``order_a`` filled − ``order_b`` filled. When it is
    non-zero the pair is partially unhedged; ``hedge_completion_price`` is the
    mid of ``order_b``'s current book (the price to finish the missing leg) and
    ``unhedged_notional`` values the gap at that price. Interpretation (is this
    risk acceptable?) is the M2.5 risk manager's job — this is only the
    deterministic measurement.
    """

    as_of: datetime
    order_a_id: str
    order_b_id: str
    a_filled_quantity: Decimal
    b_filled_quantity: Decimal
    unhedged_quantity: Decimal
    a_average_price: Decimal
    b_average_price: Decimal
    hedge_completion_price: Decimal | None
    unhedged_notional: Decimal | None
    both_terminal: bool = field(default=False)
