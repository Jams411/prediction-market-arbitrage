"""Row value-objects for recorder entities that have no domain model yet
(Milestone M2.2).

Orders, fills, positions, and PnL are produced by the paper broker / risk work
(M2.4 / M2.5), which does not exist. The recorder owns their persistence shape
so that future code can emit rows matching it. These are plain frozen
containers — no execution or accounting logic. Every monetary field is an exact
:class:`~decimal.Decimal`; every timestamp is timezone-aware.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ._convert import dec_text, opt_dec_text, require_choice, require_text, utc_naive
from .errors import RecorderError

ORDER_SIDES = frozenset({"buy", "sell"})
ORDER_TYPES = frozenset({"limit", "market"})
ORDER_STATUSES = frozenset(
    {"new", "submitted", "partially_filled", "filled", "canceled", "rejected", "expired"}
)
LIQUIDITY_KINDS = frozenset({"maker", "taker", "unknown"})
PNL_SCOPES = frozenset({"contract", "pair", "portfolio"})


@dataclass(frozen=True, slots=True)
class OrderEventRow:
    """One point in an order's lifecycle (append-only — a status change is a new row)."""

    order_id: str
    venue: str
    contract_id: str
    side: str
    order_type: str
    quantity: Decimal
    status: str
    event_time: datetime
    limit_price: Decimal | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        require_text(self.order_id, field="OrderEventRow.order_id")
        require_text(self.venue, field="OrderEventRow.venue")
        require_text(self.contract_id, field="OrderEventRow.contract_id")
        require_choice(self.side, ORDER_SIDES, field="OrderEventRow.side")
        require_choice(self.order_type, ORDER_TYPES, field="OrderEventRow.order_type")
        require_choice(self.status, ORDER_STATUSES, field="OrderEventRow.status")
        dec_text(self.quantity, field="OrderEventRow.quantity")
        opt_dec_text(self.limit_price, field="OrderEventRow.limit_price")
        if self.order_type == "limit" and self.limit_price is None:
            raise RecorderError("OrderEventRow: a limit order needs a limit_price")
        utc_naive(self.event_time, field="OrderEventRow.event_time")


@dataclass(frozen=True, slots=True)
class FillRow:
    """One fill against an order."""

    fill_id: str
    order_id: str
    venue: str
    contract_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    filled_at: datetime
    liquidity: str = "unknown"

    def __post_init__(self) -> None:
        require_text(self.fill_id, field="FillRow.fill_id")
        require_text(self.order_id, field="FillRow.order_id")
        require_text(self.venue, field="FillRow.venue")
        require_text(self.contract_id, field="FillRow.contract_id")
        dec_text(self.price, field="FillRow.price")
        dec_text(self.quantity, field="FillRow.quantity")
        dec_text(self.fee, field="FillRow.fee")
        require_choice(self.liquidity, LIQUIDITY_KINDS, field="FillRow.liquidity")
        utc_naive(self.filled_at, field="FillRow.filled_at")


@dataclass(frozen=True, slots=True)
class PositionRow:
    """A position snapshot at a point in time (append-only history)."""

    venue: str
    contract_id: str
    quantity: Decimal  # signed
    avg_price: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        require_text(self.venue, field="PositionRow.venue")
        require_text(self.contract_id, field="PositionRow.contract_id")
        dec_text(self.quantity, field="PositionRow.quantity")
        dec_text(self.avg_price, field="PositionRow.avg_price")
        utc_naive(self.as_of, field="PositionRow.as_of")


@dataclass(frozen=True, slots=True)
class PnlRow:
    """A realized / unrealized PnL snapshot for a scope (contract, pair, portfolio)."""

    scope: str
    scope_id: str
    realized: Decimal
    unrealized: Decimal
    fees: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        require_choice(self.scope, PNL_SCOPES, field="PnlRow.scope")
        require_text(self.scope_id, field="PnlRow.scope_id")
        dec_text(self.realized, field="PnlRow.realized")
        dec_text(self.unrealized, field="PnlRow.unrealized")
        dec_text(self.fees, field="PnlRow.fees")
        utc_naive(self.as_of, field="PnlRow.as_of")


@dataclass(frozen=True, slots=True)
class LegRiskEventRow:
    """One observed one-legged exposure between two orders that should fill
    together — the persistable shape of a paper-broker ``LegRiskSnapshot``.

    Recorded **only** when there is real exposure: ``unhedged_quantity`` (=
    ``a_filled_quantity - b_filled_quantity``, signed) must be non-zero, else
    ``__post_init__`` raises. ``both_terminal`` distinguishes a *temporary*
    exposure (``False`` — a leg is still working and may yet fill) from an
    *unresolved* one (``True`` — both orders are terminal, so the imbalance is
    permanent). ``hedge_completion_price`` / ``unhedged_notional`` are ``None``
    when the measurement was taken without a book to price the gap.
    """

    order_a_id: str
    order_b_id: str
    a_filled_quantity: Decimal
    b_filled_quantity: Decimal
    unhedged_quantity: Decimal
    a_average_price: Decimal
    b_average_price: Decimal
    both_terminal: bool
    as_of: datetime
    hedge_completion_price: Decimal | None = None
    unhedged_notional: Decimal | None = None

    def __post_init__(self) -> None:
        require_text(self.order_a_id, field="LegRiskEventRow.order_a_id")
        require_text(self.order_b_id, field="LegRiskEventRow.order_b_id")
        for name in (
            "a_filled_quantity",
            "b_filled_quantity",
            "unhedged_quantity",
            "a_average_price",
            "b_average_price",
        ):
            dec_text(getattr(self, name), field=f"LegRiskEventRow.{name}")
        opt_dec_text(
            self.hedge_completion_price, field="LegRiskEventRow.hedge_completion_price"
        )
        opt_dec_text(self.unhedged_notional, field="LegRiskEventRow.unhedged_notional")
        if not isinstance(self.both_terminal, bool):
            raise RecorderError("LegRiskEventRow.both_terminal must be a bool")
        utc_naive(self.as_of, field="LegRiskEventRow.as_of")
        if self.unhedged_quantity == Decimal(0):
            raise RecorderError(
                "LegRiskEventRow: a leg-risk event needs non-zero unhedged_quantity "
                "(there is no exposure to record when both legs match)"
            )
