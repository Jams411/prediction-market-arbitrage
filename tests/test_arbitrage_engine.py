"""Deterministic tests for the M1.5 arbitrage engine. Exact Decimal arithmetic."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from arbitrage_support import (
    EVAL_TIME,
    KALSHI_MARKET,
    POLY_MARKET,
    TS,
    kalshi_book,
    make_record,
    polymarket_book,
)

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    ArbitrageError,
    EngineConfig,
    FixedPerUnitFeeModel,
    OpportunityEvaluation,
)
from prediction_market_arbitrage.domain import Opportunity
from prediction_market_arbitrage.registry import (
    MarketPairRecord,
    MarketPairRegistry,
    OutcomeRelation,
    PairStatus,
)

D = Decimal
DEEP = "100"  # a large level quantity so top-of-book price is the only one used


def _evaluate(
    *,
    a_asks: list[tuple[str, str]],
    b_asks: list[tuple[str, str]],
    quantity: str | None = None,
    config: EngineConfig | None = None,
    record: MarketPairRecord | None = None,
    a_ts: datetime = TS,
    b_ts: datetime = TS,
    eval_time: datetime = EVAL_TIME,
) -> OpportunityEvaluation:
    engine = ArbitrageEngine(config) if config is not None else ArbitrageEngine()
    rec = record if record is not None else make_record()
    return engine.evaluate(
        rec,
        kalshi_book(a_asks, timestamp=a_ts),
        polymarket_book(b_asks, timestamp=b_ts),
        evaluation_time=eval_time,
        requested_quantity=D(quantity) if quantity is not None else None,
    )


# --------------------------------------------------------------------------- #
# Baseline economics — exact, results known beforehand
# --------------------------------------------------------------------------- #


def test_baseline_gross_and_net_edge() -> None:
    result = _evaluate(a_asks=[("0.45", DEEP)], b_asks=[("0.52", DEEP)], quantity="1")

    assert result.executable_quantity == D("1")
    assert result.gross_total_cost == D("0.97")
    assert result.gross_edge == D("0.03")
    assert result.fees == D("0")
    assert result.execution_buffer == D("0")
    assert result.net_total_cost == D("0.97")
    assert result.net_edge == D("0.03")
    assert result.has_opportunity is True
    assert result.expected_total_profit == D("0.03")
    assert result.net_edge_per_unit == D("0.03")
    # audit trail
    assert result.pair_id == "pair-test"
    assert result.leg_a.contract_id == f"{KALSHI_MARKET}:YES"
    assert result.leg_b.contract_id == f"{POLY_MARKET}:SHORT"
    assert result.leg_a.acquisition_cost == D("0.45")
    assert result.leg_b.acquisition_cost == D("0.52")
    assert result.leg_a.book_timestamp == TS
    assert result.evaluation_time == EVAL_TIME
    assert result.expected_total_profit == result.net_edge_per_unit * result.executable_quantity


def test_fees_reduce_edge() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        config=EngineConfig(fee_model=FixedPerUnitFeeModel(D("0.01"))),
    )
    assert result.fees == D("0.02")  # 0.01 per unit, one unit per leg
    assert result.net_edge == D("0.01")
    assert result.has_opportunity is True


def test_buffer_reduces_edge() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        config=EngineConfig(execution_buffer_per_unit=D("0.01")),
    )
    assert result.execution_buffer == D("0.01")
    assert result.net_edge == D("0.02")
    assert result.has_opportunity is True


def test_fees_plus_buffer_eliminate_opportunity() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        config=EngineConfig(
            fee_model=FixedPerUnitFeeModel(D("0.01")),
            execution_buffer_per_unit=D("0.01"),
        ),
    )
    assert result.fees == D("0.02")
    assert result.execution_buffer == D("0.01")
    assert result.net_edge == D("0.00")
    assert result.has_opportunity is False
    assert "break-even" in result.rejection_reason


def test_exact_break_even_is_not_an_opportunity() -> None:
    result = _evaluate(a_asks=[("0.45", DEEP)], b_asks=[("0.55", DEEP)], quantity="1")
    assert result.gross_total_cost == D("1.00")
    assert result.net_edge == D("0.00")
    assert result.has_opportunity is False


def test_negative_edge_is_not_an_opportunity() -> None:
    result = _evaluate(a_asks=[("0.50", DEEP)], b_asks=[("0.55", DEEP)], quantity="1")
    assert result.net_edge == D("-0.05")
    assert result.has_opportunity is False
    assert "negative" in result.rejection_reason


# --------------------------------------------------------------------------- #
# Depth walking
# --------------------------------------------------------------------------- #


def test_multi_level_depth_weighted_cost() -> None:
    # Venue A asks: 0.40 x 5, 0.42 x 10   Venue B asks: 0.50 x 8, 0.51 x 10
    result = _evaluate(
        a_asks=[("0.40", "5"), ("0.42", "10")],
        b_asks=[("0.50", "8"), ("0.51", "10")],
        quantity="8",
    )
    # A: 5*0.40 + 3*0.42 = 2.00 + 1.26 = 3.26 ; B: 8*0.50 = 4.00
    assert result.leg_a.acquisition_cost == D("3.26")
    assert result.leg_b.acquisition_cost == D("4.00")
    assert result.gross_total_cost == D("7.26")
    assert result.gross_edge == D("0.74")  # 8 - 7.26
    assert result.net_edge == D("0.74")
    assert result.has_opportunity is True
    assert [(f.price, f.quantity) for f in result.leg_a.fills] == [
        (D("0.40"), D("5")),
        (D("0.42"), D("3")),
    ]


def test_top_of_book_only_when_quantity_fits_first_level() -> None:
    result = _evaluate(
        a_asks=[("0.40", "5"), ("0.42", "10")],
        b_asks=[("0.50", "8")],
        quantity="4",
    )
    assert result.leg_a.acquisition_cost == D("1.60")  # 4 * 0.40, first level only
    assert len(result.leg_a.fills) == 1


def test_asymmetric_available_depth_caps_size() -> None:
    result = _evaluate(
        a_asks=[("0.40", "5")],  # only 5 available on leg A
        b_asks=[("0.50", "100")],
        quantity="20",
    )
    assert result.executable_quantity == D("5")
    assert result.depth_capped is True
    assert result.has_opportunity is True  # 5 - (5*0.40 + 5*0.50) = 5 - 4.50 = 0.50


def test_require_full_fill_rejects_when_depth_short() -> None:
    result = _evaluate(
        a_asks=[("0.40", "5")],
        b_asks=[("0.50", "100")],
        quantity="20",
        config=EngineConfig(require_full_fill=True),
    )
    assert result.has_opportunity is False
    assert "insufficient depth" in result.rejection_reason


def test_quantity_cap_limits_size() -> None:
    result = _evaluate(
        a_asks=[("0.45", "100")],
        b_asks=[("0.52", "100")],
        config=EngineConfig(max_quantity=D("3")),
    )
    assert result.executable_quantity == D("3")
    assert result.gross_total_cost == D("2.91")  # 3 * 0.97
    assert result.net_edge == D("0.09")


def test_empty_ask_side_is_not_an_opportunity() -> None:
    engine = ArbitrageEngine()
    result = engine.evaluate(
        make_record(),
        kalshi_book([]),
        polymarket_book([("0.50", "10")]),
        evaluation_time=EVAL_TIME,
    )
    assert result.has_opportunity is False
    assert "empty ask side" in result.rejection_reason


# --------------------------------------------------------------------------- #
# Decimal discipline
# --------------------------------------------------------------------------- #


def test_decimal_precision_is_preserved() -> None:
    result = _evaluate(a_asks=[("0.333", DEEP)], b_asks=[("0.333", DEEP)], quantity="1")
    assert result.gross_total_cost == D("0.666")
    assert result.net_edge == D("0.334")
    assert str(result.net_edge) == "0.334"
    assert isinstance(result.net_edge, Decimal)
    assert isinstance(result.leg_a.acquisition_cost, Decimal)


def test_float_config_inputs_are_rejected() -> None:
    with pytest.raises(ArbitrageError):
        EngineConfig(execution_buffer_per_unit=0.01)  # type: ignore[arg-type]
    with pytest.raises(ArbitrageError):
        FixedPerUnitFeeModel(0.01)  # type: ignore[arg-type]
    with pytest.raises(ArbitrageError):
        EngineConfig(max_quantity=5.0)  # type: ignore[arg-type]


def test_float_requested_quantity_is_rejected() -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError):
        engine.evaluate(
            make_record(),
            kalshi_book([("0.45", DEEP)]),
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
            requested_quantity=1.5,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# Registry eligibility enforcement
# --------------------------------------------------------------------------- #


def test_verified_pair_can_be_evaluated() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        record=make_record(status=PairStatus.VERIFIED),
    )
    assert result.has_opportunity is True


@pytest.mark.parametrize(
    "status",
    [
        PairStatus.DRAFT,
        PairStatus.REVIEW_REQUIRED,
        PairStatus.REJECTED,
        PairStatus.SUSPENDED,
    ],
)
def test_non_verified_pair_is_rejected(status: PairStatus) -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError, match="only VERIFIED"):
        engine.evaluate(
            make_record(status=status),
            kalshi_book([("0.45", DEEP)]),
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
        )


def test_evaluate_from_registry_requires_eligible_pair() -> None:
    engine = ArbitrageEngine()
    draft = make_record(pair_id="p-draft", status=PairStatus.DRAFT)
    registry = MarketPairRegistry([draft])
    with pytest.raises(ArbitrageError, match="only VERIFIED"):
        engine.evaluate_from_registry(
            registry,
            "p-draft",
            kalshi_book([("0.45", DEEP)]),
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
        )


def test_evaluate_from_registry_rejects_unknown_pair_id() -> None:
    engine = ArbitrageEngine()
    registry = MarketPairRegistry([make_record(pair_id="p-known")])
    with pytest.raises(ArbitrageError, match="not in the registry"):
        engine.evaluate_from_registry(
            registry,
            "p-unknown",
            kalshi_book([("0.45", DEEP)]),
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
        )


def test_evaluate_from_registry_happy_path() -> None:
    engine = ArbitrageEngine()
    registry = MarketPairRegistry([make_record(pair_id="p-ok", status=PairStatus.VERIFIED)])
    result = engine.evaluate_from_registry(
        registry,
        "p-ok",
        kalshi_book([("0.45", DEEP)]),
        polymarket_book([("0.52", DEEP)]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("1"),
    )
    assert result.has_opportunity is True


# --------------------------------------------------------------------------- #
# Wrong book / wrong contract for the pair
# --------------------------------------------------------------------------- #


def test_wrong_contract_id_is_rejected() -> None:
    engine = ArbitrageEngine()
    record = make_record(kalshi_outcome="YES")
    with pytest.raises(ArbitrageError, match="does not match pair leg"):
        engine.evaluate(
            record,
            kalshi_book([("0.45", DEEP)], outcome="NO"),  # contract id kalshi-test-market:NO
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
        )


def test_swapped_books_are_rejected() -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError, match="does not match pair leg"):
        engine.evaluate(
            make_record(),
            polymarket_book([("0.45", DEEP)]),  # passed as the kalshi_book arg
            kalshi_book([("0.52", DEEP)]),
            evaluation_time=EVAL_TIME,
        )


def test_join_is_on_contract_id_not_contract_outcome() -> None:
    # Polymarket adapter sets contract.outcome to the side description ("No"),
    # while the contract id suffix is "SHORT". The engine joins on the id.
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
    )
    assert result.has_opportunity is True  # sanity: default books already do this
    engine = ArbitrageEngine()
    result2 = engine.evaluate(
        make_record(),
        kalshi_book([("0.45", DEEP)]),
        polymarket_book([("0.52", DEEP)], contract_outcome="No"),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("1"),
    )
    assert result2.has_opportunity is True


# --------------------------------------------------------------------------- #
# Relation handling
# --------------------------------------------------------------------------- #


def test_identical_relation_is_not_evaluated_in_m15() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        record=make_record(relation=OutcomeRelation.IDENTICAL),
    )
    assert result.has_opportunity is False
    assert "IDENTICAL" in result.rejection_reason


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #


def test_stale_book_rejected_by_max_age() -> None:
    old = EVAL_TIME - timedelta(minutes=10)
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        a_ts=old,
        config=EngineConfig(max_book_age=timedelta(minutes=5)),
    )
    assert result.has_opportunity is False
    assert "stale" in result.rejection_reason


def test_excessive_cross_book_skew_rejected() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        a_ts=TS,
        b_ts=TS + timedelta(seconds=90),
        config=EngineConfig(max_cross_book_skew=timedelta(seconds=30)),
    )
    assert result.has_opportunity is False
    assert "skew" in result.rejection_reason


def test_book_timestamp_after_evaluation_time_rejected() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        a_ts=EVAL_TIME + timedelta(seconds=5),
        config=EngineConfig(max_book_age=timedelta(minutes=5)),
    )
    assert result.has_opportunity is False
    assert "after evaluation_time" in result.rejection_reason


def test_fresh_books_within_limits_produce_opportunity() -> None:
    result = _evaluate(
        a_asks=[("0.45", DEEP)],
        b_asks=[("0.52", DEEP)],
        quantity="1",
        a_ts=EVAL_TIME - timedelta(seconds=10),
        b_ts=EVAL_TIME - timedelta(seconds=20),
        config=EngineConfig(
            max_book_age=timedelta(minutes=1),
            max_cross_book_skew=timedelta(seconds=30),
        ),
    )
    assert result.has_opportunity is True


def test_naive_evaluation_time_is_rejected() -> None:
    engine = ArbitrageEngine()
    with pytest.raises(ArbitrageError, match="timezone-aware"):
        engine.evaluate(
            make_record(),
            kalshi_book([("0.45", DEEP)]),
            polymarket_book([("0.52", DEEP)]),
            evaluation_time=datetime(2026, 1, 2, 0, 1),  # noqa: DTZ001 - intentional
        )


# --------------------------------------------------------------------------- #
# Opportunity container
# --------------------------------------------------------------------------- #


def test_to_opportunity_from_positive_evaluation() -> None:
    result = _evaluate(a_asks=[("0.45", DEEP)], b_asks=[("0.52", DEEP)], quantity="1")
    opportunity = result.to_opportunity()
    assert isinstance(opportunity, Opportunity)
    assert opportunity.pair.id == "pair-test"
    assert opportunity.quantity == D("1")
    assert opportunity.edge == D("0.03")
    assert opportunity.timestamp == EVAL_TIME
    assert opportunity.pair.left.id == f"{KALSHI_MARKET}:YES"
    assert opportunity.pair.right.id == f"{POLY_MARKET}:SHORT"


def test_to_opportunity_rejected_when_no_opportunity() -> None:
    result = _evaluate(a_asks=[("0.50", DEEP)], b_asks=[("0.55", DEEP)], quantity="1")
    with pytest.raises(ArbitrageError, match="no opportunity"):
        result.to_opportunity()
