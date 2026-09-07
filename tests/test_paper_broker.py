"""Deterministic offline tests for the M2.4 paper broker."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from paper_broker_support import CONTRACT_ID, T0, at, book, request

from prediction_market_arbitrage.arbitrage import FixedPerUnitFeeModel
from prediction_market_arbitrage.paper_broker import (
    FixedOffsetSlippage,
    OrderRequest,
    OrderStatus,
    PaperBroker,
    PaperBrokerConfig,
    PaperBrokerError,
    PerLevelSlippage,
)

D = Decimal


def _books(ob, contract_id: str = CONTRACT_ID):  # type: ignore[no-untyped-def]
    return {contract_id: ob}


# --------------------------------------------------------------------------- #
# latency
# --------------------------------------------------------------------------- #


def test_order_does_not_fill_until_submit_latency_elapses() -> None:
    broker = PaperBroker(PaperBrokerConfig(submit_latency=timedelta(seconds=2)))
    broker.submit(request("o1", quantity="10"), at=at(0))

    early = broker.advance(at=at(1), books=_books(book(asks=[("0.44", "50")], timestamp=at(1))))
    assert early == ()
    assert broker.order("o1").status is OrderStatus.SUBMITTED

    later = broker.advance(at=at(2), books=_books(book(asks=[("0.44", "50")], timestamp=at(2))))
    assert broker.order("o1").status is OrderStatus.FILLED
    assert any(e.kind == "fill" for e in later)


def test_book_older_than_effective_time_does_not_fill() -> None:
    broker = PaperBroker(PaperBrokerConfig(submit_latency=timedelta(seconds=2)))
    broker.submit(request("o1", quantity="10"), at=at(0))
    # advance to t=3 but the book is stamped t=1 (before the order reached the engine)
    events = broker.advance(at=at(3), books=_books(book(asks=[("0.44", "50")], timestamp=at(1))))
    assert events == ()
    assert broker.order("o1").status is OrderStatus.SUBMITTED


# --------------------------------------------------------------------------- #
# depth / partial fills
# --------------------------------------------------------------------------- #


def test_limit_buy_walks_depth_and_partially_fills_then_completes() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="100", limit_price="0.50"), at=at(0))

    broker.advance(
        at=at(1),
        books=_books(book(asks=[("0.44", "30"), ("0.46", "40")], timestamp=at(1))),
    )
    order = broker.order("o1")
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == D("70")
    assert order.remaining_quantity == D("30")
    assert [(f.price, f.quantity) for f in order.fills] == [
        (D("0.44"), D("30")),
        (D("0.46"), D("40")),
    ]

    broker.advance(at=at(2), books=_books(book(asks=[("0.47", "100")], timestamp=at(2))))
    done = broker.order("o1")
    assert done.status is OrderStatus.FILLED
    assert done.filled_quantity == D("100")
    assert done.average_fill_price == (D("0.44") * 30 + D("0.46") * 40 + D("0.47") * 30) / D("100")


def test_limit_price_caps_the_walk() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="100", limit_price="0.45"), at=at(0))
    broker.advance(
        at=at(1),
        books=_books(book(asks=[("0.44", "20"), ("0.46", "50")], timestamp=at(1))),
    )
    order = broker.order("o1")
    assert order.filled_quantity == D("20")  # 0.46 level is above the 0.45 limit
    assert order.status is OrderStatus.PARTIALLY_FILLED


def test_sell_walks_the_bid_side() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", side="sell", quantity="10", limit_price="0.40"), at=at(0))
    broker.advance(
        at=at(1), books=_books(book(bids=[("0.45", "4"), ("0.42", "9")], timestamp=at(1)))
    )
    order = broker.order("o1")
    assert order.status is OrderStatus.FILLED
    assert [(f.price, f.quantity) for f in order.fills] == [
        (D("0.45"), D("4")),
        (D("0.42"), D("6")),
    ]


# --------------------------------------------------------------------------- #
# rejections
# --------------------------------------------------------------------------- #


def test_below_min_order_size_is_rejected_on_submit() -> None:
    broker = PaperBroker(PaperBrokerConfig(min_order_size=D("5")))
    order = broker.submit(request("o1", quantity="3"), at=at(0))
    assert order.status is OrderStatus.REJECTED
    assert "below min" in order.reject_reason


def test_ioc_with_no_eligible_liquidity_is_rejected() -> None:
    broker = PaperBroker()
    broker.submit(
        request("o1", quantity="10", limit_price="0.40", immediate_or_cancel=True), at=at(0)
    )
    events = broker.advance(at=at(1), books=_books(book(asks=[("0.45", "50")], timestamp=at(1))))
    assert broker.order("o1").status is OrderStatus.REJECTED
    assert events[-1].order.status is OrderStatus.REJECTED


def test_ioc_partial_fill_cancels_the_remainder() -> None:
    broker = PaperBroker()
    broker.submit(
        request("o1", quantity="50", limit_price="0.50", immediate_or_cancel=True), at=at(0)
    )
    broker.advance(at=at(1), books=_books(book(asks=[("0.44", "20")], timestamp=at(1))))
    order = broker.order("o1")
    assert order.status is OrderStatus.CANCELED
    assert order.filled_quantity == D("20")
    assert "IOC unfilled remainder" in order.transitions[-1].reason


def test_duplicate_order_id_raises() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="1"), at=at(0))
    with pytest.raises(PaperBrokerError, match="duplicate order_id"):
        broker.submit(request("o1", quantity="1"), at=at(1))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": D("0"), "limit_price": D("0.5")},
        {"quantity": D("1"), "order_type": "market", "limit_price": D("0.5")},
        {"quantity": D("1"), "limit_price": D("1.5")},
        {"quantity": D("-1"), "limit_price": D("0.5")},
    ],
)
def test_malformed_request_raises(kwargs: dict[str, object]) -> None:
    with pytest.raises(PaperBrokerError):
        OrderRequest(
            order_id="bad",
            venue="kalshi",
            contract_id="c",
            side="buy",
            order_type=str(kwargs.get("order_type", "limit")),
            quantity=kwargs["quantity"],  # type: ignore[arg-type]
            limit_price=kwargs.get("limit_price"),  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# slippage (deterministic)
# --------------------------------------------------------------------------- #


def test_fixed_offset_slippage_worsens_every_fill() -> None:
    broker = PaperBroker(PaperBrokerConfig(slippage=FixedOffsetSlippage(D("0.01"))))
    broker.submit(request("b", side="buy", quantity="5", limit_price="0.60"), at=at(0))
    broker.submit(request("s", side="sell", quantity="5", limit_price="0.30"), at=at(0))
    broker.advance(
        at=at(1),
        books=_books(book(bids=[("0.40", "10")], asks=[("0.44", "10")], timestamp=at(1))),
    )
    assert broker.order("b").fills[0].price == D("0.45")  # 0.44 + 0.01
    assert broker.order("s").fills[0].price == D("0.39")  # 0.40 - 0.01


def test_per_level_slippage_scales_with_depth() -> None:
    broker = PaperBroker(PaperBrokerConfig(slippage=PerLevelSlippage(D("0.005"))))
    broker.submit(request("o1", quantity="30", limit_price="0.60"), at=at(0))
    broker.advance(
        at=at(1),
        books=_books(book(asks=[("0.44", "10"), ("0.46", "10"), ("0.48", "10")], timestamp=at(1))),
    )
    prices = [f.price for f in broker.order("o1").fills]
    assert prices == [D("0.44"), D("0.465"), D("0.49")]  # +0, +0.005, +0.010


def test_slippage_result_is_clamped_into_the_open_interval() -> None:
    broker = PaperBroker(PaperBrokerConfig(slippage=FixedOffsetSlippage(D("0.9"))))
    broker.submit(request("o1", quantity="1", limit_price="0.60"), at=at(0))
    broker.advance(at=at(1), books=_books(book(asks=[("0.44", "5")], timestamp=at(1))))
    assert broker.order("o1").fills[0].price == D("0.9999")


# --------------------------------------------------------------------------- #
# cancellation
# --------------------------------------------------------------------------- #


def test_cancel_takes_effect_only_after_cancel_latency() -> None:
    broker = PaperBroker(PaperBrokerConfig(cancel_latency=timedelta(seconds=1)))
    broker.submit(request("o1", quantity="10", limit_price="0.30"), at=at(0))  # rests
    broker.advance(at=at(1), books=_books(book(asks=[("0.45", "50")], timestamp=at(1))))
    assert broker.order("o1").status is OrderStatus.SUBMITTED

    broker.cancel("o1", at=at(2))
    broker.advance(at=at(2.5), books=_books(book(asks=[("0.45", "50")], timestamp=at(2.5))))
    assert broker.order("o1").status is OrderStatus.SUBMITTED  # cancel not effective yet

    broker.advance(at=at(3), books=_books(book(asks=[("0.45", "50")], timestamp=at(3))))
    order = broker.order("o1")
    assert order.status is OrderStatus.CANCELED
    assert order.terminal_at == at(3)  # cancel_effective_at = 2 + 1


def test_a_fill_beats_a_slower_cancel() -> None:
    broker = PaperBroker(PaperBrokerConfig(cancel_latency=timedelta(seconds=5)))
    broker.submit(request("o1", quantity="10", limit_price="0.50"), at=at(0))
    broker.cancel("o1", at=at(1))  # effective at t=6
    broker.advance(at=at(2), books=_books(book(asks=[("0.44", "50")], timestamp=at(2))))
    assert broker.order("o1").status is OrderStatus.FILLED  # filled at t=2, before cancel


def test_cancel_after_terminal_is_a_noop() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="5", limit_price="0.50"), at=at(0))
    broker.advance(at=at(1), books=_books(book(asks=[("0.44", "10")], timestamp=at(1))))
    assert broker.order("o1").status is OrderStatus.FILLED
    same = broker.cancel("o1", at=at(2))
    assert same.status is OrderStatus.FILLED


# --------------------------------------------------------------------------- #
# market-order TTL / expiry
# --------------------------------------------------------------------------- #


def test_market_order_remainder_expires_after_ttl() -> None:
    broker = PaperBroker(
        PaperBrokerConfig(
            market_order_ttl=timedelta(seconds=5), reject_on_no_immediate_fill=False
        )
    )
    broker.submit(request("o1", order_type="market", quantity="100"), at=at(0))
    broker.advance(at=at(1), books=_books(book(asks=[("0.44", "40")], timestamp=at(1))))
    assert broker.order("o1").status is OrderStatus.PARTIALLY_FILLED

    broker.advance(at=at(7), books=_books(book(asks=[("0.44", "0.01")], timestamp=at(7))))
    order = broker.order("o1")
    assert order.status is OrderStatus.EXPIRED
    assert order.filled_quantity < D("100")


# --------------------------------------------------------------------------- #
# leg risk
# --------------------------------------------------------------------------- #


def test_leg_risk_reports_one_legged_exposure() -> None:
    broker = PaperBroker()
    broker.submit(request("legA", quantity="10", limit_price="0.50"), at=at(0))
    broker.submit(
        request("legB", quantity="10", limit_price="0.50", contract_id="PB-T2:YES"), at=at(0)
    )
    a_book = book(asks=[("0.44", "10")], timestamp=at(1))
    # legB only has 3 units available at/under its 0.50 limit; the rest of the
    # book (0.55) sets the mid used to price the missing leg.
    b_book = book(
        bids=[("0.46", "5")], asks=[("0.48", "3"), ("0.55", "20")], timestamp=at(1), ticker="PB-T2"
    )
    broker.advance(at=at(1), books={CONTRACT_ID: a_book, "PB-T2:YES": b_book})

    assert broker.order("legA").status is OrderStatus.FILLED
    assert broker.order("legB").filled_quantity == D("3")
    assert broker.order("legB").status is OrderStatus.PARTIALLY_FILLED

    risk = broker.leg_risk(
        "legA", "legB", as_of=at(1), books={CONTRACT_ID: a_book, "PB-T2:YES": b_book}
    )
    assert risk.a_filled_quantity == D("10")
    assert risk.b_filled_quantity == D("3")
    assert risk.unhedged_quantity == D("7")
    assert risk.hedge_completion_price == (D("0.46") + D("0.48")) / D("2")
    assert risk.unhedged_notional == D("7") * ((D("0.46") + D("0.48")) / D("2"))
    assert risk.both_terminal is False


# --------------------------------------------------------------------------- #
# fees / positions / recorder integration
# --------------------------------------------------------------------------- #


def test_injected_fee_model_is_applied_per_fill() -> None:
    broker = PaperBroker(PaperBrokerConfig(fee_model=FixedPerUnitFeeModel(D("0.01"))))
    broker.submit(request("o1", quantity="10", limit_price="0.50"), at=at(0))
    broker.advance(
        at=at(1),
        books=_books(book(asks=[("0.44", "4"), ("0.46", "6")], timestamp=at(1))),
    )
    fills = broker.order("o1").fills
    assert [f.fee for f in fills] == [D("0.04"), D("0.06")]
    assert broker.order("o1").total_fees == D("0.10")


def test_position_accounting_averages_then_flattens() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="10", limit_price="0.60"), at=at(0))
    broker.advance(at=at(1), books=_books(book(asks=[("0.40", "10")], timestamp=at(1))))
    broker.submit(request("o2", quantity="10", limit_price="0.60"), at=at(2))
    broker.advance(at=at(3), books=_books(book(asks=[("0.50", "10")], timestamp=at(3))))
    pos = broker.position(CONTRACT_ID, as_of=at(3))
    assert pos.quantity == D("20")
    assert pos.avg_price == D("0.45")

    broker.submit(request("o3", side="sell", quantity="20", limit_price="0.30"), at=at(4))
    broker.advance(at=at(5), books=_books(book(bids=[("0.40", "20")], timestamp=at(5))))
    flat = broker.position(CONTRACT_ID, as_of=at(5))
    assert flat.quantity == D("0")
    assert flat.avg_price == D("0")


def test_snapshots_convert_to_recorder_rows_and_persist(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from prediction_market_arbitrage.recorder import Recorder

    broker = PaperBroker(PaperBrokerConfig(fee_model=FixedPerUnitFeeModel(D("0.01"))))
    broker.submit(request("o1", quantity="6", limit_price="0.50"), at=at(0))
    broker.advance(
        at=at(1), books=_books(book(asks=[("0.44", "4"), ("0.46", "6")], timestamp=at(1)))
    )
    order = broker.order("o1")

    db = str(tmp_path / "pb.duckdb")
    rec = Recorder.open(db, session_id="pb", opened_at=T0)
    for row in order.event_rows():
        rec.record_order_event(row, recorded_at=at(1))
    for fill in order.fills:
        rec.record_fill(fill.to_row(), recorded_at=at(1))
    rec.record_position(broker.position(CONTRACT_ID, as_of=at(1)), recorded_at=at(1))

    assert rec.connection.execute("SELECT count(*) FROM fills").fetchone() == (2,)
    statuses = [
        r[0] for r in rec.connection.execute(
            "SELECT status FROM order_events ORDER BY id"
        ).fetchall()
    ]
    assert statuses == ["submitted", "filled"]
    assert rec.connection.execute("SELECT quantity FROM positions").fetchone() == ("6",)
    rec.close()


# --------------------------------------------------------------------------- #
# determinism / misuse
# --------------------------------------------------------------------------- #


def test_identical_scripts_produce_identical_state() -> None:
    def run() -> tuple[object, ...]:
        broker = PaperBroker(PaperBrokerConfig(slippage=PerLevelSlippage(D("0.001"))))
        broker.submit(request("o1", quantity="50", limit_price="0.60"), at=at(0))
        broker.submit(request("o2", side="sell", quantity="20", limit_price="0.30"), at=at(0))
        broker.advance(
            at=at(1),
            books=_books(
                book(bids=[("0.40", "25")], asks=[("0.44", "20"), ("0.46", "40")], timestamp=at(1))
            ),
        )
        return tuple(
            (o.order_id, o.status, o.filled_quantity, o.average_fill_price, o.total_fees)
            for o in broker.orders()
        )

    assert run() == run()


def test_time_must_not_move_backwards() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="1"), at=at(5))
    with pytest.raises(PaperBrokerError, match="before the broker clock"):
        broker.advance(at=at(4))


def test_naive_datetime_is_rejected() -> None:
    from datetime import datetime

    broker = PaperBroker()
    with pytest.raises(PaperBrokerError, match="timezone-aware"):
        broker.submit(request("o1", quantity="1"), at=datetime(2026, 3, 2, 15))  # noqa: DTZ001


def test_order_event_rows_mirror_the_transition_history() -> None:
    broker = PaperBroker()
    broker.submit(request("o1", quantity="10", limit_price="0.50"), at=at(0))
    broker.advance(at=at(1), books=_books(book(asks=[("0.44", "4")], timestamp=at(1))))
    broker.advance(at=at(2), books=_books(book(asks=[("0.45", "10")], timestamp=at(2))))
    rows = broker.order("o1").event_rows()
    assert [r.status for r in rows] == ["submitted", "partially_filled", "filled"]
    assert all(r.order_id == "o1" and r.contract_id == CONTRACT_ID for r in rows)
    assert rows[-1].event_time == at(2)
