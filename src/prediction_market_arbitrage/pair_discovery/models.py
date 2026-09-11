"""Models for unverified contract-equivalence discovery output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ComparisonClass(StrEnum):
    """Conservative field-level comparison result."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class SemanticContract:
    """Small, auditable semantic profile derived from public market metadata.

    Missing venue fields remain ``None``.  The discovery layer never fills a
    missing rule with a guess.
    """

    venue: str
    identifier: str
    title: str
    rule_sources: tuple[str, ...] = ()
    underlying_event: str | None = None
    binary_proposition: str | None = None
    participant_outcome: str | None = None
    threshold: Decimal | None = None
    threshold_inclusivity: str | None = None
    measurement_unit: str | None = None
    event_time_window: datetime | None = None
    close_conditions: str | None = None
    resolution_source: str | None = None
    cancellation_postponement: str | None = None
    multiple_winner_treatment: str | None = None
    void_refund_fair_market: str | None = None
    settlement_backstop: datetime | None = None
    yes_no_mapping: str | None = None

    def __post_init__(self) -> None:
        if self.venue not in {"kalshi", "polymarket_us"}:
            raise ValueError("venue must be 'kalshi' or 'polymarket_us'")
        if not self.identifier.strip() or not self.title.strip():
            raise ValueError("identifier and title must be non-empty")
        for name in ("event_time_window", "settlement_backstop"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FieldComparison:
    """One inspectable comparison; values are compact, never raw responses."""

    field: str
    classification: ComparisonClass
    kalshi_value: str | None
    polymarket_us_value: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """Ranked triage candidate.  This is not a registry record."""

    kalshi: SemanticContract
    polymarket_us: SemanticContract
    verification_priority: int
    comparisons: tuple[FieldComparison, ...]
    lexical_signal: Decimal
    status: str = "UNVERIFIED"
    warning: str = "UNVERIFIED — human/primary-source verification required"

    def __post_init__(self) -> None:
        if self.kalshi.venue != "kalshi" or self.polymarket_us.venue != "polymarket_us":
            raise ValueError("candidate legs must be Kalshi then Polymarket US")
        if self.status != "UNVERIFIED":
            raise ValueError("discovery candidates must remain UNVERIFIED")
        if not 0 <= self.verification_priority <= 100:
            raise ValueError("verification_priority must be between 0 and 100")
