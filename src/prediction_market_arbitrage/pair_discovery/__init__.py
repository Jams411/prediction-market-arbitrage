"""Deterministic, read-only candidate triage for manual contract verification.

Discovery output is deliberately separate from the verified-pair registry.  It
can prioritize records for a human reviewer, but it cannot approve a pair or
make one strategy-eligible.
"""

from .comparison import compare_contracts, discover_candidates
from .models import (
    CandidatePair,
    ComparisonClass,
    FieldComparison,
    SemanticContract,
)
from .profiles import from_kalshi_market, from_polymarket_us_market

__all__ = [
    "CandidatePair",
    "ComparisonClass",
    "FieldComparison",
    "SemanticContract",
    "compare_contracts",
    "discover_candidates",
    "from_kalshi_market",
    "from_polymarket_us_market",
]
