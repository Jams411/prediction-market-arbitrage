"""Synthetic policy scope, ordering, and discovery safety regressions."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from prediction_market_arbitrage.pair_discovery import (
    compare_contracts,
    diagnose_candidates,
    discover_candidates,
    enrich_kalshi_markets,
    enrich_polymarket_us_markets,
    from_polymarket_us_market,
)
from prediction_market_arbitrage.pair_discovery.family_policy import (
    POLICY_ID,
    family_exclusion,
)
from prediction_market_arbitrage.pair_discovery.models import SemanticContract
from prediction_market_arbitrage.registry import DEFAULT_REGISTRY_PATH


def _inputs(league: str) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    sport = "football" if league == "nfl" else "baseball"
    market: dict[str, object] = {
        "slug": f"synthetic-{league}-moneyline",
        "question": "Synthetic Alpha versus Beta full game",
        "comboEnabled": True,
        "marketType": "moneyline",
        "sportsMarketType": f"{sport}_team_full_game_winner",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
    }
    event: dict[str, object] = {
        "slug": f"synthetic-{league}-event",
        "title": "Synthetic Alpha versus Beta full game",
        "tags": [{"league": {"name": league.upper(), "slug": league}}],
        "markets": [market],
    }
    kalshi_event: dict[str, object] = {
        "event_ticker": "SYNTHETIC-EVENT",
        "series_ticker": "KXNFLGAME" if league == "nfl" else "KXMLBGAME",
        "title": "Synthetic Alpha versus Beta full game",
        "product_metadata": {"competition": "Example competition"},
    }
    return market, event, kalshi_event


def _kalshi(event: dict[str, object]) -> SemanticContract:
    return enrich_kalshi_markets(
        [{"ticker": "SYNTHETIC-CHILD", "event_ticker": "SYNTHETIC-EVENT",
          "title": "Synthetic Alpha versus Beta full game"}],
        [event],
    ).profiles[0]


@pytest.mark.parametrize("league", ["nfl", "mlb"])
def test_ordinary_moneyline_reaches_family_policy_after_combo(league: str) -> None:
    market, event, kevent = _inputs(league)
    result = enrich_polymarket_us_markets([market], [event])
    assert result.stats.ordinary_markets_retained == 1
    assert result.stats.combo_markets_filtered == 0
    left, right = _kalshi(kevent), result.profiles[0]
    policy = family_exclusion(left, right)
    assert policy is not None
    assert policy.policy_id == POLICY_ID == "sports-family-equivalence-v1"
    assert policy.classification == "SYSTEMATICALLY_INCOMPATIBLE"
    assert policy.scope == "STRICT_RISKLESS_CROSS_VENUE_EQUIVALENCE"
    assert Path(policy.evidence_reference).is_file()
    with patch(
        "prediction_market_arbitrage.pair_discovery.comparison.compare_contracts",
        side_effect=AssertionError("excluded pairs must not be semantically compared"),
    ):
        assert discover_candidates([left], [right]) == ()
        diagnostic = diagnose_candidates([left], [right])
    assert diagnostic.family_incompatible_excluded == diagnostic.considered == 1
    assert diagnostic.lexical_evaluated == diagnostic.semantically_evaluated == 0


@pytest.mark.parametrize("league", ["nfl", "mlb"])
@pytest.mark.parametrize("family", ["spread", "total", "prop", "future", "championship", "award"])
def test_other_propositions_remain_discoverable(league: str, family: str) -> None:
    market, event, kevent = _inputs(league)
    market.update(marketType=family, sportsMarketType=f"synthetic_{family}",
                  sportsMarketTypeV2=f"SPORTS_MARKET_TYPE_{family.upper()}")
    left = _kalshi(kevent)
    right = from_polymarket_us_market(market, event)
    assert family_exclusion(left, right) is None
    expected = compare_contracts(left, right)
    assert discover_candidates([left], [right]) == (expected,)
    assert diagnose_candidates([left], [right]).passed_candidates == (expected,)


@pytest.mark.parametrize("field", ["marketType", "sportsMarketType", "sportsMarketTypeV2"])
@pytest.mark.parametrize("value", [None, "", "conflicting-spread"])
def test_missing_or_conflicting_family_retained(field: str, value: object) -> None:
    market, event, kevent = _inputs("nfl")
    market[field] = value
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is None


@pytest.mark.parametrize("tags", [
    [], [{"label": "NFL", "slug": "nfl"}],
    [{"league": {"name": "NFL", "slug": "mlb"}}],
    [{"league": {"name": "NFL", "slug": "nfl"}},
     {"league": {"name": "MLB", "slug": "mlb"}}],
    [{"league": {"name": "NFL"}}],
])
def test_ambiguous_league_retained(tags: list[dict[str, object]]) -> None:
    market, event, kevent = _inputs("nfl")
    event["tags"] = tags
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is None


def test_team_conflict_and_missing_parent_retained() -> None:
    market, event, kevent = _inputs("nfl")
    market["marketSides"] = [{"team": {"league": "mlb"}}]
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is None
    market["marketSides"] = [{"team": {"league": "nfl"}}]
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market)) is None


def test_title_or_ticker_prefix_is_not_family_evidence() -> None:
    left = SemanticContract("kalshi", "KXNFLGAME-SYNTHETIC", "NFL MLB moneyline")
    right = SemanticContract("polymarket_us", "synthetic-nfl", "NFL MLB moneyline")
    assert family_exclusion(left, right) is None
    market, event, kevent = _inputs("nfl")
    del kevent["series_ticker"]
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is None


@pytest.mark.parametrize("league", ["nba", "nhl", "politics", "companies", "ipo"])
def test_other_leagues_and_domains_retained(league: str) -> None:
    market, event, kevent = _inputs("nfl")
    event["tags"] = [{"league": {"name": league.upper(), "slug": league}}]
    right = from_polymarket_us_market(market, event)
    assert family_exclusion(_kalshi(kevent), right) is None
    kevent["series_ticker"] = "SYNTHETIC-OTHER-FAMILY"
    assert family_exclusion(_kalshi(kevent), right) is None


def test_confirmed_combo_removed_before_family_policy() -> None:
    market, event, kevent = _inputs("nfl")
    market.update(slug="caoc-synthetic-combo", legs=[
        {"symbol": "synthetic-a", "side": "SIDE_BUY"},
        {"symbol": "synthetic-b", "side": "SIDE_SELL"},
    ])
    enriched = enrich_polymarket_us_markets([market], [event])
    assert enriched.stats.combo_markets_filtered == 1
    result = diagnose_candidates([_kalshi(kevent)], enriched.profiles)
    assert result.considered == result.family_incompatible_excluded == 0


def test_counts_controls_and_registry_bytes_unchanged() -> None:
    registry = DEFAULT_REGISTRY_PATH
    before = registry.read_bytes()
    nm, ne, nk = _inputs("nfl")
    mm, me, mk = _inputs("mlb")
    left = [_kalshi(nk), replace(_kalshi(mk), identifier="SYNTHETIC-MLB")]
    right = [from_polymarket_us_market(nm, ne), from_polymarket_us_market(mm, me)]
    right.append(SemanticContract("polymarket_us", "synthetic-unrelated", "Zebra"))
    result = diagnose_candidates(left, right)
    assert result.considered == 6
    assert result.nfl_family_excluded == result.mlb_family_excluded == 1
    assert result.lexical_evaluated == 4
    assert result.passed == result.semantically_evaluated == 2
    assert result.rejected == 2
    assert result.family_incompatible_excluded + result.lexical_evaluated == result.considered
    assert result.passed_candidates == discover_candidates(left, right)
    assert all(p.status == "UNVERIFIED" for p in result.passed_candidates)
    assert registry.read_bytes() == before


@pytest.mark.parametrize("series", ["KXNFLSPREAD", "KXMLBSPREAD", "KXNFLTOTAL",
                                    "KXMLBTOTAL", "SYNTHETIC-CHAMPIONSHIP"])
def test_other_kalshi_series_not_excluded(series: str) -> None:
    market, event, kevent = _inputs("nfl")
    kevent["series_ticker"] = series
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is None


def test_navigation_subtags_do_not_define_event_league() -> None:
    market, event, kevent = _inputs("mlb")
    event["tags"] = [
        {"league": {"name": "MLB", "slug": "mlb"}},
        {"slug": "baseball", "subtags": [{"league": {"name": "KBO", "slug": "kbo"}}]},
    ]
    assert family_exclusion(_kalshi(kevent), from_polymarket_us_market(market, event)) is not None


def test_ambiguous_parent_join_retained() -> None:
    market, event, kevent = _inputs("nfl")
    other = dict(event, slug="synthetic-other-parent")
    result = enrich_polymarket_us_markets([market], [event, other])
    assert result.stats.ambiguous_parent_metadata == 1
    assert family_exclusion(_kalshi(kevent), result.profiles[0]) is None
