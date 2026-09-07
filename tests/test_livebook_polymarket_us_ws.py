"""Deterministic tests for the Polymarket US Markets-WS decoder (M2.1).

Frames follow the example at
``docs.polymarket.us/api-reference/websocket/markets``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from livebook_support import T0, poly_contract, poly_market_data_frame

from prediction_market_arbitrage.livebook import (
    DeltaOutcome,
    HealthStatus,
    LiveBookError,
    LiveBookFeed,
)
from prediction_market_arbitrage.livebook.polymarket_us_ws import decode_market_data

D = Decimal


def _feed() -> LiveBookFeed:
    return LiveBookFeed(
        contract=poly_contract("LONG"),
        venue="polymarket_us",
        max_staleness=timedelta(seconds=5),
        require_sequence=False,
    )


def test_market_data_frame_decodes_to_a_long_snapshot() -> None:
    snapshot = decode_market_data(
        poly_market_data_frame(
            bids=[("0.555", "0.50"), ("0.550", "2.50")],
            offers=[("0.560", "0.80"), ("0.565", "1.50")],
            transact_time="2026-02-01T12:30:00Z",
        )
    )
    assert snapshot.venue == "polymarket_us"
    assert snapshot.contract_id == "livebook-test-market:LONG"
    assert snapshot.sequence is None
    assert snapshot.market_state == "MARKET_STATE_OPEN"
    assert snapshot.source_time == datetime(2026, 2, 1, 12, 30, tzinfo=UTC)
    assert {(lvl.price, lvl.quantity) for lvl in snapshot.bids} == {
        (D("0.555"), D("0.50")),
        (D("0.550"), D("2.50")),
    }
    assert {(lvl.price, lvl.quantity) for lvl in snapshot.asks} == {
        (D("0.560"), D("0.80")),
        (D("0.565"), D("1.50")),
    }


def test_nanosecond_transact_time_is_truncated_to_microseconds() -> None:
    snapshot = decode_market_data(
        poly_market_data_frame(
            bids=[("0.55", "1")], offers=[("0.56", "1")],
            transact_time="2026-02-01T12:30:00.446134874Z",
        )
    )
    assert snapshot.source_time == datetime(2026, 2, 1, 12, 30, 0, 446134, tzinfo=UTC)


def test_absent_transact_time_and_state_are_none() -> None:
    snapshot = decode_market_data(
        poly_market_data_frame(
            bids=[("0.5", "1")], offers=[("0.6", "1")], state=None, transact_time=None
        )
    )
    assert snapshot.source_time is None
    assert snapshot.market_state is None


def test_decoded_snapshot_feeds_a_healthy_book_and_next_frame_replaces_it() -> None:
    feed = _feed()
    first = feed.apply_snapshot(
        decode_market_data(
            poly_market_data_frame(
                bids=[("0.55", "10")], offers=[("0.60", "8")],
                transact_time="2026-02-01T12:00:00Z",
            )
        ),
        received_at=T0,
    )
    assert first.health.status is HealthStatus.HEALTHY

    replaced = feed.apply_snapshot(
        decode_market_data(
            poly_market_data_frame(
                bids=[("0.56", "3")], offers=[("0.61", "9")],
                transact_time="2026-02-01T12:00:01Z",
            )
        ),
        received_at=T0 + timedelta(seconds=1),
    )
    assert replaced.outcome is DeltaOutcome.APPLIED
    book = feed.current_order_book(T0 + timedelta(seconds=1))
    assert book is not None
    assert book.bids[0].price == D("0.56")
    assert book.asks[0].price == D("0.61")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda f: f.__setitem__("subscriptionType", "SUBSCRIPTION_TYPE_TRADE"),
            "subscriptionType",
        ),
        (lambda f: f.__delitem__("marketData"), "marketData"),
        (
            lambda f: f["marketData"]["bids"][0]["px"].__setitem__("currency", "EUR"),
            "expected 'USD'",
        ),
        (
            lambda f: f["marketData"]["bids"][0].__setitem__("qty", 5),
            "qty.*expected a string",
        ),
    ],
)
def test_malformed_market_data_frames_raise(mutate, match: str) -> None:  # type: ignore[no-untyped-def]
    frame = poly_market_data_frame(bids=[("0.55", "1")], offers=[("0.56", "1")])
    mutate(frame)
    with pytest.raises(LiveBookError, match=match):
        decode_market_data(frame)
