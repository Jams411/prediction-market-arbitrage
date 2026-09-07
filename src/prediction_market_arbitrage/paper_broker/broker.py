"""Deterministic paper broker: simulate order execution against normalized
order-book depth (Milestone M2.4).

Pure and deterministic — no wall-clock, no randomness. The caller drives
simulated time forward with :meth:`PaperBroker.advance`, supplying the
:class:`~prediction_market_arbitrage.domain.OrderBook` that is live at that
instant; the broker matches every working order against real depth, applies a
deterministic latency and slippage model, and records the order lifecycle and
fills as immutable snapshots. It does **not** talk to a venue and does **not**
decide *whether* to trade (that is strategy / M2.5).

Model summary:

- **Latency.** A submitted order reaches the matching engine at
  ``submit_time + config.submit_latency``; it can only fill against a book whose
  ``timestamp`` is at or after that. A cancel takes effect at
  ``cancel_time + config.cancel_latency`` — a fill that lands first wins the race.
- **Depth / partial fills.** A buy walks the ask side, a sell the bid side, best
  price first. A limit order stops at its limit price. If the eligible depth is
  less than the remaining quantity, the order partially fills and stays working
  (unless it is IOC).
- **Slippage.** Each filled level's execution price comes from the injected
  :class:`~.slippage.SlippageModel` (default: the walked price), clamped into
  ``(0, 1)`` (A-033).
- **Rejections.** Malformed request, below ``min_order_size``, duplicate id, and
  IOC / market with no eligible liquidity on its first eligible book.
- **Expiry.** A market order unfilled after ``config.market_order_ttl`` expires
  its remainder.
- **Leg risk.** :meth:`leg_risk` measures the one-legged exposure between two
  orders that should have filled together.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.arbitrage import FeeModel, ZeroFeeModel
from prediction_market_arbitrage.domain import OrderBook, PriceLevel
from prediction_market_arbitrage.recorder import PositionRow

from .errors import PaperBrokerError
from .models import (
    BrokerEvent,
    Fill,
    LegRiskSnapshot,
    Order,
    OrderRequest,
    OrderStatus,
    StatusTransition,
)
from .slippage import NoSlippage, SlippageModel

_ZERO = Decimal(0)
_PRICE_MIN = Decimal("0.0001")
_PRICE_MAX = Decimal("0.9999")


@dataclass(frozen=True, slots=True)
class PaperBrokerConfig:
    """Deterministic knobs. Latencies are ``timedelta``; every price is Decimal."""

    fee_model: FeeModel = field(default_factory=ZeroFeeModel)
    slippage: SlippageModel = field(default_factory=NoSlippage)
    submit_latency: timedelta = timedelta(0)
    cancel_latency: timedelta = timedelta(0)
    min_order_size: Decimal | None = None
    market_order_ttl: timedelta | None = None
    #: IOC / market orders that see no eligible liquidity on their first eligible
    #: book are rejected (else a market order simply keeps working).
    reject_on_no_immediate_fill: bool = True

    def __post_init__(self) -> None:
        for name in ("submit_latency", "cancel_latency"):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value < timedelta(0):
                raise PaperBrokerError(f"PaperBrokerConfig.{name} must be a non-negative timedelta")
        if self.market_order_ttl is not None and self.market_order_ttl <= timedelta(0):
            raise PaperBrokerError("PaperBrokerConfig.market_order_ttl must be positive or None")
        if self.min_order_size is not None:
            size = self.min_order_size
            if not isinstance(size, Decimal) or not size.is_finite() or size <= _ZERO:
                raise PaperBrokerError(
                    "PaperBrokerConfig.min_order_size must be a positive Decimal"
                )


@dataclass(slots=True)
class _OrderState:
    request: OrderRequest
    status: OrderStatus
    submitted_at: datetime
    effective_at: datetime
    fills: list[Fill] = field(default_factory=list)
    transitions: list[StatusTransition] = field(default_factory=list)
    terminal_at: datetime | None = None
    cancel_effective_at: datetime | None = None
    fill_seq: int = 0
    saw_eligible_book: bool = False

    @property
    def filled_quantity(self) -> Decimal:
        total = _ZERO
        for fill in self.fills:
            total += fill.quantity
        return total

    def snapshot(self) -> Order:
        return Order(
            request=self.request,
            status=self.status,
            submitted_at=self.submitted_at,
            effective_at=self.effective_at,
            fills=tuple(self.fills),
            transitions=tuple(self.transitions),
            terminal_at=self.terminal_at,
            reject_reason=next(
                (t.reason for t in self.transitions if t.status is OrderStatus.REJECTED), ""
            ),
        )

    def transition(self, status: OrderStatus, at: datetime, reason: str = "") -> None:
        self.status = status
        self.transitions.append(StatusTransition(status=status, at=at, reason=reason))
        if status.is_terminal:
            self.terminal_at = at


@dataclass(slots=True)
class _Position:
    quantity: Decimal = _ZERO  # signed
    avg_price: Decimal = _ZERO


class PaperBroker:
    """Simulates order execution for many contracts. Single-threaded, ordered."""

    def __init__(self, config: PaperBrokerConfig | None = None) -> None:
        self._config = config if config is not None else PaperBrokerConfig()
        self._orders: dict[str, _OrderState] = {}
        self._positions: dict[str, _Position] = {}
        self._clock: datetime | None = None

    @property
    def config(self) -> PaperBrokerConfig:
        return self._config

    # -- submission / cancellation ---------------------------------- #

    def submit(self, request: OrderRequest, *, at: datetime) -> Order:
        if not isinstance(request, OrderRequest):
            raise PaperBrokerError("submit expects an OrderRequest")
        self._require_time(at, "at")
        if request.order_id in self._orders:
            raise PaperBrokerError(f"duplicate order_id {request.order_id!r}")

        state = _OrderState(
            request=request,
            status=OrderStatus.SUBMITTED,
            submitted_at=at,
            effective_at=at + self._config.submit_latency,
        )
        self._orders[request.order_id] = state
        self._advance_clock(at)

        state.transition(OrderStatus.SUBMITTED, at)
        minimum = self._config.min_order_size
        if minimum is not None and request.quantity < minimum:
            state.transition(
                OrderStatus.REJECTED, at, f"quantity {request.quantity} below min {minimum}"
            )
        return state.snapshot()

    def cancel(self, order_id: str, *, at: datetime) -> Order:
        self._require_time(at, "at")
        state = self._state(order_id)
        self._advance_clock(at)
        if state.status.is_terminal:
            return state.snapshot()  # cancel arrived too late — no-op
        state.cancel_effective_at = at + self._config.cancel_latency
        return state.snapshot()

    # -- time advance ---------------------------------------------- #

    def advance(
        self, *, at: datetime, books: Mapping[str, OrderBook] | None = None
    ) -> tuple[BrokerEvent, ...]:
        """Move simulated time to ``at`` and process every working order against
        ``books`` (keyed by ``contract_id``). Returns the events generated, in
        deterministic order."""
        self._require_time(at, "at")
        self._advance_clock(at)
        events: list[BrokerEvent] = []
        for state in self._orders.values():
            if state.status.is_terminal:
                continue
            self._process_order(state, at, books, events)
        return tuple(events)

    # -- queries -------------------------------------------------- #

    def order(self, order_id: str) -> Order:
        return self._state(order_id).snapshot()

    def orders(self) -> tuple[Order, ...]:
        return tuple(state.snapshot() for state in self._orders.values())

    def working_orders(self) -> tuple[Order, ...]:
        return tuple(
            state.snapshot() for state in self._orders.values() if not state.status.is_terminal
        )

    def position(self, contract_id: str, *, as_of: datetime) -> PositionRow:
        self._require_time(as_of, "as_of", advance=False)
        pos = self._positions.get(contract_id, _Position())
        return PositionRow(
            venue=self._venue_for(contract_id),
            contract_id=contract_id,
            quantity=pos.quantity,
            avg_price=pos.avg_price,
            as_of=as_of,
        )

    def leg_risk(
        self,
        order_a_id: str,
        order_b_id: str,
        *,
        as_of: datetime,
        books: Mapping[str, OrderBook] | None = None,
    ) -> LegRiskSnapshot:
        self._require_time(as_of, "as_of", advance=False)
        a, b = self._state(order_a_id), self._state(order_b_id)
        a_filled, b_filled = a.filled_quantity, b.filled_quantity
        completion = self._book_mid(books, b.request.contract_id) if books is not None else None
        unhedged = a_filled - b_filled
        return LegRiskSnapshot(
            as_of=as_of,
            order_a_id=order_a_id,
            order_b_id=order_b_id,
            a_filled_quantity=a_filled,
            b_filled_quantity=b_filled,
            unhedged_quantity=unhedged,
            a_average_price=a.snapshot().average_fill_price,
            b_average_price=b.snapshot().average_fill_price,
            hedge_completion_price=completion,
            unhedged_notional=None if completion is None else abs(unhedged) * completion,
            both_terminal=a.status.is_terminal and b.status.is_terminal,
        )

    # -- internals: matching ------------------------------------- #

    def _process_order(
        self,
        state: _OrderState,
        at: datetime,
        books: Mapping[str, OrderBook] | None,
        events: list[BrokerEvent],
    ) -> None:
        request = state.request
        book = None if books is None else books.get(request.contract_id)
        eligible = (
            state.effective_at <= at
            and book is not None
            and book.timestamp >= state.effective_at
        )

        if eligible:
            first_eligible = not state.saw_eligible_book
            state.saw_eligible_book = True
            self._match_against_book(
                state, book, at, events, first_eligible=first_eligible  # type: ignore[arg-type]
            )

        if state.status.is_terminal:
            return

        # Cancel that has taken effect wins the remainder.
        if state.cancel_effective_at is not None and state.cancel_effective_at <= at:
            state.transition(OrderStatus.CANCELED, state.cancel_effective_at, "cancel took effect")
            events.append(self._status_event(state, state.cancel_effective_at))
            return

        # Market-order TTL on the remainder.
        ttl = self._config.market_order_ttl
        if (
            request.order_type == "market"
            and ttl is not None
            and at - state.effective_at > ttl
        ):
            state.transition(OrderStatus.EXPIRED, at, f"market order unfilled after {ttl}")
            events.append(self._status_event(state, at))

    def _match_against_book(
        self,
        state: _OrderState,
        book: OrderBook,
        at: datetime,
        events: list[BrokerEvent],
        *,
        first_eligible: bool,
    ) -> None:
        request = state.request
        levels = book.asks if request.side == "buy" else book.bids
        remaining = request.quantity - state.filled_quantity
        cumulative = _ZERO
        new_fills: list[Fill] = []

        for index, level in enumerate(levels):
            if remaining <= _ZERO:
                break
            if not self._price_passes_limit(request, level):
                break  # levels are best-first; nothing further can fill
            take = level.quantity if level.quantity < remaining else remaining
            exec_price = self._clamp_price(
                self._config.slippage.adjust(
                    side=request.side,  # type: ignore[arg-type]
                    level_price=level.price,
                    level_index=index,
                    filled_quantity=take,
                    cumulative_quantity=cumulative,
                )
            )
            fee = self._config.fee_model.fee(
                venue=request.venue, fills=[(exec_price, take)]
            )
            if not isinstance(fee, Decimal) or not fee.is_finite() or fee < _ZERO:
                raise PaperBrokerError(
                    "fee model returned a non-Decimal, negative, or non-finite fee"
                )
            state.fill_seq += 1
            fill = Fill(
                fill_id=f"{request.order_id}#{state.fill_seq}",
                order_id=request.order_id,
                venue=request.venue,
                contract_id=request.contract_id,
                price=exec_price,
                quantity=take,
                fee=fee,
                liquidity="taker",
                filled_at=at,
                level_index=index,
            )
            state.fills.append(fill)
            new_fills.append(fill)
            self._apply_fill_to_position(fill, request.side)
            remaining -= take
            cumulative += take

        filled = state.filled_quantity
        if new_fills:
            if filled >= request.quantity:
                state.transition(OrderStatus.FILLED, at)
            else:
                state.transition(OrderStatus.PARTIALLY_FILLED, at)
            for fill in new_fills:
                events.append(BrokerEvent("fill", at, request.order_id, state.snapshot(), fill))
            events.append(self._status_event(state, at))
        elif first_eligible and self._is_immediate(request):
            reason = "no eligible liquidity on first eligible book"
            state.transition(OrderStatus.REJECTED, at, reason)
            events.append(self._status_event(state, at))
            return

        if not state.status.is_terminal and request.immediate_or_cancel and remaining > _ZERO:
            state.transition(OrderStatus.CANCELED, at, "IOC unfilled remainder")
            events.append(self._status_event(state, at))

    # -- internals: helpers ------------------------------------- #

    @staticmethod
    def _price_passes_limit(request: OrderRequest, level: PriceLevel) -> bool:
        if request.order_type == "market" or request.limit_price is None:
            return True
        if request.side == "buy":
            return level.price <= request.limit_price
        return level.price >= request.limit_price

    def _is_immediate(self, request: OrderRequest) -> bool:
        return request.immediate_or_cancel or (
            request.order_type == "market" and self._config.reject_on_no_immediate_fill
        )

    @staticmethod
    def _clamp_price(price: Decimal) -> Decimal:
        if price < _PRICE_MIN:
            return _PRICE_MIN
        if price > _PRICE_MAX:
            return _PRICE_MAX
        return price

    def _apply_fill_to_position(self, fill: Fill, side: str) -> None:
        pos = self._positions.setdefault(fill.contract_id, _Position())
        signed = fill.quantity if side == "buy" else -fill.quantity
        current = pos.quantity
        if current == _ZERO or (current > _ZERO) == (signed > _ZERO):
            total = abs(current) + fill.quantity
            pos.avg_price = (
                (pos.avg_price * abs(current) + fill.price * fill.quantity) / total
                if total > _ZERO
                else _ZERO
            )
            pos.quantity = current + signed
        else:
            # Reducing / crossing the existing position.
            if fill.quantity <= abs(current):
                pos.quantity = current + signed  # avg_price of the surviving lot unchanged
            else:
                pos.quantity = current + signed
                pos.avg_price = fill.price  # flipped — new lot at this fill price
        if pos.quantity == _ZERO:
            pos.avg_price = _ZERO

    @staticmethod
    def _book_mid(
        books: Mapping[str, OrderBook] | None, contract_id: str
    ) -> Decimal | None:
        if books is None:
            return None
        book = books.get(contract_id)
        if book is None or book.best_bid is None or book.best_ask is None:
            return None
        return (book.best_bid.price + book.best_ask.price) / Decimal(2)

    def _venue_for(self, contract_id: str) -> str:
        for state in self._orders.values():
            if state.request.contract_id == contract_id:
                return state.request.venue
        return "unknown"

    def _status_event(self, state: _OrderState, at: datetime) -> BrokerEvent:
        return BrokerEvent("status", at, state.request.order_id, state.snapshot())

    def _state(self, order_id: str) -> _OrderState:
        state = self._orders.get(order_id)
        if state is None:
            raise PaperBrokerError(f"unknown order_id {order_id!r}")
        return state

    def _require_time(self, value: datetime, name: str, *, advance: bool = True) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise PaperBrokerError(f"{name} must be a timezone-aware datetime")
        if advance and self._clock is not None and value < self._clock:
            raise PaperBrokerError(
                f"{name} {value.isoformat()} is before the broker clock {self._clock.isoformat()}"
            )

    def _advance_clock(self, at: datetime) -> None:
        if self._clock is None or at > self._clock:
            self._clock = at
