"""Venue-neutral request / response value objects for the live-broker interface
(Milestone M3.4).

Deliberately close to the M2.4 paper-broker types (``paper_broker.models``) so a
future live path is a drop-in behind the same strategy code — but kept separate
because these describe a *real venue round-trip* that no primary evidence yet
defines. Every monetary field is an exact :class:`~decimal.Decimal`; every
timestamp is timezone-aware.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .errors import LiveBrokerError

_ZERO = Decimal(0)
_ONE = Decimal(1)

ORDER_SIDES = frozenset({"buy", "sell"})
ORDER_TYPES = frozenset({"limit", "market"})
TIME_IN_FORCE = frozenset({"gtc", "ioc", "fok"})


class LiveOrderState(Enum):
    """Lifecycle state as *reported by a venue*. ``UNKNOWN`` = the venue gave no
    usable status (fail-closed: never assume filled)."""

    UNKNOWN = "unknown"
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


def _dec(value: object, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise LiveBrokerError(f"{name} must be a finite Decimal")
    return value


def _aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LiveBrokerError(f"{name} must be a timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class LiveOrderRequest:
    """A venue order to place. ``client_order_id`` is the caller-chosen
    idempotency key — required, and enforced at the interface boundary."""

    client_order_id: str
    venue: str
    contract_id: str
    side: str  # 'buy' | 'sell'
    order_type: str  # 'limit' | 'market'
    quantity: Decimal
    limit_price: Decimal | None = None
    time_in_force: str = "gtc"

    def __post_init__(self) -> None:
        for name in ("client_order_id", "venue", "contract_id"):
            if not str(getattr(self, name)).strip():
                raise LiveBrokerError(f"LiveOrderRequest.{name} must be non-empty")
        if self.side not in ORDER_SIDES:
            raise LiveBrokerError("LiveOrderRequest.side must be 'buy' or 'sell'")
        if self.order_type not in ORDER_TYPES:
            raise LiveBrokerError("LiveOrderRequest.order_type must be 'limit' or 'market'")
        if self.time_in_force not in TIME_IN_FORCE:
            raise LiveBrokerError(
                f"LiveOrderRequest.time_in_force must be one of {sorted(TIME_IN_FORCE)}"
            )
        _dec(self.quantity, name="LiveOrderRequest.quantity")
        if self.quantity <= _ZERO:
            raise LiveBrokerError("LiveOrderRequest.quantity must be > 0")
        if self.order_type == "limit":
            if self.limit_price is None:
                raise LiveBrokerError("a limit order needs a limit_price")
            _dec(self.limit_price, name="LiveOrderRequest.limit_price")
            if not (_ZERO < self.limit_price < _ONE):
                raise LiveBrokerError("LiveOrderRequest.limit_price must be in (0, 1)")
        elif self.limit_price is not None:
            raise LiveBrokerError("a market order must not carry a limit_price")


@dataclass(frozen=True, slots=True)
class CancelRequest:
    """A cancel keyed by the ``client_order_id`` (and the venue id when known)."""

    client_order_id: str
    venue_order_id: str | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise LiveBrokerError("CancelRequest.client_order_id must be non-empty")


@dataclass(frozen=True, slots=True)
class LiveOrderAck:
    """A venue's immediate acknowledgement of a submit / cancel."""

    client_order_id: str
    venue_order_id: str | None
    state: LiveOrderState
    accepted: bool
    as_of: datetime
    raw: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.as_of, name="LiveOrderAck.as_of")


@dataclass(frozen=True, slots=True)
class LiveOrderStatus:
    """A point-in-time order status read from the venue."""

    client_order_id: str
    venue_order_id: str | None
    state: LiveOrderState
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    as_of: datetime

    def __post_init__(self) -> None:
        _dec(self.filled_quantity, name="LiveOrderStatus.filled_quantity")
        _dec(self.remaining_quantity, name="LiveOrderStatus.remaining_quantity")
        if self.average_fill_price is not None:
            _dec(self.average_fill_price, name="LiveOrderStatus.average_fill_price")
        _aware(self.as_of, name="LiveOrderStatus.as_of")


@dataclass(frozen=True, slots=True)
class LivePosition:
    """One venue position (signed quantity)."""

    venue: str
    contract_id: str
    quantity: Decimal
    average_price: Decimal | None
    as_of: datetime

    def __post_init__(self) -> None:
        _dec(self.quantity, name="LivePosition.quantity")
        if self.average_price is not None:
            _dec(self.average_price, name="LivePosition.average_price")
        _aware(self.as_of, name="LivePosition.as_of")
