"""Three evidence-backed exclusions for ordinary discovery, not registry decisions."""

from dataclasses import dataclass

from .models import SemanticContract

POLICY_ID = "sports-family-equivalence-v2"
EVIDENCE_REFERENCE = (
    "docs/evidence/contract-discovery/"
    "sports-contract-family-equivalence-audit-2026-09-11T220824Z.json"
)

MLB_TOTALS_EVIDENCE_REFERENCE = (
    "docs/evidence/contract-discovery/"
    "mlb-full-game-totals-family-audit-2026-09-12T020603Z.json"
)


@dataclass(frozen=True, slots=True)
class FamilyExclusion:
    kalshi_series: str
    polymarket_league: str
    sports_market_type: str
    policy_id: str = POLICY_ID
    scope: str = "STRICT_RISKLESS_CROSS_VENUE_EQUIVALENCE"
    classification: str = "SYSTEMATICALLY_INCOMPATIBLE"
    market_type: str = "moneyline"
    sports_market_type_v2: str = "SPORTS_MARKET_TYPE_MONEYLINE"
    evidence_reference: str = EVIDENCE_REFERENCE
    effective_evidence_date: str = "2026-09-11"
    evidence_version: int = 1
    reason_summary: str = (
        "Materially different postponement/rescheduling, expiration windows, "
        "fallback-source hierarchies, and fair-market settlement behavior."
    )


FAMILY_EXCLUSIONS = (
    FamilyExclusion("KXNFLGAME", "nfl", "football_team_full_game_winner"),
    FamilyExclusion("KXMLBGAME", "mlb", "baseball_team_full_game_winner"),
    FamilyExclusion(
        "KXMLBTOTAL", "mlb", "baseball_team_full_game_total",
        market_type="totals",
        sports_market_type_v2="SPORTS_MARKET_TYPE_TOTAL",
        evidence_reference=MLB_TOTALS_EVIDENCE_REFERENCE,
        effective_evidence_date="2026-09-12",
        reason_summary=(
            "Materially different resumption windows, fair-market reference timing, "
            "pre-first-pitch forfeit treatment, and nominal expiration horizons."
        ),
    ),
)


def family_exclusion(
    kalshi: SemanticContract, polymarket_us: SemanticContract
) -> FamilyExclusion | None:
    """Return an exclusion only when every narrow structured identifier agrees."""
    if kalshi.venue != "kalshi" or polymarket_us.venue != "polymarket_us":
        raise ValueError("family_exclusion expects Kalshi then Polymarket US")
    left, right = kalshi.family_metadata, polymarket_us.family_metadata
    for policy in FAMILY_EXCLUSIONS:
        if (
            left.kalshi_series == policy.kalshi_series
            and right.polymarket_league == policy.polymarket_league
            and right.market_type == policy.market_type
            and right.sports_market_type == policy.sports_market_type
            and right.sports_market_type_v2 == policy.sports_market_type_v2
        ):
            return policy
    return None
