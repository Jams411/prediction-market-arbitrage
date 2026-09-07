"""Synthetic builders for the M3.1 dashboard tests. Not collected by pytest.

Reuses the M2.5 risk builders (``risk_support``) for opportunities / positions /
leg risk, and hand-builds live-book feeds, orders, and registry records with
obviously synthetic identifiers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from livebook_support import kalshi_contract, levels

from prediction_market_arbitrage.livebook import BookSnapshot, HealthStatus
from prediction_market_arbitrage.livebook.state import LiveBookFeed
from prediction_market_arbitrage.paper_broker import (
    Fill,
    Order,
    OrderRequest,
    OrderStatus,
    StatusTransition,
)
from prediction_market_arbitrage.recorder import PnlRow
from prediction_market_arbitrage.registry import (
    MarketPairRecord,
    MarketPairRegistry,
    OutcomeRelation,
    PairStatus,
    VenueLeg,
)

T0 = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
MAX_STALENESS = timedelta(seconds=5)
_CONTRACT = kalshi_contract()


def feed(
    *,
    status: HealthStatus = HealthStatus.HEALTHY,
    snapshot_at: datetime = T0,
) -> LiveBookFeed:
    """A :class:`LiveBookFeed` driven into ``status`` (HEALTHY, STALE via an old
    snapshot, DISCONNECTED, or UNINITIALIZED for no snapshot)."""
    lb = LiveBookFeed(contract=_CONTRACT, venue="kalshi", max_staleness=MAX_STALENESS)
    if status is HealthStatus.UNINITIALIZED:
        return lb
    lb.apply_snapshot(
        BookSnapshot(
            venue="kalshi",
            contract_id=_CONTRACT.id,
            bids=levels([("0.40", "100")]),
            asks=levels([("0.60", "100")]),
            sequence=1,
            source_time=snapshot_at,
        ),
        received_at=snapshot_at,
    )
    if status is HealthStatus.DISCONNECTED:
        lb.mark_disconnected(at=snapshot_at)
    return lb


def order(
    *,
    order_id: str = "o1",
    status: OrderStatus = OrderStatus.FILLED,
    quantity: str = "10",
    filled: str = "10",
    price: str = "0.50",
    reject_reason: str = "",
) -> Order:
    req = OrderRequest(
        order_id=order_id,
        venue="kalshi",
        contract_id=_CONTRACT.id,
        side="buy",
        order_type="limit",
        quantity=Decimal(quantity),
        limit_price=Decimal(price),
    )
    fills: tuple[Fill, ...] = ()
    if Decimal(filled) > 0:
        fills = (
            Fill(
                fill_id=f"{order_id}-f1",
                order_id=order_id,
                venue="kalshi",
                contract_id=_CONTRACT.id,
                price=Decimal(price),
                quantity=Decimal(filled),
                fee=Decimal("0.01"),
                liquidity="taker",
                filled_at=T0,
                level_index=0,
            ),
        )
    return Order(
        request=req,
        status=status,
        submitted_at=T0,
        effective_at=T0,
        fills=fills,
        transitions=(StatusTransition(status=status, at=T0, reason=reject_reason),),
        terminal_at=T0 if status.is_terminal else None,
        reject_reason=reject_reason,
    )


def pnl_row(*, realized: str = "1.50", unrealized: str = "0.25", fees: str = "0.05") -> PnlRow:
    return PnlRow(
        scope="portfolio",
        scope_id="paper",
        realized=Decimal(realized),
        unrealized=Decimal(unrealized),
        fees=Decimal(fees),
        as_of=T0,
    )


def _leg(venue: str, outcome: str) -> VenueLeg:
    return VenueLeg(
        venue=venue,
        market_id=f"{venue}-synthetic-market",
        outcome=outcome,
        sources=("https://example.test/doc",),
    )


def _record(pair_id: str, status: PairStatus) -> MarketPairRecord:
    return MarketPairRecord(
        pair_id=pair_id,
        proposition="Synthetic proposition for dashboard tests",
        status=status,
        relation=OutcomeRelation.IDENTICAL,
        kalshi=_leg("kalshi", "YES"),
        polymarket_us=_leg("polymarket_us", "LONG"),
        settlement_notes="synthetic",
        known_differences=(),
        known_differences_reviewed=True,
        checklist=(),
        reviewer="tester",
        verified_at=T0,
        live_use_eligible=False,
        blocking_reason="synthetic test data — never live",
        notes="",
    )


def registry() -> MarketPairRegistry:
    """One VERIFIED + one DRAFT synthetic pair."""
    return MarketPairRegistry(
        [
            _record("DASH-SYNTH-1", PairStatus.VERIFIED),
            _record("DASH-SYNTH-2", PairStatus.DRAFT),
        ]
    )
