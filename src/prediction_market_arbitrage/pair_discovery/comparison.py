"""Deterministic comparison and conservative verification-priority ranking."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from .models import CandidatePair, ComparisonClass, FieldComparison, SemanticContract

_WORDS = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "be",
        "by",
        "for",
        "if",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "will",
        "win",
    }
)

_WEIGHTS: dict[str, int] = {
    "underlying_event_entity": 18,
    "binary_proposition": 14,
    "participant_outcome_mapping": 14,
    "threshold_value": 12,
    "threshold_inclusivity": 10,
    "measurement_unit": 8,
    "event_time_window": 8,
    "close_conditions": 3,
    "resolution_source": 6,
    "cancellation_postponement": 10,
    "multiple_winner_treatment": 6,
    "void_refund_fair_market": 10,
    "settlement_backstop_timing": 5,
    "yes_no_mapping_confidence": 8,
}
_MATERIAL_FIELDS = frozenset(
    {
        "underlying_event_entity",
        "binary_proposition",
        "participant_outcome_mapping",
        "threshold_value",
        "threshold_inclusivity",
        "measurement_unit",
        "event_time_window",
        "resolution_source",
        "cancellation_postponement",
        "multiple_winner_treatment",
        "void_refund_fair_market",
        "settlement_backstop_timing",
        "yes_no_mapping_confidence",
    }
)


def compare_contracts(kalshi: SemanticContract, polymarket_us: SemanticContract) -> CandidatePair:
    """Compare two profiles without making or implying an approval decision."""
    if kalshi.venue != "kalshi" or polymarket_us.venue != "polymarket_us":
        raise ValueError("compare_contracts expects Kalshi then Polymarket US")

    comparisons = (
        _text_comparison(
            "underlying_event_entity", kalshi.underlying_event, polymarket_us.underlying_event
        ),
        _text_comparison(
            "binary_proposition", kalshi.binary_proposition, polymarket_us.binary_proposition
        ),
        _text_comparison(
            "participant_outcome_mapping",
            kalshi.participant_outcome,
            polymarket_us.participant_outcome,
        ),
        _threshold_comparison(kalshi.threshold, polymarket_us.threshold),
        _scalar_comparison(
            "threshold_inclusivity",
            kalshi.threshold_inclusivity,
            polymarket_us.threshold_inclusivity,
        )
        if kalshi.threshold is not None or polymarket_us.threshold is not None
        else FieldComparison(
            "threshold_inclusivity",
            ComparisonClass.NOT_APPLICABLE,
            None,
            None,
            "no threshold detected",
        ),
        _text_comparison(
            "measurement_unit", kalshi.measurement_unit, polymarket_us.measurement_unit
        ),
        _datetime_comparison(
            "event_time_window", kalshi.event_time_window, polymarket_us.event_time_window
        ),
        _text_comparison(
            "close_conditions", kalshi.close_conditions, polymarket_us.close_conditions
        ),
        _text_comparison(
            "resolution_source", kalshi.resolution_source, polymarket_us.resolution_source
        ),
        _text_comparison(
            "cancellation_postponement",
            kalshi.cancellation_postponement,
            polymarket_us.cancellation_postponement,
        ),
        _text_comparison(
            "multiple_winner_treatment",
            kalshi.multiple_winner_treatment,
            polymarket_us.multiple_winner_treatment,
        ),
        _text_comparison(
            "void_refund_fair_market",
            kalshi.void_refund_fair_market,
            polymarket_us.void_refund_fair_market,
        ),
        _datetime_comparison(
            "settlement_backstop_timing",
            kalshi.settlement_backstop,
            polymarket_us.settlement_backstop,
        ),
        _text_comparison(
            "yes_no_mapping_confidence", kalshi.yes_no_mapping, polymarket_us.yes_no_mapping
        ),
    )
    signal = _lexical_signal(kalshi, polymarket_us)
    return CandidatePair(
        kalshi=kalshi,
        polymarket_us=polymarket_us,
        verification_priority=_priority(comparisons, signal),
        comparisons=comparisons,
        lexical_signal=signal,
    )


def discover_candidates(
    kalshi_contracts: Iterable[SemanticContract],
    polymarket_us_contracts: Iterable[SemanticContract],
    *,
    limit: int = 20,
    minimum_lexical_signal: Decimal = Decimal("0.20"),
) -> tuple[CandidatePair, ...]:
    """Return deterministically ranked triage candidates.

    Lexical overlap is only a cheap generation signal.  Semantic comparisons
    and material mismatches control priority, and every returned item remains
    explicitly ``UNVERIFIED``.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    candidates: list[CandidatePair] = []
    poly = tuple(polymarket_us_contracts)
    for kalshi in kalshi_contracts:
        for polymarket_us in poly:
            candidate = compare_contracts(kalshi, polymarket_us)
            if candidate.lexical_signal >= minimum_lexical_signal:
                candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            -item.verification_priority,
            -item.lexical_signal,
            item.kalshi.identifier,
            item.polymarket_us.identifier,
        )
    )
    return tuple(candidates[:limit])


def _text_comparison(
    field: str, left: str | None, right: str | None, *, not_applicable: bool = False
) -> FieldComparison:
    if not_applicable:
        return FieldComparison(field, ComparisonClass.NOT_APPLICABLE, None, None, "not applicable")
    if left is None or right is None:
        return FieldComparison(
            field,
            ComparisonClass.UNKNOWN,
            left,
            right,
            "one or both venue rule fields are unavailable",
        )
    if _normalize(left) == _normalize(right):
        return FieldComparison(field, ComparisonClass.MATCH, left, right, "normalized values match")
    return FieldComparison(
        field,
        ComparisonClass.MISMATCH,
        left,
        right,
        "normalized values differ; human review required",
    )


def _threshold_comparison(left: Decimal | None, right: Decimal | None) -> FieldComparison:
    if left is None and right is None:
        return FieldComparison(
            "threshold_value", ComparisonClass.NOT_APPLICABLE, None, None, "no threshold detected"
        )
    return _scalar_comparison("threshold_value", left, right)


def _datetime_comparison(
    field: str, left: datetime | None, right: datetime | None
) -> FieldComparison:
    return _scalar_comparison(field, left, right)


def _scalar_comparison(field: str, left: object | None, right: object | None) -> FieldComparison:
    left_text = str(left) if left is not None else None
    right_text = str(right) if right is not None else None
    if left is None or right is None:
        return FieldComparison(
            field,
            ComparisonClass.UNKNOWN,
            left_text,
            right_text,
            "one or both venue rule fields are unavailable",
        )
    classification = ComparisonClass.MATCH if left == right else ComparisonClass.MISMATCH
    reason = "values match exactly" if classification is ComparisonClass.MATCH else "values differ"
    return FieldComparison(field, classification, left_text, right_text, reason)


def _priority(comparisons: tuple[FieldComparison, ...], lexical_signal: Decimal) -> int:
    maximum = sum(
        _WEIGHTS[comparison.field]
        for comparison in comparisons
        if comparison.classification is not ComparisonClass.NOT_APPLICABLE
    )
    score = 0
    for comparison in comparisons:
        weight = _WEIGHTS[comparison.field]
        if comparison.classification is ComparisonClass.MATCH:
            score += weight
        elif comparison.classification is ComparisonClass.MISMATCH:
            score -= weight * (2 if comparison.field in _MATERIAL_FIELDS else 1)
    semantic = Decimal(max(0, score)) / Decimal(maximum)
    combined = semantic * Decimal(90) + lexical_signal * Decimal(10)
    return min(100, max(0, int(combined.quantize(Decimal("1")))))


def _lexical_signal(left: SemanticContract, right: SemanticContract) -> Decimal:
    left_tokens = _tokens(
        " ".join(filter(None, (left.title, left.underlying_event, left.participant_outcome)))
    )
    right_tokens = _tokens(
        " ".join(filter(None, (right.title, right.underlying_event, right.participant_outcome)))
    )
    union = left_tokens | right_tokens
    if not union:
        return Decimal(0)
    return Decimal(len(left_tokens & right_tokens)) / Decimal(len(union))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(word for word in _WORDS.findall(value.casefold()) if word not in _STOPWORDS)


def _normalize(value: str) -> str:
    return " ".join(_WORDS.findall(value.casefold()))
