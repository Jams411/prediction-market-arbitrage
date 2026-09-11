"""Deterministic, read-only candidate triage for manual contract verification.

Discovery output is deliberately separate from the verified-pair registry.  It
can prioritize records for a human reviewer, but it cannot approve a pair or
make one strategy-eligible.
"""

from .comparison import compare_contracts, diagnose_candidates, discover_candidates
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
from .profiles import from_kalshi_market, from_polymarket_us_market

__all__ = [
    "CandidatePair",
    "CoarseSignal",
    "ComparisonClass",
    "DiscoveryDiagnostics",
    "FieldComparison",
    "MatchingKeys",
    "RejectedNearMiss",
    "SemanticContract",
    "compare_contracts",
    "diagnose_candidates",
    "discover_candidates",
    "from_kalshi_market",
    "from_polymarket_us_market",
]
