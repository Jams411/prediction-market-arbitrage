"""Deterministic tests for unverified contract-equivalence triage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.pair_discovery import (
    CandidatePair,
    ComparisonClass,
    SemanticContract,
    compare_contracts,
    discover_candidates,
    from_kalshi_market,
    from_polymarket_us_market,
)
from prediction_market_arbitrage.registry import MarketPairRecord, load_registry

T0 = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
T1 = datetime(2027, 2, 1, 15, 0, tzinfo=UTC)


def _profile(
    venue: str,
    identifier: str,
    *,
    event: str = "2026 Example League championship",
    title: str = "Will Example United win the 2026 championship?",
) -> SemanticContract:
    return SemanticContract(
        venue=venue,
        identifier=identifier,
        title=title,
        rule_sources=(f"{venue}:market:{identifier}",),
        underlying_event=event,
        binary_proposition="Example United wins the 2026 Example League championship",
        participant_outcome="Example United",
        threshold=None,
        threshold_inclusivity=None,
        measurement_unit="championship_winner",
        event_time_window=T0,
        close_conditions="closes when a champion is declared",
        resolution_source="official Example League result",
        cancellation_postponement="remains open if postponed; void if canceled",
        multiple_winner_treatment="each co-champion is a winner",
        void_refund_fair_market="canceled event is void and refunded",
        settlement_backstop=T1,
        yes_no_mapping="YES=Example United wins; NO=Example United does not win",
    )


def _classes(candidate: CandidatePair) -> dict[str, ComparisonClass]:
    return {item.field: item.classification for item in candidate.comparisons}


def test_strong_semantic_match_remains_unverified() -> None:
    candidate = compare_contracts(
        _profile("kalshi", "K-SYNTHETIC"),
        _profile("polymarket_us", "pm-synthetic"),
    )

    assert candidate.verification_priority == 100
    assert candidate.status == "UNVERIFIED"
    assert "human/primary-source verification required" in candidate.warning
    assert set(_classes(candidate).values()) <= {
        ComparisonClass.MATCH,
        ComparisonClass.NOT_APPLICABLE,
    }


def test_equivalent_looking_title_does_not_hide_cancellation_mismatch() -> None:
    kalshi = _profile("kalshi", "K-CANCEL")
    polymarket = replace(
        _profile("polymarket_us", "pm-cancel"),
        cancellation_postponement="settles at last fair market price if canceled",
    )

    candidate = compare_contracts(kalshi, polymarket)

    assert _classes(candidate)["cancellation_postponement"] is ComparisonClass.MISMATCH
    assert candidate.verification_priority < 100


def test_same_event_different_threshold_and_inclusivity_are_mismatches() -> None:
    kalshi = replace(
        _profile("kalshi", "K-THRESHOLD"),
        threshold=Decimal("100.00"),
        threshold_inclusivity=">",
        measurement_unit="usd",
    )
    polymarket = replace(
        _profile("polymarket_us", "pm-threshold"),
        threshold=Decimal("100.00"),
        threshold_inclusivity=">=",
        measurement_unit="usd",
    )

    candidate = compare_contracts(kalshi, polymarket)
    classes = _classes(candidate)

    assert classes["threshold_value"] is ComparisonClass.MATCH
    assert classes["threshold_inclusivity"] is ComparisonClass.MISMATCH


def test_decimal_threshold_comparison_is_exact() -> None:
    kalshi = replace(_profile("kalshi", "K-DECIMAL"), threshold=Decimal("0.10"))
    polymarket = replace(
        _profile("polymarket_us", "pm-decimal"), threshold=Decimal("0.1000000000000000001")
    )

    assert _classes(compare_contracts(kalshi, polymarket))["threshold_value"] is (
        ComparisonClass.MISMATCH
    )


def test_different_events_with_lexical_overlap_rank_below_true_match() -> None:
    kalshi = _profile("kalshi", "K-EVENT")
    strong = _profile("polymarket_us", "pm-strong")
    wrong = replace(
        _profile(
            "polymarket_us",
            "pm-wrong",
            event="2026 Example League conference championship",
            title="Will Example United win the 2026 conference championship?",
        ),
        binary_proposition="Example United wins the conference championship",
    )

    ranked = discover_candidates([kalshi], [wrong, strong])

    assert [item.polymarket_us.identifier for item in ranked] == ["pm-strong", "pm-wrong"]
    assert _classes(ranked[1])["underlying_event_entity"] is ComparisonClass.MISMATCH


def test_unknown_rule_field_stays_unknown() -> None:
    candidate = compare_contracts(
        _profile("kalshi", "K-UNKNOWN"),
        replace(_profile("polymarket_us", "pm-unknown"), resolution_source=None),
    )

    comparison = next(item for item in candidate.comparisons if item.field == "resolution_source")
    assert comparison.classification is ComparisonClass.UNKNOWN
    assert comparison.polymarket_us_value is None


def test_multiple_winner_mismatch_is_material() -> None:
    candidate = compare_contracts(
        _profile("kalshi", "K-MULTIPLE"),
        replace(
            _profile("polymarket_us", "pm-multiple"),
            multiple_winner_treatment="payout divided equally among co-champions",
        ),
    )

    assert _classes(candidate)["multiple_winner_treatment"] is ComparisonClass.MISMATCH
    assert candidate.verification_priority < 100


def test_ranking_is_deterministic_for_ties() -> None:
    kalshi = _profile("kalshi", "K-TIE")
    a = _profile("polymarket_us", "pm-a")
    b = _profile("polymarket_us", "pm-b")

    first = discover_candidates([kalshi], [b, a])
    second = discover_candidates([kalshi], [a, b])

    assert [item.polymarket_us.identifier for item in first] == ["pm-a", "pm-b"]
    assert first == second


def test_discovery_output_cannot_approve_or_enter_canonical_registry() -> None:
    candidate = compare_contracts(
        _profile("kalshi", "K-NOT-REGISTRY"),
        _profile("polymarket_us", "pm-not-registry"),
    )

    assert not isinstance(candidate, MarketPairRecord)
    assert candidate.status == "UNVERIFIED"
    assert load_registry().all() == ()
    assert load_registry().eligible() == ()


def test_public_metadata_profiles_preserve_unknowns_and_decimal_thresholds() -> None:
    kalshi = from_kalshi_market(
        {
            "ticker": "K-SYNTHETIC-T100",
            "event_ticker": "K-SYNTHETIC",
            "title": "Will the value be above 100 USD?",
            "rules_primary": "If the value is greater than 100 USD, resolves Yes.",
            "strike_type": "greater",
            "floor_strike": "100.000",
            "occurrence_datetime": "2026-11-03T00:00:00Z",
            "expiration_time": "2027-02-01T15:00:00Z",
            "yes_sub_title": "Above 100",
            "no_sub_title": "100 or below",
        }
    )
    polymarket = from_polymarket_us_market(
        {
            "slug": "pm-synthetic-100",
            "question": "Will the value be above 100 USD?",
            "title": "Above 100",
            "description": "Resolves Yes if the value is above 100 USD.",
            "gameStartTime": "2026-11-03T00:00:00Z",
            "endDate": "2027-02-01T15:00:00Z",
            "marketSides": [
                {"long": True, "description": "Above 100"},
                {"long": False, "description": "100 or below"},
            ],
        }
    )

    assert kalshi.threshold == Decimal("100.000")
    assert polymarket.threshold == Decimal("100")
    assert kalshi.resolution_source is None
    assert polymarket.resolution_source is None
