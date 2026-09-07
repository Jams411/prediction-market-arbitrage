"""Venue-neutral live-book update messages (Milestone M2.1).

The state machine in :mod:`.state` consumes only these types. Venue-specific
WebSocket wire formats are decoded into them by :mod:`.kalshi_ws` and
:mod:`.polymarket_us_ws` — the same "keep venue JSON shapes out of the core"
boundary the REST adapters draw between ``client`` and ``normalize``
(``docs/ARCHITECTURE.md``).

Two update kinds:

- :class:`BookSnapshot` — the complete set of resting levels for one contract at
  a point in time. Replaces whatever the feed held for that contract.
- :class:`BookDelta` — a signed change to the aggregated quantity at one
  ``(side, price)`` of one contract. Applied on top of the current state.

Every price / quantity is an explicit :class:`~decimal.Decimal`; every timestamp
is timezone-aware. ``sequence`` is the venue's per-subscription message counter
when the feed provides one (Kalshi ``seq``), else ``None`` (Polymarket US
market-data messages carry no sequence and are full snapshots).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from prediction_market_arbitrage.domain import PriceLevel

from .errors import LiveBookError

#: Which side of the book a delta touches, in venue-neutral terms.
Side = Literal["bid", "ask"]

_ZERO = Decimal(0)
_ONE = Decimal(1)


def require_aware_dt(value: datetime, *, field: str) -> datetime:
    """Reject a missing or timezone-naive ``datetime`` with :class:`LiveBookError`."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LiveBookError(f"{field}: must be a timezone-aware datetime")
    return value


def _require_decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LiveBookError(f"{field}: expected a finite Decimal, got {value!r}")
    return value


def _check_optional_sequence(value: int | None, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LiveBookError(f"{field} must be a non-negative int or None")


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """A complete book for one contract. Applying it discards prior state.

    ``bids`` / ``asks`` are the domain's :class:`PriceLevel` tuples but are **not**
    required to be pre-sorted here — :meth:`.state.LiveBook.apply_snapshot`
    rebuilds its ordered index from them. ``market_state`` is the venue's
    tradability state string when the feed reports one (Polymarket US
    ``state``), else ``None`` (the Kalshi orderbook channel carries none).
    """

    venue: str
    contract_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    sequence: int | None
    source_time: datetime | None
    market_state: str | None = None

    def __post_init__(self) -> None:
        if not self.venue:
            raise LiveBookError("BookSnapshot.venue must be non-empty")
        if not self.contract_id:
            raise LiveBookError("BookSnapshot.contract_id must be non-empty")
        for side_name, levels in (("bids", self.bids), ("asks", self.asks)):
            if not isinstance(levels, tuple) or any(
                not isinstance(level, PriceLevel) for level in levels
            ):
                raise LiveBookError(
                    f"BookSnapshot.{side_name} must be a tuple of PriceLevel"
                )
        _check_optional_sequence(self.sequence, field="BookSnapshot.sequence")
        if self.source_time is not None:
            require_aware_dt(self.source_time, field="BookSnapshot.source_time")


@dataclass(frozen=True, slots=True)
class BookDelta:
    """A signed change to the aggregated quantity at one ``(side, price)``.

    ``quantity_delta`` is added to the current quantity at ``price`` on ``side``.
    A level whose quantity reaches exactly zero is removed. A delta that would
    drive a quantity **negative** is a desync signal (handled by the state
    machine, not raised here). ``price`` is a probability-style value in
    ``[0, 1]``.
    """

    venue: str
    contract_id: str
    side: Side
    price: Decimal
    quantity_delta: Decimal
    sequence: int | None
    source_time: datetime | None

    def __post_init__(self) -> None:
        if not self.venue:
            raise LiveBookError("BookDelta.venue must be non-empty")
        if not self.contract_id:
            raise LiveBookError("BookDelta.contract_id must be non-empty")
        if self.side not in ("bid", "ask"):
            raise LiveBookError(f"BookDelta.side must be 'bid' or 'ask', got {self.side!r}")
        price = _require_decimal(self.price, field="BookDelta.price")
        if price < _ZERO or price > _ONE:
            raise LiveBookError(f"BookDelta.price {price} outside [0, 1]")
        delta = _require_decimal(self.quantity_delta, field="BookDelta.quantity_delta")
        if delta == _ZERO:
            raise LiveBookError("BookDelta.quantity_delta must be non-zero")
        _check_optional_sequence(self.sequence, field="BookDelta.sequence")
        if self.source_time is not None:
            require_aware_dt(self.source_time, field="BookDelta.source_time")
