"""Pure ordinary-state threshold discrepancy detection; no I/O or execution."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.domain.validation import DomainValidationError, require_aware

from .models import (
    Diagnostic,
    EvidenceStatus,
    ResearchEvaluation,
    ResearchSignal,
    SignalType,
    ThresholdRelationship,
)


def evaluate_threshold_ordering(
    relationship: ThresholdRelationship,
    lower_yes_book: OrderBook,
    higher_yes_book: OrderBook,
    *,
    evaluation_time: datetime,
    max_age: timedelta,
    max_skew: timedelta,
    input_status: EvidenceStatus = EvidenceStatus.UNKNOWN,
) -> ResearchEvaluation:
    """Flag higher YES bid > lower YES ask under an explicit shared-scalar relation.

    Book membership must match the supplied relationship exactly. The relationship
    is evidence supplied by the caller; no event membership is inferred from IDs.
    Age/skew limits are research inputs, not modifications to production risk.
    """
    require_aware(evaluation_time, field="evaluation_time")
    if max_age < timedelta(0) or max_skew < timedelta(0):
        raise DomainValidationError("research time limits must be nonnegative")
    if not isinstance(input_status, EvidenceStatus):
        raise DomainValidationError("input_status: requires EvidenceStatus")
    if (
        lower_yes_book.contract != relationship.lower_yes
        or higher_yes_book.contract != relationship.higher_yes
    ):
        return ResearchEvaluation(None, (Diagnostic.IDENTITY_MISMATCH,))
    if relationship.ordinary_proof_status not in (EvidenceStatus.TESTED, EvidenceStatus.VERIFIED):
        return ResearchEvaluation(None, (Diagnostic.ORDINARY_PROOF_UNAVAILABLE,))
    times = (lower_yes_book.timestamp, higher_yes_book.timestamp)
    if max(times) > evaluation_time:
        return ResearchEvaluation(None, (Diagnostic.FUTURE_BOOK,))
    if evaluation_time - min(times) > max_age:
        return ResearchEvaluation(None, (Diagnostic.STALE_BOOK,))
    if max(times) - min(times) > max_skew:
        return ResearchEvaluation(None, (Diagnostic.EXCESSIVE_SKEW,))
    ask, bid = lower_yes_book.best_ask, higher_yes_book.best_bid
    if ask is None or bid is None:
        return ResearchEvaluation(None, (Diagnostic.MISSING_LEVEL,))
    gap = bid.price - ask.price
    if gap <= 0:
        return ResearchEvaluation(None, (Diagnostic.NO_DISCREPANCY,))
    return ResearchEvaluation(
        ResearchSignal(
            detector_id="cpi-threshold-ordering",
            detector_version="1",
            kind=SignalType.LOGICAL_INCONSISTENCY,
            relationship=relationship,
            evaluation_time=evaluation_time,
            lower_book=lower_yes_book,
            higher_book=higher_yes_book,
            input_status=input_status,
            metric_name="higher_bid_minus_lower_ask",
            metric_value=gap,
            metric_unit="USD_per_contract",
            top_level_quantity=min(ask.quantity, bid.quantity),
            limitations=relationship.settlement_limitations
            + (
                "Ordinary shared-scalar implication only; not guaranteed arbitrage.",
                "Fees not evaluated; displayed size does not guarantee non-atomic fills.",
                "Input provenance is caller-supplied; event membership is not inferred.",
            ),
        )
    )


def rank_threshold_signals(signals: Iterable[ResearchSignal]) -> tuple[ResearchSignal, ...]:
    """Rank only this detector's findings; no cross-metric confidence score."""
    items = tuple(signals)
    for signal in items:
        if (
            signal.detector_id != "cpi-threshold-ordering"
            or signal.detector_version != "1"
            or signal.kind != SignalType.LOGICAL_INCONSISTENCY
            or signal.metric_name != "higher_bid_minus_lower_ask"
            or signal.metric_unit != "USD_per_contract"
            or signal.metric_value <= 0
        ):
            raise DomainValidationError("ranking requires threshold discrepancy signals")
    # Stable passes preserve datetime precision without float timestamps.
    items = tuple(sorted(items, key=lambda s: (s.relationship.id, s.relationship.version)))
    items = tuple(
        sorted(
            items, key=lambda s: min(s.lower_book.timestamp, s.higher_book.timestamp), reverse=True
        )
    )
    return tuple(sorted(items, key=lambda s: (s.metric_value, s.top_level_quantity), reverse=True))
