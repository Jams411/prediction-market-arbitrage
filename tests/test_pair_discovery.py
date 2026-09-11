"""Deterministic tests for unverified contract-equivalence triage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.pair_discovery import (
    CandidatePair,
    ComboClassification,
    ComparisonClass,
    DiscoveryDiagnostics,
    SemanticContract,
    classify_polymarket_us_combo,
    compare_contracts,
    diagnose_candidates,
    discover_candidates,
    enrich_kalshi_markets,
    enrich_polymarket_us_markets,
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


def test_strong_same_event_near_miss_is_prioritized_below_lexical_gate() -> None:
    kalshi = _profile(
        "kalshi",
        "K-NEAR",
        event="shared final",
        title="alpha bravo charlie delta echo foxtrot golf hotel iris",
    )
    same_event = _profile(
        "polymarket_us",
        "pm-same-event",
        event="shared final",
        title="juliet kilo lima mike november oscar papa queen romeo",
    )
    unrelated = replace(
        _profile(
            "polymarket_us",
            "pm-unrelated",
            event="different contest",
            title="alpha bravo quebec romeo sierra tango uniform victor whiskey",
        ),
        participant_outcome="Different Club",
        event_time_window=T1,
    )

    result = diagnose_candidates([kalshi], [unrelated, same_event], near_miss_limit=2)

    assert result.passed == 0
    assert result.near_misses[0].polymarket_us.identifier == "pm-same-event"
    assert result.near_misses[0].lexical_signal < Decimal("0.20")
    signals = {item.field: item.classification for item in result.near_misses[0].coarse_signals}
    assert signals["underlying_event"] is ComparisonClass.MATCH
    assert signals["participant"] is ComparisonClass.MATCH


def test_generic_shared_token_false_positive_is_diagnosable() -> None:
    kalshi = replace(
        _profile("kalshi", "K-GENERIC", event="college game"),
        title="Falcons college score total",
        participant_outcome="Atlanta Falcons",
    )
    polymarket = replace(
        _profile("polymarket_us", "pm-generic", event="professional season"),
        title="Falcons professional championship",
        participant_outcome="Springfield Falcons",
    )

    result = diagnose_candidates([kalshi], [polymarket])
    near_miss = result.near_misses[0]

    assert "falcons" in near_miss.shared_tokens
    assert near_miss.rejection_reason.endswith("below unchanged threshold 0.20")
    signals = {signal.field: signal.classification for signal in near_miss.coarse_signals}
    assert signals["underlying_event"] is ComparisonClass.MISMATCH
    assert signals["participant"] is ComparisonClass.MISMATCH


def test_normalized_token_output_is_sorted_and_deterministic() -> None:
    kalshi = replace(
        _profile("kalshi", "K-TOKENS", event="Zulu Alpha"),
        title="Will Bravo, alpha win?",
        participant_outcome=None,
    )
    polymarket = replace(
        _profile("polymarket_us", "pm-tokens", event="Other Event"),
        title="Alpha Charlie Delta Echo Foxtrot Golf Hotel India",
        participant_outcome=None,
    )

    first = diagnose_candidates([kalshi], [polymarket]).near_misses[0]
    second = diagnose_candidates([kalshi], [polymarket]).near_misses[0]

    assert first.kalshi_keys.all_tokens == tuple(sorted(first.kalshi_keys.all_tokens))
    assert first.shared_tokens == ("alpha",)
    assert first == second


def test_missing_metadata_is_explicit_in_diagnostics() -> None:
    kalshi = replace(
        _profile(
            "kalshi", "K-MISSING", event="event one", title="alpha bravo charlie delta echo"
        ),
        category=None,
        participant_outcome=None,
        resolution_source=None,
    )
    polymarket = replace(
        _profile(
            "polymarket_us",
            "pm-missing",
            event="event two",
            title="alpha foxtrot golf hotel india",
        ),
        participant_outcome="Different Club",
        event_time_window=None,
    )

    near_miss = diagnose_candidates([kalshi], [polymarket]).near_misses[0]

    assert "kalshi.category" in near_miss.missing_metadata_fields
    assert "kalshi.resolution_source" in near_miss.missing_metadata_fields
    assert "polymarket_us.event_time_window" in near_miss.missing_metadata_fields


def test_diagnostic_counts_reconcile_for_actual_cross_product() -> None:
    kalshi = [_profile("kalshi", "K-A"), _profile("kalshi", "K-B", title="other one")]
    polymarket = [
        _profile("polymarket_us", "pm-a"),
        _profile("polymarket_us", "pm-b", title="other two"),
        _profile("polymarket_us", "pm-c", title="unrelated words"),
    ]

    result = diagnose_candidates(kalshi, polymarket)

    assert result.considered == 6
    assert result.passed + result.rejected == result.considered


def test_near_miss_top_n_is_bounded_and_deterministic() -> None:
    kalshi = [
        replace(
            _profile(
                "kalshi", "K-BOUND", event="event kalshi", title="shared alpha one two three four"
            ),
            participant_outcome=None,
        )
    ]
    polymarket = [
        replace(
            _profile(
                "polymarket_us",
                f"pm-{suffix}",
                event=f"event polymarket {suffix}",
                title=f"shared {suffix} five six seven eight",
            ),
            participant_outcome=None,
        )
        for suffix in ("c", "a", "b")
    ]

    first = diagnose_candidates(kalshi, reversed(polymarket), near_miss_limit=2)
    second = diagnose_candidates(kalshi, polymarket, near_miss_limit=2)

    assert len(first.near_misses) == 2
    assert first.near_misses == second.near_misses
    assert [item.polymarket_us.identifier for item in first.near_misses] == ["pm-a", "pm-b"]


def test_diagnostics_remain_unverified_and_cannot_enter_registry() -> None:
    result = diagnose_candidates(
        [_profile("kalshi", "K-DIAGNOSTIC")],
        [_profile("polymarket_us", "pm-diagnostic", title="unrelated")],
    )

    assert isinstance(result, DiscoveryDiagnostics)
    assert result.status == "UNVERIFIED"
    assert all(item.status == "UNVERIFIED" for item in result.near_misses)
    assert not isinstance(result, MarketPairRecord)
    assert load_registry().eligible() == ()


def _kalshi_market(ticker: str, event_ticker: str, title: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "title": title,
        "yes_sub_title": "Example United",
        "no_sub_title": "Example United",
        "market_type": "binary",
        "occurrence_datetime": "2026-11-03T00:00:00Z",
        "rules_primary": f"If {title}, resolves Yes.",
    }


def _polymarket_market(slug: str, title: str) -> dict[str, object]:
    return {
        "slug": slug,
        "question": "League championship",
        "title": title,
        "category": "sports",
        "marketType": "futures",
        "comboEnabled": False,
        "marketSides": [
            {
                "long": True,
                "description": "Yes",
                "teamId": 42,
                "team": {"name": "Example United", "league": "EL"},
            },
            {"long": False, "description": "No", "teamId": 42},
        ],
    }


def test_authoritative_parent_metadata_survives_enrichment() -> None:
    kalshi = enrich_kalshi_markets(
        [_kalshi_market("K-CHILD", "K-EVENT", "Alpha proposition")],
        [
            {
                "event_ticker": "K-EVENT",
                "title": "2026 Example League Championship",
                "category": "Sports",
                "series_ticker": "KXEXAMPLE",
                "product_metadata": {"competition": "Example League"},
                "settlement_sources": [
                    {"name": "Example League", "url": "https://example.test/results"}
                ],
            }
        ],
    ).profiles[0]
    polymarket = enrich_polymarket_us_markets(
        [_polymarket_market("pm-child", "Beta proposition")],
        [
            {
                "id": 7,
                "slug": "pm-event",
                "title": "2026 Example League Championship",
                "category": "sports",
                "startTime": "2026-11-03T00:00:00Z",
                "seriesSlug": "example-2026",
                "tags": [
                    {
                        "league": {
                            "name": "Example League",
                            "resolution": "https://example.test/results",
                        }
                    }
                ],
                "markets": [{"slug": "pm-child"}],
            }
        ],
    ).profiles[0]

    assert kalshi.event_identifier == "K-EVENT"
    assert polymarket.event_identifier == "pm-event"
    assert "kalshi:event:K-EVENT" in kalshi.rule_sources
    assert "polymarket_us:event:pm-event" in polymarket.rule_sources
    assert kalshi.underlying_event == polymarket.underlying_event
    assert kalshi.series_or_league == polymarket.series_or_league == "Example League"
    assert kalshi.category == "Sports"
    assert polymarket.category == "sports"
    assert polymarket.participant_outcome == "Example United"
    assert polymarket.participant_identifiers == ("team:42",)
    assert kalshi.resolution_sources == polymarket.resolution_sources
    assert polymarket.market_type == "futures"


def test_multiple_children_reuse_one_cached_parent_event() -> None:
    result = enrich_kalshi_markets(
        [
            _kalshi_market("K-A", "K-PARENT", "Alpha"),
            _kalshi_market("K-B", "K-PARENT", "Beta"),
        ],
        [{"event_ticker": "K-PARENT", "title": "Shared event"}],
    )

    assert result.stats.parent_event_records_fetched == 1
    assert result.stats.parent_events_used == 1
    assert result.stats.parent_cache_reuses == 1
    assert [profile.underlying_event for profile in result.profiles] == [
        "Shared event",
        "Shared event",
    ]


def test_structured_combos_are_filtered_but_simple_markets_remain() -> None:
    kalshi_combo = _kalshi_market("K-MVE", "K-MVE-EVENT", "Combo")
    kalshi_combo["mve_collection_ticker"] = "KXMVE"
    polymarket_combo = {
        "id": "caoc-synthetic-combo",
        "legs": [
            {"symbol": "market-a", "side": "SIDE_BUY"},
            {"symbol": "market-b", "side": "SIDE_SELL"},
        ],
    }

    kalshi = enrich_kalshi_markets(
        [kalshi_combo, _kalshi_market("K-SIMPLE", "K-EVENT", "Simple")],
        [{"event_ticker": "K-EVENT", "title": "Simple event"}],
    )
    polymarket = enrich_polymarket_us_markets(
        [polymarket_combo, _polymarket_market("pm-simple", "Simple")],
        [{"slug": "pm-event", "title": "Simple event", "markets": [{"slug": "pm-simple"}]}],
    )

    assert kalshi.stats.combo_markets_filtered == 1
    assert polymarket.stats.combo_markets_filtered == 1
    assert [profile.identifier for profile in kalshi.profiles] == ["K-SIMPLE"]
    assert [profile.identifier for profile in polymarket.profiles] == ["pm-simple"]


def test_combo_enabled_capability_does_not_exclude_ordinary_nfl_moneyline() -> None:
    market = _polymarket_market("aec-nfl-ari-lac", "Arizona vs Los Angeles")
    market.update(
        {
            "marketType": "moneyline",
            "sportsMarketType": "football_team_full_game_winner",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "comboEnabled": True,
        }
    )

    result = enrich_polymarket_us_markets(
        [market],
        [
            {
                "slug": "nfl-ari-lac",
                "title": "Arizona vs Los Angeles",
                "combos": {"enabled": True, "numMarkets": 770},
                "markets": [{"slug": "aec-nfl-ari-lac"}],
            }
        ],
    )

    assert classify_polymarket_us_combo(market) is ComboClassification.ORDINARY_CONTRACT
    assert [profile.identifier for profile in result.profiles] == ["aec-nfl-ari-lac"]
    assert result.profiles[0].market_type == "SPORTS_MARKET_TYPE_MONEYLINE"
    assert result.stats.ordinary_markets_retained == 1
    assert result.stats.combo_markets_filtered == 0
    assert result.stats.parent_events_used == 1


def test_combo_enabled_capability_does_not_exclude_ordinary_mlb_moneyline() -> None:
    market = _polymarket_market("aec-mlb-col-det", "Colorado vs Detroit")
    market.update(
        {
            "marketType": "moneyline",
            "sportsMarketType": "baseball_team_full_game_winner",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "comboEnabled": True,
        }
    )

    result = enrich_polymarket_us_markets([market], [])

    assert [profile.identifier for profile in result.profiles] == ["aec-mlb-col-det"]
    assert result.stats.ordinary_markets_retained == 1
    assert result.stats.combo_markets_filtered == 0


def test_combo_enabled_capability_does_not_exclude_ordinary_spread() -> None:
    market = _polymarket_market("asc-nfl-ari-lac-pos-3pt5", "Arizona +3.5")
    market.update(
        {
            "marketType": "spreads",
            "sportsMarketType": "football_team_full_game_spread",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
            "comboEnabled": True,
        }
    )

    result = enrich_polymarket_us_markets([market], [])

    assert [profile.identifier for profile in result.profiles] == [
        "asc-nfl-ari-lac-pos-3pt5"
    ]
    assert result.profiles[0].market_type == "SPORTS_MARKET_TYPE_SPREAD"


def test_confirmed_caoc_combo_requires_structured_legs() -> None:
    combo = {
        "id": "caoc-synthetic-combo",
        "legs": [
            {"symbol": "market-a", "side": "SIDE_BUY"},
            {"symbol": "market-b", "side": "SIDE_SELL"},
        ],
        "state": "INSTRUMENT_STATE_OPEN",
    }

    assert classify_polymarket_us_combo(combo) is ComboClassification.CONFIRMED_COMBO


def test_ambiguous_combo_structure_is_unknown_and_not_silently_excluded() -> None:
    market = _polymarket_market("caoc-ambiguous", "Ambiguous combo")
    market["legs"] = [{"symbol": "market-a", "side": "SIDE_BUY"}]

    result = enrich_polymarket_us_markets([market], [])

    assert classify_polymarket_us_combo(market) is ComboClassification.UNKNOWN
    assert [profile.identifier for profile in result.profiles] == ["caoc-ambiguous"]
    assert result.stats.combo_metadata_unknown == 1
    assert result.stats.combo_markets_filtered == 0


def test_authoritative_event_context_surfaces_weak_market_titles() -> None:
    kalshi = enrich_kalshi_markets(
        [_kalshi_market("K-WEAK", "K-EVENT", "Alpha")],
        [{"event_ticker": "K-EVENT", "title": "2026 Example League Championship Final"}],
    ).profiles
    polymarket = enrich_polymarket_us_markets(
        [_polymarket_market("pm-weak", "Zulu")],
        [
            {
                "slug": "pm-event",
                "title": "2026 Example League Championship Final",
                "markets": [{"slug": "pm-weak"}],
            }
        ],
    ).profiles

    candidates = discover_candidates(kalshi, polymarket)

    assert len(candidates) == 1
    assert candidates[0].lexical_signal >= Decimal("0.20")
    assert candidates[0].status == "UNVERIFIED"


def test_shared_entity_different_event_does_not_clear_lexical_gate() -> None:
    kalshi = replace(
        _profile(
            "kalshi",
            "K-DIFFERENT",
            event="European cup quarterfinal one",
            title="Example United alpha bravo charlie",
        ),
        participant_outcome="Example United",
    )
    polymarket = replace(
        _profile(
            "polymarket_us",
            "pm-different",
            event="Domestic league relegation contest",
            title="Example United delta echo foxtrot",
        ),
        participant_outcome="Example United",
    )

    diagnostics = diagnose_candidates([kalshi], [polymarket])

    assert diagnostics.threshold == Decimal("0.20")
    assert diagnostics.passed == 0
    signals = {
        item.field: item.classification
        for item in diagnostics.near_misses[0].coarse_signals
    }
    assert signals["participant"] is ComparisonClass.MATCH
    assert signals["underlying_event"] is ComparisonClass.MISMATCH


def test_differing_authoritative_event_date_remains_a_blocker() -> None:
    candidate = compare_contracts(
        _profile("kalshi", "K-DATE"),
        replace(_profile("polymarket_us", "pm-date"), event_time_window=T1),
    )

    assert _classes(candidate)["event_time_window"] is ComparisonClass.MISMATCH


def test_missing_or_ambiguous_parent_metadata_stays_unknown() -> None:
    market = _polymarket_market("pm-orphan", "Orphan")
    result = enrich_polymarket_us_markets(
        [market],
        [
            {"slug": "event-a", "title": "A", "markets": [{"slug": "pm-orphan"}]},
            {"slug": "event-b", "title": "B", "markets": [{"slug": "pm-orphan"}]},
        ],
    )

    assert result.stats.ambiguous_parent_metadata == 1
    assert result.profiles[0].event_identifier is None
    assert result.profiles[0].resolution_sources == ()


def test_missing_polymarket_combo_flag_remains_unknown_not_filtered() -> None:
    market = _polymarket_market("pm-combo-unknown", "Unknown combo status")
    del market["comboEnabled"]
    result = enrich_polymarket_us_markets(
        [market],
        [
            {
                "slug": "pm-parent",
                "title": "Parent",
                "markets": [{"slug": "pm-combo-unknown"}],
            }
        ],
    )

    assert result.stats.combo_metadata_unknown == 1
    assert result.stats.ordinary_markets_retained == 0
    assert result.stats.combo_markets_filtered == 0
    assert [profile.identifier for profile in result.profiles] == ["pm-combo-unknown"]
