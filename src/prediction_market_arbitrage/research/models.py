"""Advisory research values; never execution or registry approvals."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from prediction_market_arbitrage.domain import Contract, OrderBook
from prediction_market_arbitrage.domain.validation import (
    DomainValidationError,
    as_decimal,
    require_aware,
    require_non_empty,
    require_positive,
)


class SignalType(StrEnum):
    STRICT_ARBITRAGE = "STRICT_ARBITRAGE"
    RELATIVE_VALUE = "RELATIVE_VALUE"
    LOGICAL_INCONSISTENCY = "LOGICAL_INCONSISTENCY"
    FAIR_VALUE_DEVIATION = "FAIR_VALUE_DEVIATION"


class EvidenceStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    OBSERVED = "OBSERVED"
    TESTED = "TESTED"
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ThresholdRelationship:
    """Explicit same-event binding supplied by research, not inferred from tickers.

    A shared scalar uses strict greater-than predicates in percent units. Event
    membership/source identity are supplied evidence, not proven by OrderBook.
    """

    id: str
    version: str
    event_id: str
    lower_yes: Contract
    higher_yes: Contract
    lower_threshold: Decimal
    higher_threshold: Decimal
    underlying: str
    observation_window: str
    source: str
    evidence_refs: tuple[str, ...]
    ordinary_proof_status: EvidenceStatus
    settlement_limitations: tuple[str, ...]
    metadata_status: EvidenceStatus = EvidenceStatus.UNKNOWN
    unit: str = "percent"

    def __post_init__(self) -> None:
        for name in ("id", "version", "event_id", "underlying", "observation_window", "source"):
            require_non_empty(getattr(self, name), field=name)
        for name in ("lower_yes", "higher_yes"):
            contract = getattr(self, name)
            if not isinstance(contract, Contract) or contract.outcome != "YES":
                raise DomainValidationError(f"{name}: requires an exact YES Contract")
        if self.lower_yes.venue != self.higher_yes.venue:
            raise DomainValidationError("relationship: different venues")
        if self.lower_yes.market.id == self.higher_yes.market.id:
            raise DomainValidationError("relationship: thresholds require distinct markets")
        for name in ("lower_threshold", "higher_threshold"):
            as_decimal(getattr(self, name), field=name)
        if self.lower_threshold >= self.higher_threshold:
            raise DomainValidationError("relationship: thresholds must strictly increase")
        _texts(self.evidence_refs, "evidence_refs")
        _texts(self.settlement_limitations, "settlement_limitations")
        if not isinstance(self.ordinary_proof_status, EvidenceStatus):
            raise DomainValidationError("ordinary_proof_status: requires EvidenceStatus")
        if not isinstance(self.metadata_status, EvidenceStatus):
            raise DomainValidationError("metadata_status: requires EvidenceStatus")
        require_non_empty(self.unit, field="unit")


def _texts(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise DomainValidationError(f"{name}: requires nonempty immutable evidence")
    for value in values:
        require_non_empty(value, field=name)


@dataclass(frozen=True, slots=True)
class ResearchSignal:
    """Read-only finding, deliberately unrelated to OpportunityEvaluation.

    STRICT_ARBITRAGE is reserved for a future gated presentation adapter; this
    research constructor cannot confer that label on conditional evidence.
    """

    detector_id: str
    detector_version: str
    kind: SignalType
    relationship: ThresholdRelationship
    evaluation_time: datetime
    lower_book: OrderBook
    higher_book: OrderBook
    input_status: EvidenceStatus
    metric_name: str
    metric_value: Decimal
    metric_unit: str
    top_level_quantity: Decimal
    limitations: tuple[str, ...]
    settlement_confidence: str = field(default="UNKNOWN", init=False)
    value_confidence: str = field(default="NOT_ASSESSED", init=False)
    fees: str = field(default="NOT_EVALUATED", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SignalType) or self.kind == SignalType.STRICT_ARBITRAGE:
            raise DomainValidationError("kind: research cannot certify strict arbitrage")
        if not isinstance(self.input_status, EvidenceStatus):
            raise DomainValidationError("input_status: requires EvidenceStatus")
        for name in ("detector_id", "detector_version", "metric_name", "metric_unit"):
            require_non_empty(getattr(self, name), field=name)
        require_aware(self.evaluation_time, field="evaluation_time")
        as_decimal(self.metric_value, field="metric_value")
        require_positive(as_decimal(self.top_level_quantity, field="quantity"), field="quantity")
        if (
            self.lower_book.contract != self.relationship.lower_yes
            or self.higher_book.contract != self.relationship.higher_yes
        ):
            raise DomainValidationError("signal: books do not match relationship")
        _texts(self.limitations, "limitations")
        if not set(self.relationship.settlement_limitations).issubset(self.limitations):
            raise DomainValidationError("signal: settlement limitations must be preserved")


class Diagnostic(StrEnum):
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    ORDINARY_PROOF_UNAVAILABLE = "ORDINARY_PROOF_UNAVAILABLE"
    MISSING_LEVEL = "MISSING_LEVEL"
    FUTURE_BOOK = "FUTURE_BOOK"
    STALE_BOOK = "STALE_BOOK"
    EXCESSIVE_SKEW = "EXCESSIVE_SKEW"
    NO_DISCREPANCY = "NO_DISCREPANCY"


@dataclass(frozen=True, slots=True)
class ResearchEvaluation:
    signal: ResearchSignal | None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.diagnostics, tuple):
            raise DomainValidationError("diagnostics: requires a tuple")
        if any(not isinstance(item, Diagnostic) for item in self.diagnostics):
            raise DomainValidationError("diagnostics: invalid reason")
        if (self.signal is None) == (not self.diagnostics):
            raise DomainValidationError("evaluation: requires either signal or diagnostics")
