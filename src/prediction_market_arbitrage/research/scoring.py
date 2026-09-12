"""Offline cost/liquidity scoring for advisory research signals."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from prediction_market_arbitrage.domain.validation import (
    DomainValidationError,
    as_decimal,
    require_non_empty,
)

from .models import ResearchEvaluation


class RejectionReason(StrEnum):
    NO_SIGNAL = "NO_SIGNAL"
    INSUFFICIENT_USABLE_SIZE = "INSUFFICIENT_USABLE_SIZE"
    COSTS_EXCEED_RAW_EDGE = "COSTS_EXCEED_RAW_EDGE"
    SAFETY_BUFFER_EXCEEDS_EDGE = "SAFETY_BUFFER_EXCEEDS_EDGE"


@dataclass(frozen=True, slots=True)
class ResearchScoringConfig:
    """Configurable research assumptions; no venue fee schedule is implied."""

    modeled_fee_per_unit: Decimal = Decimal("0")
    safety_buffer_per_unit: Decimal = Decimal("0")
    minimum_usable_size: Decimal = Decimal("0")
    cost_basis: str = "MODELED/ASSUMED"

    def __post_init__(self) -> None:
        for name in (
            "modeled_fee_per_unit",
            "safety_buffer_per_unit",
            "minimum_usable_size",
        ):
            value = as_decimal(getattr(self, name), field=name)
            if value < 0:
                raise DomainValidationError(f"{name} must be nonnegative")
        require_non_empty(self.cost_basis, field="cost_basis")


@dataclass(frozen=True, slots=True)
class ResearchScore:
    """A cost/liquidity-aware advisory result, never an execution opportunity."""

    raw_discrepancy: Decimal
    modeled_fees: Decimal
    usable_size: Decimal
    safety_buffer: Decimal
    net_research_edge: Decimal
    accepted: bool
    rejection_reason: RejectionReason | None
    cost_basis: str

    def __post_init__(self) -> None:
        for name in (
            "raw_discrepancy",
            "modeled_fees",
            "usable_size",
            "safety_buffer",
            "net_research_edge",
        ):
            as_decimal(getattr(self, name), field=name)
        if self.usable_size < 0:
            raise DomainValidationError("usable_size must be nonnegative")
        require_non_empty(self.cost_basis, field="cost_basis")
        if self.accepted != (self.rejection_reason is None):
            raise DomainValidationError("accepted and rejection_reason disagree")


def score_research_evaluation(
    evaluation: ResearchEvaluation,
    config: ResearchScoringConfig,
) -> ResearchScore:
    """Apply configurable costs and displayed top-level depth to one evaluation."""
    if evaluation.signal is None:
        return ResearchScore(
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            False,
            RejectionReason.NO_SIGNAL,
            config.cost_basis,
        )
    signal = evaluation.signal
    raw = signal.metric_value
    size = signal.top_level_quantity
    if size < config.minimum_usable_size:
        return ResearchScore(
            raw,
            config.modeled_fee_per_unit * size,
            size,
            config.safety_buffer_per_unit * size,
            Decimal("0"),
            False,
            RejectionReason.INSUFFICIENT_USABLE_SIZE,
            config.cost_basis,
        )
    fees = config.modeled_fee_per_unit * size
    buffer = config.safety_buffer_per_unit * size
    net = (raw - config.modeled_fee_per_unit - config.safety_buffer_per_unit) * size
    if net <= 0:
        reason = (
            RejectionReason.SAFETY_BUFFER_EXCEEDS_EDGE
            if raw <= config.safety_buffer_per_unit
            else RejectionReason.COSTS_EXCEED_RAW_EDGE
        )
        return ResearchScore(raw, fees, size, buffer, net, False, reason, config.cost_basis)
    return ResearchScore(raw, fees, size, buffer, net, True, None, config.cost_basis)


def rank_research_scores(scores: Iterable[ResearchScore]) -> tuple[ResearchScore, ...]:
    """Deterministically rank accepted and rejected scores by net edge."""
    return tuple(
        sorted(
            scores,
            key=lambda score: (score.net_research_edge, score.raw_discrepancy, score.usable_size),
            reverse=True,
        )
    )
