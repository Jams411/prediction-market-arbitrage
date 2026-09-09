"""Deterministic tests for M1.5 same-market complete-set arbitrage.

``ArbitrageEngine.evaluate_complete_set`` — buy one unit of every mutually
exclusive outcome of a single market; a matched set pays exactly 1 per unit, so
a set costing < 1 (after fees + execution buffer) is a locked-in edge. Exact
Decimal arithmetic throughout.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from arbitrage_support import (
    EVAL_TIME,
    KALSHI_MARKET,
    POLY_VENUE,
    TS,
    outcome_book,
)

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    ArbitrageError,
    CompleteSetEvaluation,
    EngineConfig,
    FixedPerUnitFeeModel,
    OpportunityEvaluation,
)
from prediction_market_arbitrage.domain import Opportunity, OrderBook
from prediction_market_arbitrage.recorder import Recorder, RecorderError

D = Decimal
DEEP = "100"  # level quantity large enough that only the top price is used


def _binary(
    yes_ask: str,
    no_ask: str,
    *,
    yes_qty: str = DEEP,
    no_qty: str = DEEP,
    yes_ts: datetime = TS,
    no_ts: datetime = TS,
) -> list[OrderBook]:
    return [
        outcome_book("YES", [(yes_ask, yes_qty)], timestamp=yes_ts),
        outcome_book("NO", [(no_ask, no_qty)], timestamp=no_ts),
    ]


def _evaluate(
    books: list[OrderBook],
    *,
    config: EngineConfig | None = None,
    requested: Decimal | None = None,
    at: datetime = EVAL_TIME,
) -> CompleteSetEvaluation:
    engine = ArbitrageEngine(config) if config is not None else ArbitrageEngine()
    return engine.evaluate_complete_set(books, evaluation_time=at, requested_quantity=requested)


# --------------------------------------------------------------------------- #
# Core economic cases: profitable / breakeven / unprofitable
# --------------------------------------------------------------------------- #


def test_profitable_complete_set() -> None:
    result = _evaluate(_binary("0.40", "0.55"))
    assert isinstance(result, CompleteSetEvaluation)
    assert result.market_id == KALSHI_MARKET
    assert result.venue == "kalshi"
    assert result.outcome_count == 2
    assert result.executable_quantity == D("100")
    assert result.gross_total_cost == D("95.00")
    assert result.gross_edge == D("5.00")
    assert result.fees == D(0)
    assert result.execution_buffer == D(0)
    assert result.net_edge == D("5.00")
    assert result.has_opportunity is True
    assert result.rejection_reason == ""
    assert result.expected_total_profit == D("5.00")
    assert result.net_edge_per_unit == D("0.05")


def test_break_even_complete_set_is_not_an_opportunity() -> None:
    result = _evaluate(_binary("0.40", "0.60"))
    assert result.gross_total_cost == D("100.00")
    assert result.net_edge == D("0.00")
    assert result.has_opportunity is False
    assert "break-even" in result.rejection_reason


def test_unprofitable_complete_set() -> None:
    result = _evaluate(_binary("0.50", "0.55"))
    assert result.net_edge == D("-5.00")
    assert result.has_opportunity is False
    assert "negative" in result.rejection_reason


# --------------------------------------------------------------------------- #
# Depth, executable quantity, caps
# --------------------------------------------------------------------------- #


def test_executable_quantity_is_min_depth_across_outcomes() -> None:
    result = _evaluate(_binary("0.40", "0.55", yes_qty="4", no_qty="9"))
    assert result.executable_quantity == D("4")
    assert result.gross_total_cost == D("0.40") * 4 + D("0.55") * 4
    assert result.net_edge == D("4") - result.gross_total_cost
    assert result.has_opportunity is True


def test_depth_weighted_cost_walks_multiple_levels() -> None:
    books = [
        outcome_book("YES", [("0.40", "2"), ("0.44", "8")]),
        outcome_book("NO", [("0.55", "100")]),
    ]
    result = _evaluate(books, requested=D("5"))
    # YES: 0.40*2 + 0.44*3 = 2.12 ; NO: 0.55*5 = 2.75
    assert result.legs[0].acquisition_cost == D("2.12")
    assert result.legs[1].acquisition_cost == D("2.75")
    assert result.gross_total_cost == D("4.87")
    assert result.executable_quantity == D("5")
    assert result.gross_edge == D("0.13")
    assert result.has_opportunity is True


def test_requested_quantity_caps_size() -> None:
    result = _evaluate(_binary("0.40", "0.55"), requested=D("10"))
    assert result.executable_quantity == D("10")
    assert result.depth_capped is False
    assert result.net_edge == D("0.50")


def test_max_quantity_config_caps_size() -> None:
    result = _evaluate(_binary("0.40", "0.55"), config=EngineConfig(max_quantity=D("7")))
    assert result.executable_quantity == D("7")


# --------------------------------------------------------------------------- #
# Insufficient depth
# --------------------------------------------------------------------------- #


def test_insufficient_depth_is_depth_capped_by_default() -> None:
    result = _evaluate(_binary("0.40", "0.55", yes_qty="3", no_qty="10"), requested=D("5"))
    assert result.executable_quantity == D("3")
    assert result.depth_capped is True
    assert result.has_opportunity is True


def test_insufficient_depth_rejected_under_require_full_fill() -> None:
    result = _evaluate(
        _binary("0.40", "0.55", yes_qty="3", no_qty="10"),
        config=EngineConfig(require_full_fill=True),
        requested=D("5"),
    )
    assert result.has_opportunity is False
    assert result.executable_quantity == D(0)
    assert "insufficient depth" in result.rejection_reason


def test_empty_ask_side_on_one_outcome_is_not_an_opportunity() -> None:
    books = [outcome_book("YES", [("0.40", "100")]), outcome_book("NO", [])]
    result = _evaluate(books)
    assert result.has_opportunity is False
    assert "empty ask side" in result.rejection_reason


# --------------------------------------------------------------------------- #
# Stale-data / freshness
# --------------------------------------------------------------------------- #


def test_stale_book_rejected_by_max_age() -> None:
    old = EVAL_TIME - timedelta(minutes=5)
    result = _evaluate(
        _binary("0.40", "0.55", no_ts=old),
        config=EngineConfig(max_book_age=timedelta(seconds=30)),
    )
    assert result.has_opportunity is False
    assert "stale" in result.rejection_reason


def test_book_timestamp_after_evaluation_time_rejected() -> None:
    future = EVAL_TIME + timedelta(seconds=1)
    result = _evaluate(
        _binary("0.40", "0.55", no_ts=future),
        config=EngineConfig(max_book_age=timedelta(minutes=10)),
    )
    assert result.has_opportunity is False
    assert "after evaluation_time" in result.rejection_reason


def test_excessive_cross_book_skew_rejected() -> None:
    skewed = TS + timedelta(seconds=45)
    result = _evaluate(
        _binary("0.40", "0.55", no_ts=skewed),
        config=EngineConfig(max_cross_book_skew=timedelta(seconds=10)),
    )
    assert result.has_opportunity is False
    assert "skew" in result.rejection_reason


def test_fresh_books_within_limits_still_produce_the_opportunity() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(
            max_book_age=timedelta(minutes=10), max_cross_book_skew=timedelta(seconds=30)
        ),
    )
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# Fees and execution buffer
# --------------------------------------------------------------------------- #


def test_fees_are_summed_across_every_outcome_and_reduce_edge() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(fee_model=FixedPerUnitFeeModel(D("0.03"))),
    )
    # 0.03 * 100 per outcome, two outcomes -> 6.00 total.
    assert result.fees == D("6.00")
    assert result.net_edge == D("5.00") - D("6.00")
    assert result.has_opportunity is False


def test_execution_buffer_reduces_but_can_leave_an_edge() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(execution_buffer_per_unit=D("0.02")),
    )
    assert result.execution_buffer == D("2.00")
    assert result.net_edge == D("3.00")
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# Slippage reserve on the complete-set path
# --------------------------------------------------------------------------- #


def test_zero_slippage_reserve_leaves_the_complete_set_result_unchanged() -> None:
    baseline = _evaluate(_binary("0.40", "0.55"))
    with_zero = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(slippage_reserve_per_unit=D("0")),
    )
    assert with_zero.slippage_reserve == D("0")
    assert with_zero.net_edge == baseline.net_edge == D("5.00")
    assert with_zero.has_opportunity is True


def test_positive_slippage_reserve_reduces_complete_set_net_edge() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(slippage_reserve_per_unit=D("0.02")),
    )
    assert result.slippage_reserve == D("2.00")  # 0.02 * 100 matched sets
    assert result.net_total_cost == D("95.00") + D("2.00")
    assert result.net_edge == D("3.00")
    assert result.has_opportunity is True


def test_slippage_reserve_can_zero_out_a_complete_set_edge() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(slippage_reserve_per_unit=D("0.05")),
    )
    assert result.slippage_reserve == D("5.00")
    assert result.net_edge == D("0.00")
    assert result.has_opportunity is False
    assert "break-even" in result.rejection_reason


def test_slippage_reserve_can_make_a_complete_set_unprofitable() -> None:
    result = _evaluate(
        _binary("0.40", "0.55"),
        config=EngineConfig(slippage_reserve_per_unit=D("0.06")),
    )
    assert result.net_edge == D("-1.00")
    assert result.has_opportunity is False
    assert "negative" in result.rejection_reason


def test_slippage_reserve_applies_to_a_categorical_complete_set() -> None:
    books = [
        outcome_book("A", [("0.30", "100")]),
        outcome_book("B", [("0.30", "100")]),
        outcome_book("C", [("0.35", "100")]),
    ]
    result = _evaluate(books, config=EngineConfig(slippage_reserve_per_unit=D("0.02")))
    assert result.slippage_reserve == D("2.00")
    assert result.net_edge == D("3.00")
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# Categorical (N > 2) outcome sets
# --------------------------------------------------------------------------- #


def test_three_way_categorical_complete_set() -> None:
    books = [
        outcome_book("A", [("0.30", "100")]),
        outcome_book("B", [("0.30", "100")]),
        outcome_book("C", [("0.35", "100")]),
    ]
    result = _evaluate(books)
    assert result.outcome_count == 3
    assert result.gross_total_cost == D("95.00")
    assert result.net_edge == D("5.00")
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# to_opportunity()
# --------------------------------------------------------------------------- #


def test_to_opportunity_from_a_binary_complete_set() -> None:
    result = _evaluate(_binary("0.40", "0.55"))
    opp = result.to_opportunity()
    assert isinstance(opp, Opportunity)
    assert opp.pair.id == KALSHI_MARKET
    assert opp.quantity == D("100")
    assert opp.edge == D("0.05")
    assert opp.timestamp == EVAL_TIME


def test_to_opportunity_rejects_a_categorical_set() -> None:
    books = [
        outcome_book("A", [("0.30", "100")]),
        outcome_book("B", [("0.30", "100")]),
        outcome_book("C", [("0.35", "100")]),
    ]
    result = _evaluate(books)
    with pytest.raises(ArbitrageError, match="exactly 2 outcomes"):
        result.to_opportunity()


def test_to_opportunity_rejects_when_no_opportunity() -> None:
    result = _evaluate(_binary("0.50", "0.55"))
    with pytest.raises(ArbitrageError, match="no opportunity"):
        result.to_opportunity()


# --------------------------------------------------------------------------- #
# Misuse -> ArbitrageError
# --------------------------------------------------------------------------- #


def test_fewer_than_two_books_is_misuse() -> None:
    with pytest.raises(ArbitrageError, match="at least two"):
        _evaluate([outcome_book("YES", [("0.40", "100")])])


def test_non_orderbook_is_misuse() -> None:
    bad = [outcome_book("YES", [("0.40", "100")]), "not-a-book"]
    with pytest.raises(ArbitrageError, match="must be an OrderBook"):
        _evaluate(bad)  # type: ignore[arg-type]


def test_mixed_market_is_misuse() -> None:
    books = [
        outcome_book("YES", [("0.40", "100")], market="market-one"),
        outcome_book("NO", [("0.55", "100")], market="market-two"),
    ]
    with pytest.raises(ArbitrageError, match="same venue and market"):
        _evaluate(books)


def test_mixed_venue_is_misuse() -> None:
    books = [
        outcome_book("YES", [("0.40", "100")]),
        outcome_book("NO", [("0.55", "100")], venue=POLY_VENUE),
    ]
    with pytest.raises(ArbitrageError, match="same venue and market"):
        _evaluate(books)


def test_duplicate_outcome_is_misuse() -> None:
    books = [
        outcome_book("YES", [("0.40", "100")]),
        outcome_book("YES", [("0.30", "100")]),
    ]
    with pytest.raises(ArbitrageError, match="distinct outcomes"):
        _evaluate(books)


def test_naive_evaluation_time_is_misuse() -> None:
    with pytest.raises(ArbitrageError, match="timezone-aware"):
        ArbitrageEngine().evaluate_complete_set(
            _binary("0.40", "0.55"), evaluation_time=datetime(2026, 1, 2, 0, 1)
        )


@pytest.mark.parametrize("bad", [D("0"), D("-1")])
def test_non_positive_requested_quantity_is_misuse(bad: Decimal) -> None:
    with pytest.raises(ArbitrageError, match="must be > 0"):
        _evaluate(_binary("0.40", "0.55"), requested=bad)


def test_float_requested_quantity_is_misuse() -> None:
    with pytest.raises(ArbitrageError, match="finite Decimal"):
        _evaluate(_binary("0.40", "0.55"), requested=5.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Exact Decimal precision
# --------------------------------------------------------------------------- #


def test_decimal_precision_is_preserved() -> None:
    books = [
        outcome_book("YES", [("0.333333", "1")]),
        outcome_book("NO", [("0.444444", "1")]),
    ]
    result = _evaluate(books)
    assert result.gross_total_cost == D("0.777777")
    assert result.net_edge == D("1") - D("0.777777")
    assert result.net_edge == D("0.222223")
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# Safety boundary: a complete-set result cannot masquerade as a
# registry-verified cross-venue OpportunityEvaluation downstream.
# --------------------------------------------------------------------------- #


def test_complete_set_evaluation_is_a_distinct_type_from_opportunity_evaluation() -> None:
    result = _evaluate(_binary("0.40", "0.55"))
    assert not isinstance(result, OpportunityEvaluation)
    assert not issubclass(CompleteSetEvaluation, OpportunityEvaluation)


def test_recorder_refuses_a_complete_set_evaluation() -> None:
    result = _evaluate(_binary("0.40", "0.55"))
    assert result.has_opportunity is True  # a "real" edge — still rejected downstream
    with Recorder.open(session_id="cs-safety", opened_at=EVAL_TIME, label="test") as rec:
        with pytest.raises(RecorderError, match="OpportunityEvaluation"):
            rec.record_opportunity(result, recorded_at=EVAL_TIME)  # type: ignore[arg-type]
