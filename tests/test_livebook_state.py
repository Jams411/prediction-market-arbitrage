"""Deterministic tests for the M2.1 live-book state machine and health."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from livebook_support import T0, kalshi_contract, levels, poly_contract

from prediction_market_arbitrage.livebook import (
    BookDelta,
    BookSnapshot,
    DeltaOutcome,
    HealthStatus,
    LiveBookError,
    LiveBookFeed,
)

D = Decimal
STALENESS = timedelta(seconds=5)


def _feed(*, require_sequence: bool = True) -> LiveBookFeed:
    return LiveBookFeed(
        contract=kalshi_contract("YES"),
        venue="kalshi",
        max_staleness=STALENESS,
        require_sequence=require_sequence,
    )


def _snapshot(
    *,
    seq: int | None = 2,
    bids: list[tuple[str, str]],
    asks: list[tuple[str, str]],
    market_state: str | None = None,
) -> BookSnapshot:
    return BookSnapshot(
        venue="kalshi",
        contract_id="LIVEBOOK-TEST-T1:YES",
        bids=levels(bids),
        asks=levels(asks),
        sequence=seq,
        source_time=None,
        market_state=market_state,
    )


def _delta(*, seq: int | None, side: str, price: str, qty: str) -> BookDelta:
    return BookDelta(
        venue="kalshi",
        contract_id="LIVEBOOK-TEST-T1:YES",
        side=side,  # type: ignore[arg-type]
        price=D(price),
        quantity_delta=D(qty),
        sequence=seq,
        source_time=None,
    )


def _init(
    feed: LiveBookFeed,
    *,
    bids: list[tuple[str, str]],
    asks: list[tuple[str, str]],
    seq: int = 2,
) -> None:
    feed.apply_snapshot(_snapshot(seq=seq, bids=bids, asks=asks), received_at=T0)


def _ob(feed: LiveBookFeed, now: object = T0):  # type: ignore[no-untyped-def]
    book = feed.current_order_book(now)  # type: ignore[arg-type]
    assert book is not None
    return book


# --------------------------------------------------------------------------- #
# Snapshot initialization
# --------------------------------------------------------------------------- #


def test_uninitialized_feed_is_not_tradeable() -> None:
    feed = _feed()
    health = feed.health(T0)
    assert health.status is HealthStatus.UNINITIALIZED
    assert health.trading_enabled is False
    assert feed.current_order_book(T0) is None


def test_snapshot_initializes_a_healthy_tradeable_book() -> None:
    feed = _feed()
    result = feed.apply_snapshot(
        _snapshot(bids=[("0.40", "100"), ("0.38", "50")], asks=[("0.44", "70")]),
        received_at=T0,
    )
    assert result.outcome is DeltaOutcome.APPLIED
    assert result.health.status is HealthStatus.HEALTHY
    assert result.health.trading_enabled is True

    book = feed.current_order_book(T0)
    assert book is not None
    assert [(lvl.price, lvl.quantity) for lvl in book.bids] == [
        (D("0.40"), D("100")),
        (D("0.38"), D("50")),
    ]
    assert [(lvl.price, lvl.quantity) for lvl in book.asks] == [(D("0.44"), D("70"))]


def test_crossed_snapshot_desyncs_and_disables_trading() -> None:
    feed = _feed()
    result = feed.apply_snapshot(
        _snapshot(bids=[("0.60", "10")], asks=[("0.50", "10")]), received_at=T0
    )
    assert result.outcome is DeltaOutcome.CROSSED_RESULT
    assert result.health.status is HealthStatus.DESYNCED
    assert feed.current_order_book(T0) is None


# --------------------------------------------------------------------------- #
# Delta application
# --------------------------------------------------------------------------- #


def test_delta_adds_to_existing_level_and_removes_at_zero() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "100")], asks=[("0.44", "70")])

    grew = feed.apply_delta(_delta(seq=3, side="bid", price="0.40", qty="25"), received_at=T0)
    assert grew.outcome is DeltaOutcome.APPLIED
    assert _ob(feed).bids[0].quantity == D("125")

    emptied = feed.apply_delta(_delta(seq=4, side="ask", price="0.44", qty="-70"), received_at=T0)
    assert emptied.outcome is DeltaOutcome.APPLIED
    assert _ob(feed).asks == ()


def test_delta_before_snapshot_raises() -> None:
    with pytest.raises(LiveBookError, match="before any snapshot"):
        _feed().apply_delta(_delta(seq=1, side="bid", price="0.4", qty="1"), received_at=T0)


def test_negative_quantity_delta_desyncs() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.44", "5")])
    result = feed.apply_delta(_delta(seq=3, side="bid", price="0.40", qty="-25"), received_at=T0)
    assert result.outcome is DeltaOutcome.NEGATIVE_QUANTITY
    assert result.health.status is HealthStatus.DESYNCED
    # state left unchanged
    assert feed.book.to_order_book(T0).bids[0].quantity == D("10")


def test_delta_that_crosses_the_book_desyncs_and_rolls_back_sequence() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.60", "10")])
    # Push a new ask level at 0.35, below the best bid -> crossed.
    result = feed.apply_delta(_delta(seq=3, side="ask", price="0.35", qty="4"), received_at=T0)
    assert result.outcome is DeltaOutcome.CROSSED_RESULT
    assert result.health.status is HealthStatus.DESYNCED
    assert feed.last_sequence == 2  # not advanced


# --------------------------------------------------------------------------- #
# Sequence gap detection + resync
# --------------------------------------------------------------------------- #


def test_duplicate_and_stale_sequence_are_ignored() -> None:
    feed = _feed()
    _init(feed, seq=5, bids=[("0.40", "10")], asks=[("0.44", "10")])
    feed.apply_delta(_delta(seq=6, side="bid", price="0.40", qty="1"), received_at=T0)

    dup = feed.apply_delta(_delta(seq=6, side="bid", price="0.40", qty="99"), received_at=T0)
    assert dup.outcome is DeltaOutcome.DUPLICATE
    old = feed.apply_delta(_delta(seq=4, side="bid", price="0.40", qty="99"), received_at=T0)
    assert old.outcome is DeltaOutcome.STALE_SEQUENCE
    assert _ob(feed).bids[0].quantity == D("11")  # unchanged by dup/stale
    assert feed.health(T0).status is HealthStatus.HEALTHY


def test_sequence_gap_desyncs_then_resync_snapshot_restores_health() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.44", "10")])

    gap = feed.apply_delta(_delta(seq=5, side="bid", price="0.40", qty="1"), received_at=T0)
    assert gap.outcome is DeltaOutcome.SEQUENCE_GAP
    assert gap.health.status is HealthStatus.DESYNCED
    assert feed.current_order_book(T0) is None

    # Deltas are ignored while desynced.
    ignored = feed.apply_delta(_delta(seq=6, side="bid", price="0.40", qty="1"), received_at=T0)
    assert ignored.outcome is DeltaOutcome.IGNORED_DESYNCED

    feed.begin_resync(at=T0)
    assert feed.health(T0).status is HealthStatus.RESYNCING
    restored = feed.apply_snapshot(
        _snapshot(seq=9, bids=[("0.41", "20")], asks=[("0.45", "20")]), received_at=T0
    )
    assert restored.health.status is HealthStatus.HEALTHY
    assert feed.last_sequence == 9


# --------------------------------------------------------------------------- #
# Disconnect / staleness
# --------------------------------------------------------------------------- #


def test_disconnect_disables_trading_until_snapshot() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.44", "10")])
    health = feed.mark_disconnected(at=T0)
    assert health.status is HealthStatus.DISCONNECTED
    assert feed.current_order_book(T0) is None
    feed.begin_resync(at=T0)
    _init(feed, seq=3, bids=[("0.40", "10")], asks=[("0.44", "10")])
    assert feed.health(T0).status is HealthStatus.HEALTHY


def test_feed_goes_stale_after_max_staleness() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.44", "10")])
    assert feed.health(T0 + STALENESS).status is HealthStatus.HEALTHY
    stale = feed.health(T0 + STALENESS + timedelta(seconds=1))
    assert stale.status is HealthStatus.STALE
    assert stale.trading_enabled is False


def test_now_before_last_update_is_treated_as_stale() -> None:
    feed = _feed()
    _init(feed, seq=2, bids=[("0.40", "10")], asks=[("0.44", "10")])
    assert feed.health(T0 - timedelta(seconds=1)).status is HealthStatus.STALE


def test_naive_datetime_is_rejected() -> None:
    from datetime import datetime

    feed = _feed()
    with pytest.raises(LiveBookError, match="timezone-aware"):
        feed.health(datetime(2026, 2, 1, 12, 0, 0))  # noqa: DTZ001


# --------------------------------------------------------------------------- #
# Target mismatch + market state
# --------------------------------------------------------------------------- #


def test_wrong_contract_or_venue_message_raises() -> None:
    feed = _feed()
    bad = BookSnapshot(
        venue="kalshi",
        contract_id="OTHER:YES",
        bids=levels([("0.4", "1")]),
        asks=(),
        sequence=1,
        source_time=None,
    )
    with pytest.raises(LiveBookError, match="does not match feed contract"):
        feed.apply_snapshot(bad, received_at=T0)


def test_non_open_market_state_disables_trading() -> None:
    feed = LiveBookFeed(
        contract=poly_contract("LONG"),
        venue="polymarket_us",
        max_staleness=STALENESS,
        require_sequence=False,
    )
    snap = BookSnapshot(
        venue="polymarket_us",
        contract_id="livebook-test-market:LONG",
        bids=levels([("0.40", "10")]),
        asks=levels([("0.60", "10")]),
        sequence=None,
        source_time=T0,
        market_state="MARKET_STATE_HALTED",
    )
    result = feed.apply_snapshot(snap, received_at=T0)
    assert result.health.status is HealthStatus.MARKET_NOT_OPEN
    assert result.health.trading_enabled is False


def test_polymarket_style_feed_replaces_book_each_snapshot_and_drops_reordered() -> None:
    feed = LiveBookFeed(
        contract=poly_contract("LONG"),
        venue="polymarket_us",
        max_staleness=STALENESS,
        require_sequence=False,
    )

    def snap(bid_qty: str, *, source_time: object) -> BookSnapshot:
        return BookSnapshot(
            venue="polymarket_us",
            contract_id="livebook-test-market:LONG",
            bids=levels([("0.40", bid_qty)]),
            asks=levels([("0.60", "10")]),
            sequence=None,
            source_time=source_time,  # type: ignore[arg-type]
            market_state="MARKET_STATE_OPEN",
        )

    feed.apply_snapshot(snap("10", source_time=T0 + timedelta(seconds=2)), received_at=T0)
    fresh = feed.apply_snapshot(snap("25", source_time=T0 + timedelta(seconds=3)), received_at=T0)
    assert fresh.outcome is DeltaOutcome.APPLIED
    assert _ob(feed).bids[0].quantity == D("25")

    reordered = feed.apply_snapshot(
        snap("99", source_time=T0 + timedelta(seconds=1)), received_at=T0
    )
    assert reordered.outcome is DeltaOutcome.STALE_SEQUENCE
    assert _ob(feed).bids[0].quantity == D("25")  # unchanged
