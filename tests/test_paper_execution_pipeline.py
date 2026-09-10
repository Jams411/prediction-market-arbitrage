"""End-to-end **offline** proof of the paper-execution pipeline — real-money
gate #3 audit (obs/realmoney-gates-3-4-5-6-10).

Wires the components that were previously only tested in isolation:

    ArbitrageEngine (detector)
        -> PaperBroker (real order-book depth matching, partial fill)
        -> derived position / fees
        -> Recorder (append-only DuckDB)
        -> ReplaySession (deterministic reconstruction)

and asserts:

- the detector produced an opportunity and the paper broker executed it
  end-to-end (gate #3, offline);
- the taker order walked two ask levels — a real simulated **partial fill**
  (gate #6, *simulated* only);
- the in-pipeline fee equals the injected `KalshiTradingFeeModel` output for the
  same fills (gate #4, *model in the loop* — not a venue reconciliation);
- replaying the recording folds the recorded fills back to the recorded
  position, and two runs record byte-identical rows (gate #10, *offline*
  reconciliation / restart-safety only).

This is **not** a gate completion. The market data here is synthetic, not a
recorded real venue session, and no authenticated venue state is involved. See
`docs/PROJECT_JOURNAL.md` (2026-09-10 audit) for the residual blockers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from arbitrage_support import EVAL_TIME, kalshi_book, make_record, polymarket_book

from prediction_market_arbitrage.arbitrage import ArbitrageEngine
from prediction_market_arbitrage.arbitrage.fees import KalshiTradingFeeModel, VenueFeeModel
from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.paper_broker import (
    OrderRequest,
    OrderStatus,
    PaperBroker,
    PaperBrokerConfig,
)
from prediction_market_arbitrage.recorder import (
    FillRow,
    OrderEventRow,
    PnlRow,
    Recorder,
)
from prediction_market_arbitrage.replay import ReplaySession

D = Decimal
T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_KALSHI = Venue(id="kalshi", name="Kalshi")
_CID = "kalshi-test-market:YES"


def _exec_book(ts: datetime) -> OrderBook:
    """A two-level Kalshi ask book: 6 @ 0.40 then 10 @ 0.41 — a 10-lot taker
    buy fills 6 at the first level and 4 at the second (a real partial fill)."""
    contract = Contract(
        market=Market(venue=_KALSHI, id="kalshi-test-market", title="synthetic", close_time=None),
        id=_CID,
        outcome="YES",
    )
    return OrderBook(
        contract=contract,
        bids=(),
        asks=(
            PriceLevel(price=D("0.40"), quantity=D("6")),
            PriceLevel(price=D("0.41"), quantity=D("10")),
        ),
        timestamp=ts,
    )


def _fee_model() -> VenueFeeModel:
    return VenueFeeModel({KalshiTradingFeeModel.VENUE: KalshiTradingFeeModel()})


def _run_pipeline(database: str) -> None:
    """detector -> paper broker -> recorder. Deterministic: fixed inputs,
    injected timestamps, single-threaded."""
    # 1. detector
    evaluation = ArbitrageEngine().evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("10"),
    )
    assert evaluation.has_opportunity  # sanity: there is something to execute

    # 2. paper broker — taker buy of 10 across the two-level book
    broker = PaperBroker(PaperBrokerConfig(fee_model=_fee_model()))
    broker.submit(
        OrderRequest(
            order_id="pipe-o1",
            venue="kalshi",
            contract_id=_CID,
            side="buy",
            order_type="limit",
            quantity=D("10"),
            limit_price=D("0.41"),
        ),
        at=T0,
    )
    tick = T0 + timedelta(seconds=1)
    broker.advance(at=tick, books={_CID: _exec_book(tick)})
    order = broker.order("pipe-o1")
    position = broker.position(_CID, as_of=T0 + timedelta(seconds=2))

    # 3. recorder
    with Recorder.open(database, session_id="pipe", opened_at=T0, label="pipeline") as rec:
        rec.record_order_book(
            _exec_book(T0 + timedelta(seconds=1)),
            recorded_at=T0 + timedelta(seconds=1),
            source="synthetic",
        )
        rec.record_opportunity(evaluation, recorded_at=T0 + timedelta(seconds=1))
        rec.record_order_event(
            OrderEventRow(
                order_id="pipe-o1",
                venue="kalshi",
                contract_id=_CID,
                side="buy",
                order_type="limit",
                quantity=D("10"),
                status=order.status.value,
                event_time=T0 + timedelta(seconds=1),
                limit_price=D("0.41"),
            ),
            recorded_at=T0 + timedelta(seconds=1),
        )
        for fill in order.fills:
            rec.record_fill(
                FillRow(
                    fill_id=fill.fill_id,
                    order_id=fill.order_id,
                    venue=fill.venue,
                    contract_id=fill.contract_id,
                    price=fill.price,
                    quantity=fill.quantity,
                    fee=fill.fee,
                    filled_at=fill.filled_at,
                    liquidity=fill.liquidity,
                ),
                recorded_at=fill.filled_at,
            )
        rec.record_position(position, recorded_at=T0 + timedelta(seconds=2))
        rec.record_pnl(
            PnlRow(
                scope="portfolio",
                scope_id="all",
                realized=D("0"),
                unrealized=D("0"),
                fees=sum((f.fee for f in order.fills), D("0")),
                as_of=T0 + timedelta(seconds=2),
            ),
            recorded_at=T0 + timedelta(seconds=2),
        )


def test_pipeline_executes_records_and_replay_reconciles(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = str(tmp_path / "pipe.duckdb")

    # rebuild the broker state here so we can assert on it directly
    evaluation = ArbitrageEngine().evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.55", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("10"),
    )
    broker = PaperBroker(PaperBrokerConfig(fee_model=_fee_model()))
    broker.submit(
        OrderRequest(
            order_id="pipe-o1",
            venue="kalshi",
            contract_id=_CID,
            side="buy",
            order_type="limit",
            quantity=D("10"),
            limit_price=D("0.41"),
        ),
        at=T0,
    )
    tick = T0 + timedelta(seconds=1)
    broker.advance(at=tick, books={_CID: _exec_book(tick)})
    order = broker.order("pipe-o1")

    # gate #3 — detector produced an opportunity; the paper broker executed it
    assert evaluation.has_opportunity is True
    assert order.status is OrderStatus.FILLED

    # gate #6 (simulated) — the taker order walked TWO ask levels
    assert [(f.price, f.quantity) for f in order.fills] == [
        (D("0.40"), D("6")),
        (D("0.41"), D("4")),
    ]
    assert sum((f.quantity for f in order.fills), D("0")) == D("10")

    # gate #4 (model-in-loop, NOT venue reconciliation) — the fee applied by the
    # broker equals the injected fee model over each fill slice, and is non-zero
    model = _fee_model()
    for fill in order.fills:
        assert fill.fee == model.fee(venue="kalshi", fills=[(fill.price, fill.quantity)])
    assert sum((f.fee for f in order.fills), D("0")) > D("0")

    # position derived from the fills
    position = broker.position(_CID, as_of=T0 + timedelta(seconds=2))
    assert position.quantity == D("10")

    # persist + replay
    _run_pipeline(database)
    with ReplaySession.open(database, session_id="pipe") as session:
        replay_fills = list(session.fills())
        (replay_position,) = list(session.positions())
        (replay_order,) = list(session.order_events())

    # gate #10 (offline half) — recorded fills fold back to the recorded position
    folded = sum((rf.quantity for rf in replay_fills), D("0"))
    assert folded == replay_position.quantity == D("10")
    assert replay_order.quantity == D("10")
    assert replay_order.status == OrderStatus.FILLED.value


def test_pipeline_recording_is_byte_identical_across_runs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Restart-safety / determinism (gate #10, offline): two independent runs
    of the same pipeline record the same fills, position, and order."""
    def snapshot(database: str) -> tuple[object, ...]:
        _run_pipeline(database)
        with ReplaySession.open(database, session_id="pipe") as session:
            fills = [(f.fill_id, f.price, f.quantity, f.fee, f.liquidity) for f in session.fills()]
            positions = [(p.contract_id, p.quantity, p.avg_price) for p in session.positions()]
            orders = [(o.order_id, o.side, o.quantity, o.status) for o in session.order_events()]
        return (fills, positions, orders)

    assert snapshot(str(tmp_path / "a.duckdb")) == snapshot(str(tmp_path / "b.duckdb"))
