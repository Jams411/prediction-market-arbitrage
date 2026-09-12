"""Deterministic comparison and conservative verification-priority ranking."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .family_policy import family_exclusion
from .models import (
    CandidatePair,
    CoarseSignal,
    ComparisonClass,
    DiscoveryDiagnostics,
    FieldComparison,
    MatchingKeys,
    RejectedNearMiss,
    SemanticContract,
)

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
DEFAULT_MINIMUM_LEXICAL_SIGNAL = Decimal("0.20")


@dataclass(frozen=True, slots=True)
class _PreparedProfile:
    contract: SemanticContract
    tokens: frozenset[str]
    keys: MatchingKeys
    event: str | None
    participant: str | None
    category: str | None
    series_or_league: str | None


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
    minimum_lexical_signal: Decimal = DEFAULT_MINIMUM_LEXICAL_SIGNAL,
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
            if family_exclusion(kalshi, polymarket_us) is not None:
                continue
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


def diagnose_candidates(
    kalshi_contracts: Iterable[SemanticContract],
    polymarket_us_contracts: Iterable[SemanticContract],
    *,
    candidate_limit: int = 20,
    near_miss_limit: int = 20,
    minimum_lexical_signal: Decimal = DEFAULT_MINIMUM_LEXICAL_SIGNAL,
) -> DiscoveryDiagnostics:
    """Explain the unchanged lexical gate with bounded, streaming examples.

    The full cross-product is counted, but only ``candidate_limit`` passed rows
    and ``near_miss_limit`` rejected rows are retained.  No registry or strategy
    type is created.
    """
    if candidate_limit <= 0 or near_miss_limit <= 0:
        raise ValueError("candidate and near-miss limits must be positive")
    kalshi = tuple(_prepare(item) for item in kalshi_contracts)
    polymarket = tuple(_prepare(item) for item in polymarket_us_contracts)
    passed = 0
    rejected = 0
    family_counts = {"nfl": 0, "mlb": 0}
    passed_examples: list[CandidatePair] = []
    near_misses: list[RejectedNearMiss] = []

    for left in kalshi:
        for right in polymarket:
            exclusion = family_exclusion(left.contract, right.contract)
            if exclusion is not None:
                family_counts[exclusion.polymarket_league] += 1
                continue
            signal = _token_signal(left.tokens, right.tokens)
            if signal >= minimum_lexical_signal:
                passed += 1
                _retain_passed(
                    passed_examples,
                    compare_contracts(left.contract, right.contract),
                    candidate_limit,
                )
                continue
            rejected += 1
            rank = _near_miss_rank(left, right, signal)
            if len(near_misses) < near_miss_limit or rank < _near_miss_sort_key(
                near_misses[-1]
            ):
                _retain_near_miss(
                    near_misses,
                    _near_miss(left, right, signal, minimum_lexical_signal),
                    near_miss_limit,
                )

    considered = passed + rejected + sum(family_counts.values())
    return DiscoveryDiagnostics(
        considered=considered,
        nfl_family_excluded=family_counts["nfl"],
        mlb_family_excluded=family_counts["mlb"],
        passed=passed,
        rejected=rejected,
        threshold=minimum_lexical_signal,
        passed_candidates=tuple(passed_examples),
        near_misses=tuple(near_misses),
    )


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
    left_tokens = _contract_tokens(left)
    right_tokens = _contract_tokens(right)
    return _token_signal(left_tokens, right_tokens)


def _contract_tokens(contract: SemanticContract) -> frozenset[str]:
    return _tokens(
        " ".join(
            filter(
                None,
                (contract.title, contract.underlying_event, contract.participant_outcome),
            )
        )
    )


def _token_signal(left_tokens: frozenset[str], right_tokens: frozenset[str]) -> Decimal:
    union = left_tokens | right_tokens
    if not union:
        return Decimal(0)
    return Decimal(len(left_tokens & right_tokens)) / Decimal(len(union))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(word for word in _WORDS.findall(value.casefold()) if word not in _STOPWORDS)


def _normalize(value: str) -> str:
    return " ".join(_WORDS.findall(value.casefold()))


def _prepare(contract: SemanticContract) -> _PreparedProfile:
    tokens = _contract_tokens(contract)
    return _PreparedProfile(
        contract=contract,
        tokens=tokens,
        keys=MatchingKeys(all_tokens=tuple(sorted(tokens))),
        event=_optional_normalize(contract.underlying_event),
        participant=_optional_normalize(contract.participant_outcome),
        category=_optional_normalize(contract.category),
        series_or_league=_optional_normalize(contract.series_or_league),
    )


def _optional_normalize(value: str | None) -> str | None:
    return _normalize(value) if value is not None else None


def _coarse_match_count(left: _PreparedProfile, right: _PreparedProfile) -> int:
    pairs: tuple[tuple[object | None, object | None], ...] = (
        (left.event, right.event),
        (left.participant, right.participant),
        (left.category, right.category),
        (left.series_or_league, right.series_or_league),
        (left.contract.event_time_window, right.contract.event_time_window),
        (left.contract.threshold, right.contract.threshold),
    )
    return sum(a is not None and b is not None and a == b for a, b in pairs)


def _near_miss_rank(
    left: _PreparedProfile, right: _PreparedProfile, signal: Decimal
) -> tuple[int, Decimal, str, str]:
    return (
        -_coarse_match_count(left, right),
        -signal,
        left.contract.identifier,
        right.contract.identifier,
    )


def _near_miss_sort_key(item: RejectedNearMiss) -> tuple[int, Decimal, str, str]:
    matches = sum(
        signal.classification is ComparisonClass.MATCH for signal in item.coarse_signals
    )
    return (-matches, -item.lexical_signal, item.kalshi.identifier, item.polymarket_us.identifier)


def _retain_passed(items: list[CandidatePair], item: CandidatePair, limit: int) -> None:
    items.append(item)
    items.sort(
        key=lambda candidate: (
            -candidate.verification_priority,
            -candidate.lexical_signal,
            candidate.kalshi.identifier,
            candidate.polymarket_us.identifier,
        )
    )
    del items[limit:]


def _retain_near_miss(
    items: list[RejectedNearMiss], item: RejectedNearMiss, limit: int
) -> None:
    items.append(item)
    items.sort(key=_near_miss_sort_key)
    del items[limit:]


def _near_miss(
    left: _PreparedProfile,
    right: _PreparedProfile,
    signal: Decimal,
    threshold: Decimal,
) -> RejectedNearMiss:
    shared = left.tokens & right.tokens
    return RejectedNearMiss(
        kalshi=left.contract,
        polymarket_us=right.contract,
        lexical_signal=signal,
        kalshi_keys=left.keys,
        polymarket_us_keys=right.keys,
        shared_tokens=tuple(sorted(shared)),
        kalshi_unique_tokens=tuple(sorted(left.tokens - shared)),
        polymarket_us_unique_tokens=tuple(sorted(right.tokens - shared)),
        coarse_signals=(
            _coarse_signal(
                "underlying_event",
                left.contract.underlying_event,
                right.contract.underlying_event,
            ),
            _coarse_signal(
                "participant",
                left.contract.participant_outcome,
                right.contract.participant_outcome,
            ),
            _coarse_signal("category", left.contract.category, right.contract.category),
            _coarse_signal(
                "series_or_league",
                left.contract.series_or_league,
                right.contract.series_or_league,
            ),
            _coarse_signal(
                "event_date",
                left.contract.event_time_window,
                right.contract.event_time_window,
            ),
            _coarse_signal("threshold", left.contract.threshold, right.contract.threshold),
        ),
        missing_metadata_fields=_missing_metadata(left.contract, right.contract),
        rejection_reason=f"lexical signal {signal} is below unchanged threshold {threshold}",
    )


def _coarse_signal(field: str, left: object | None, right: object | None) -> CoarseSignal:
    if left is None or right is None:
        classification = ComparisonClass.UNKNOWN
    elif _coarse_value(left) == _coarse_value(right):
        classification = ComparisonClass.MATCH
    else:
        classification = ComparisonClass.MISMATCH
    return CoarseSignal(
        field=field,
        classification=classification,
        kalshi_value=str(left) if left is not None else None,
        polymarket_us_value=str(right) if right is not None else None,
    )


def _coarse_value(value: object) -> object:
    return _normalize(value) if isinstance(value, str) else value


def _missing_metadata(
    left: SemanticContract, right: SemanticContract
) -> tuple[str, ...]:
    fields = (
        "event_identifier",
        "category",
        "series_or_league",
        "underlying_event",
        "participant_outcome",
        "market_type",
        "measurement_unit",
        "event_time_window",
        "close_conditions",
        "resolution_source",
        "cancellation_postponement",
        "multiple_winner_treatment",
        "void_refund_fair_market",
        "settlement_backstop",
        "yes_no_mapping",
    )
    return tuple(
        f"{venue}.{field}"
        for venue, contract in (("kalshi", left), ("polymarket_us", right))
        for field in fields
        if getattr(contract, field) is None
    )
