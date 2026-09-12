"""Synthetic offline tests for advisory research scoring."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.domain import Contract, Market, OrderBook, PriceLevel, Venue
from prediction_market_arbitrage.research import (
    EvidenceStatus,
    RejectionReason,
    ResearchEvaluation,
    ResearchScoringConfig,
    ThresholdRelationship,
    evaluate_threshold_ordering,
    rank_research_scores,
    score_research_evaluation,
)

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def evaluation() -> ResearchEvaluation:
    venue = Venue("synthetic", "Synthetic")
    lower = Contract(Market(venue, "lower", "CPI lower"), "lower:YES", "YES")
    higher = Contract(Market(venue, "higher", "CPI higher"), "higher:YES", "YES")
    relation = ThresholdRelationship(
        "r", "1", "event", lower, higher, D(".2"), D(".3"), "CPI",
        "month", "BLS", ("synthetic://terms",), EvidenceStatus.TESTED,
        ("settlement unresolved",),
    )
    return evaluate_threshold_ordering(
        relation,
        OrderBook(lower, (PriceLevel(D(".4"), D("10")),), (PriceLevel(D(".5"), D("10")),), NOW),
        OrderBook(higher, (PriceLevel(D(".7"), D("6")),), (PriceLevel(D(".8"), D("10")),), NOW),
        evaluation_time=NOW,
        max_age=timedelta(minutes=5),
        max_skew=timedelta(minutes=1),
        input_status=EvidenceStatus.TESTED,
    )


def test_negative_net_edge_after_modeled_costs() -> None:
    score = score_research_evaluation(
        evaluation(), ResearchScoringConfig(modeled_fee_per_unit=D(".25"))
    )
    assert score.raw_discrepancy == D(".2")
    assert score.net_research_edge == D("-0.3")
    assert score.rejection_reason is RejectionReason.COSTS_EXCEED_RAW_EDGE


def test_positive_net_edge_is_advisory() -> None:
    score = score_research_evaluation(
        evaluation(),
        ResearchScoringConfig(modeled_fee_per_unit=D(".01"), safety_buffer_per_unit=D(".02")),
    )
    assert score.accepted
    assert score.net_research_edge == D("1.02")
    assert score.cost_basis == "MODELED/ASSUMED"


def test_insufficient_size_and_buffer_rejection() -> None:
    small = score_research_evaluation(
        evaluation(), ResearchScoringConfig(minimum_usable_size=D("7"))
    )
    assert small.rejection_reason is RejectionReason.INSUFFICIENT_USABLE_SIZE
    buffered = score_research_evaluation(
        evaluation(), ResearchScoringConfig(safety_buffer_per_unit=D(".21"))
    )
    assert buffered.rejection_reason is RejectionReason.SAFETY_BUFFER_EXCEEDS_EDGE


def test_ranking_is_deterministic_by_net_edge() -> None:
    low = score_research_evaluation(
        evaluation(), ResearchScoringConfig(modeled_fee_per_unit=D(".1"))
    )
    high = score_research_evaluation(
        evaluation(), ResearchScoringConfig(modeled_fee_per_unit=D(".01"))
    )
    assert rank_research_scores((low, high)) == (high, low)
