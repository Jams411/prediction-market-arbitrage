"""Reconstructed value-objects yielded by the replay adapter (M2.3).

Each mirrors one recorder table, with stored text turned back into exact
:class:`~decimal.Decimal` and stored naive-UTC timestamps reattached to UTC.
``row_id`` is the recorder's monotonic append id — the deterministic ordering
key within a stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.livebook import BookSnapshot, FeedHealth
from prediction_market_arbitrage.registry import OutcomeRelation


@dataclass(frozen=True, slots=True)
class RecordedOrderBook:
    """A reconstructed domain :class:`OrderBook` plus its record metadata."""

    row_id: int
    book: OrderBook
    recorded_at: datetime
    source: str

    def as_book_snapshot(self) -> BookSnapshot:
        """The same book as a livebook :class:`BookSnapshot` (``sequence`` /
        ``market_state`` are ``None`` — the recorder did not store them), so a
        replayed book can be fed straight into ``LiveBookFeed.apply_snapshot``."""
        return BookSnapshot(
            venue=self.book.contract.market.venue.id,
            contract_id=self.book.contract.id,
            bids=self.book.bids,
            asks=self.book.asks,
            sequence=None,
            source_time=self.book.timestamp,
            market_state=None,
        )


@dataclass(frozen=True, slots=True)
class RecordedOpportunity:
    row_id: int
    pair_id: str
    relation: OutcomeRelation
    evaluation_time: datetime
    executable_quantity: Decimal
    depth_capped: bool
    gross_total_cost: Decimal
    gross_edge: Decimal
    fees: Decimal
    execution_buffer: Decimal
    net_total_cost: Decimal
    net_edge: Decimal
    has_opportunity: bool
    rejection_reason: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedOrderEvent:
    row_id: int
    order_id: str
    venue: str
    contract_id: str
    side: str
    order_type: str
    limit_price: Decimal | None
    quantity: Decimal
    status: str
    event_time: datetime
    reason: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedFill:
    row_id: int
    fill_id: str
    order_id: str
    venue: str
    contract_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    liquidity: str
    filled_at: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedPosition:
    row_id: int
    venue: str
    contract_id: str
    quantity: Decimal
    avg_price: Decimal
    as_of: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedPnl:
    row_id: int
    scope: str
    scope_id: str
    realized: Decimal
    unrealized: Decimal
    fees: Decimal
    as_of: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedHealthEvent:
    row_id: int
    venue: str
    contract_id: str
    health: FeedHealth
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecordedLegRiskEvent:
    """A reconstructed one-legged-exposure event (recorder ``leg_risk_events``)."""

    row_id: int
    order_a_id: str
    order_b_id: str
    a_filled_quantity: Decimal
    b_filled_quantity: Decimal
    unhedged_quantity: Decimal
    a_average_price: Decimal
    b_average_price: Decimal
    hedge_completion_price: Decimal | None
    unhedged_notional: Decimal | None
    both_terminal: bool
    as_of: datetime
    recorded_at: datetime

    @property
    def temporary(self) -> bool:
        """A leg is still working — the exposure may still resolve."""
        return not self.both_terminal

    @property
    def unresolved(self) -> bool:
        """Both orders are terminal, so the one-leg imbalance is permanent."""
        return self.both_terminal


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One item on the merged, time-ordered replay timeline."""

    #: 'order_book' | 'opportunity' | 'order_event' | 'fill' | 'position' | 'pnl'
    #: | 'health' | 'leg_risk'
    kind: str
    recorded_at: datetime
    row_id: int
    payload: (
        RecordedOrderBook
        | RecordedOpportunity
        | RecordedOrderEvent
        | RecordedFill
        | RecordedPosition
        | RecordedPnl
        | RecordedHealthEvent
        | RecordedLegRiskEvent
    )
