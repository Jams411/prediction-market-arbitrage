"""Types for the manual verified market-pair registry (Milestone M1.4).

The registry declares which venue contracts a human has reviewed and decided may
be compared by later arbitrage code. It stores and enforces human decisions — it
performs **no** matching itself (no title strings, no fuzzy similarity, no LLM;
see ``docs/DECISIONS.md`` D-006, D-011 and ``docs/MARKET_PAIRING.md``).

Nothing here computes arbitrage, prices, fees, or execution eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RegistryError(ValueError):
    """Raised when the registry file or one of its records is malformed/invalid.

    The loader raises this for *any* bad record and never returns a partially
    loaded registry — the registry fails closed.
    """


class PairStatus(StrEnum):
    """Lifecycle of a reviewed pair. Only ``VERIFIED`` is comparable downstream."""

    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class OutcomeRelation(StrEnum):
    """How the two legs' named outcomes relate economically.

    - ``IDENTICAL``: the Kalshi leg's named outcome pays the same as the
      Polymarket US leg's named outcome (same real-world side).
    - ``COMPLEMENTARY``: the two named outcomes are opposite sides of the same
      proposition (together they cover both states); this is the pairing a
      cross-venue YES/NO arbitrage would use.

    The mapping is a stored human decision — not inferred.
    """

    IDENTICAL = "IDENTICAL"
    COMPLEMENTARY = "COMPLEMENTARY"


#: Statuses whose pairs the registry's ``eligible()`` API will return. Only
#: VERIFIED pairs may reach later strategy code.
ELIGIBLE_STATUSES: frozenset[PairStatus] = frozenset({PairStatus.VERIFIED})

#: The human-review checklist. Every key must be present and ``true`` for a
#: record to be accepted as ``VERIFIED``. These are judgements a person makes
#: from the venues' primary rules — the registry only records and enforces them.
REQUIRED_CHECKLIST_KEYS: tuple[str, ...] = (
    "same_underlying_event",
    "same_cutoff_or_observation_time",
    "same_timezone",
    "same_settlement_authority",
    "same_measurement_definition",
    "same_threshold_inclusivity",
    "same_cancellation_void_rules",
    "same_outcome_direction",
    "same_event_scope",
    "wording_differences_reviewed",
    "venue_settlement_asymmetry_reviewed",
)


@dataclass(frozen=True, slots=True)
class VenueLeg:
    """One side of a pair: a specific named outcome on one venue."""

    venue: str
    market_id: str
    outcome: str
    sources: tuple[str, ...]

    def identity(self) -> tuple[str, str, str]:
        """The ``(venue, market_id, outcome)`` triple used for conflict checks."""
        return (self.venue, self.market_id, self.outcome)


@dataclass(frozen=True, slots=True)
class MarketPairRecord:
    """One human-reviewed cross-venue pairing record.

    Construction does light structural checks only; full validation (VERIFIED
    completeness, cross-record conflicts, fail-closed status handling) lives in
    :mod:`.loader`, which is the only supported way to build these.
    """

    pair_id: str
    proposition: str
    status: PairStatus
    relation: OutcomeRelation
    kalshi: VenueLeg
    polymarket_us: VenueLeg
    settlement_notes: str
    known_differences: tuple[str, ...]
    known_differences_reviewed: bool
    checklist: tuple[tuple[str, bool], ...]
    reviewer: str
    verified_at: datetime | None
    live_use_eligible: bool
    blocking_reason: str
    notes: str

    def __post_init__(self) -> None:
        if not self.pair_id or not self.pair_id.strip():
            raise RegistryError("MarketPairRecord.pair_id: must be a non-empty string")
        if not isinstance(self.status, PairStatus):
            raise RegistryError(f"{self.pair_id}: status must be a PairStatus")
        if not isinstance(self.relation, OutcomeRelation):
            raise RegistryError(f"{self.pair_id}: relation must be an OutcomeRelation")

    def checklist_map(self) -> dict[str, bool]:
        return dict(self.checklist)

    @property
    def is_eligible(self) -> bool:
        """True only for VERIFIED pairs. Not a live-trading approval."""
        return self.status in ELIGIBLE_STATUSES
