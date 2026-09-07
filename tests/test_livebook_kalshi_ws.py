"""Deterministic tests for the Kalshi ``orderbook_delta`` frame decoders (M2.1).

Frames follow the AsyncAPI examples at
``docs.kalshi.com/websockets/orderbook-updates``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from livebook_support import (
    T0,
    kalshi_contract,
    kalshi_delta_frame,
    kalshi_snapshot_frame,
)

from prediction_market_arbitrage.livebook import LiveBookError, LiveBookFeed
from prediction_market_arbitrage.livebook.kalshi_ws import (
    decode_orderbook_delta,
    decode_orderbook_snapshot,
)

D = Decimal
D_STALE = timedelta(seconds=5)


def _yes_feed() -> LiveBookFeed:
    return LiveBookFeed(contract=kalshi_contract("YES"), venue="kalshi", max_staleness=D_STALE)


def test_snapshot_decodes_yes_and_no_books_with_implied_asks() -> None:
    # AsyncAPI example values.
    yes_snapshot, no_snapshot = decode_orderbook_snapshot(
        kalshi_snapshot_frame(
            seq=2,
            yes_fp=[("0.0800", "300.00"), ("0.2200", "333.00")],
            no_fp=[("0.5400", "20.00"), ("0.5600", "146.00")],
        )
    )

    assert yes_snapshot.contract_id == "LIVEBOOK-TEST-T1:YES"
    assert yes_snapshot.sequence == 2
    assert {(lvl.price, lvl.quantity) for lvl in yes_snapshot.bids} == {
        (D("0.0800"), D("300.00")),
        (D("0.2200"), D("333.00")),
    }
    # YES asks are implied by NO bids: price = 1 - no_bid.
    assert {(lvl.price, lvl.quantity) for lvl in yes_snapshot.asks} == {
        (D("0.4600"), D("20.00")),
        (D("0.4400"), D("146.00")),
    }
    assert no_snapshot.contract_id == "LIVEBOOK-TEST-T1:NO"
    assert {(lvl.price, lvl.quantity) for lvl in no_snapshot.asks} == {
        (D("0.9200"), D("300.00")),
        (D("0.7800"), D("333.00")),
    }


def test_snapshot_missing_side_is_empty() -> None:
    yes_snapshot, no_snapshot = decode_orderbook_snapshot(
        kalshi_snapshot_frame(seq=1, yes_fp=[("0.20", "5")], no_fp=None)
    )
    assert yes_snapshot.asks == ()  # no NO bids -> no implied YES asks
    assert no_snapshot.bids == ()


def test_snapshot_applies_through_the_feed_to_a_valid_domain_book() -> None:
    frame = kalshi_snapshot_frame(
        seq=2,
        yes_fp=[("0.0800", "300.00"), ("0.2200", "333.00")],
        no_fp=[("0.5400", "20.00"), ("0.5600", "146.00")],
    )
    yes_snapshot, _ = decode_orderbook_snapshot(frame)
    feed = _yes_feed()
    feed.apply_snapshot(yes_snapshot, received_at=T0)
    book = feed.current_order_book(T0)
    assert book is not None
    assert book.bids[0].price == D("0.2200")
    assert book.asks[0].price == D("0.4400")


def test_delta_decodes_direct_and_implied_pair_with_timestamp() -> None:
    direct, implied = decode_orderbook_delta(
        kalshi_delta_frame(
            seq=3, side="yes", price_dollars="0.9600", delta_fp="-54.00", ts_ms=1669149841000
        )
    )
    assert (direct.contract_id, direct.side, direct.price, direct.quantity_delta) == (
        "LIVEBOOK-TEST-T1:YES",
        "bid",
        D("0.9600"),
        D("-54.00"),
    )
    assert (implied.contract_id, implied.side, implied.price, implied.quantity_delta) == (
        "LIVEBOOK-TEST-T1:NO",
        "ask",
        D("0.0400"),
        D("-54.00"),
    )
    assert direct.sequence == 3
    assert direct.source_time == datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        milliseconds=1669149841000
    )


def test_delta_side_no_mirrors_to_yes_ask() -> None:
    direct, implied = decode_orderbook_delta(
        kalshi_delta_frame(seq=4, side="no", price_dollars="0.3000", delta_fp="12.00")
    )
    assert (direct.contract_id, direct.side) == ("LIVEBOOK-TEST-T1:NO", "bid")
    assert (implied.contract_id, implied.side, implied.price) == (
        "LIVEBOOK-TEST-T1:YES",
        "ask",
        D("0.7000"),
    )
    assert direct.source_time is None


def test_snapshot_then_delta_through_feed_updates_the_book() -> None:
    yes_snapshot, _ = decode_orderbook_snapshot(
        kalshi_snapshot_frame(seq=2, yes_fp=[("0.2000", "100.00")], no_fp=[("0.5000", "40.00")])
    )
    feed = _yes_feed()
    feed.apply_snapshot(yes_snapshot, received_at=T0)

    direct, _ = decode_orderbook_delta(
        kalshi_delta_frame(seq=3, side="yes", price_dollars="0.2000", delta_fp="25.00")
    )
    feed.apply_delta(direct, received_at=T0)
    book = feed.current_order_book(T0)
    assert book is not None
    assert book.bids[0].quantity == D("125.00")


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        ({"type": "wrong", "seq": 1, "msg": {}}, "frame type"),
        (
            kalshi_delta_frame(seq=1, side="maybe", price_dollars="0.5", delta_fp="1"),
            "'yes' or 'no'",
        ),
        (kalshi_delta_frame(seq=1, side="yes", price_dollars="0.5", delta_fp="0.00"), "zero"),
    ],
)
def test_malformed_delta_frames_raise(frame: dict[str, object], match: str) -> None:
    with pytest.raises(LiveBookError, match=match):
        decode_orderbook_delta(frame)


def test_snapshot_non_string_level_raises() -> None:
    frame = kalshi_snapshot_frame(seq=1, yes_fp=[("0.20", "5")], no_fp=None)
    frame["msg"]["yes_dollars_fp"] = [[0.2, "5"]]  # type: ignore[index]
    with pytest.raises(LiveBookError, match="must be strings"):
        decode_orderbook_snapshot(frame)
