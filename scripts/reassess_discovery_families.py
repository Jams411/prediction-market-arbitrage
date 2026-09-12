#!/usr/bin/env python3
"""Bounded public policy-v2 observation and event-balanced research inventory.

24 event metadata GETs: six previously evidenced games, with winner, spread,
and total Kalshi parents for each. No books, prices, authentication or execution.
This targeted sample cannot establish absence of non-sports opportunities.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import cast

from discover_contract_pairs import _diagnostics_json, _objects
from observe_sports_family_policy import _TARGETS, _get_event

from prediction_market_arbitrage.pair_discovery import (
    ComboClassification,
    classify_polymarket_us_combo,
    diagnose_candidates,
    enrich_kalshi_markets,
    enrich_polymarket_us_markets,
)
from prediction_market_arbitrage.pair_discovery.family_policy import FAMILY_EXCLUSIONS, POLICY_ID

# Exact proposition types, not title-word classification. Periods stay distinct.
_RESEARCH_FAMILIES = {
    ("KXNFLSPREAD", "nfl", "football_team_full_game_spread"): "NFL full-game spreads",
    ("KXNFLTOTAL", "nfl", "football_team_full_game_total"): "NFL full-game totals",
    ("KXMLBSPREAD", "mlb", "baseball_team_full_game_spread"): "MLB full-game spreads",
}


@dataclass
class _Relationship:
    candidate_pairs: int = 0
    same_event_pairs: int = 0
    event_overlaps: set[str] = field(default_factory=set)


@dataclass
class _Research:
    events: set[str] = field(default_factory=set)
    active_events: set[str] = field(default_factory=set)
    line_events: set[str] = field(default_factory=set)
    candidate_pairs: int = 0
    examples: list[dict[str, str]] = field(default_factory=list)


def _family(market: dict[str, object]) -> str:
    return str(market.get("sportsMarketType") or "UNKNOWN")


def observe() -> dict[str, object]:
    from datetime import UTC, datetime

    kalshi_events, poly_events = [], []
    sources: list[str] = []
    event_map: dict[str, str] = {}
    for winner_ticker, slug in _TARGETS:
        for kind in ("GAME", "SPREAD", "TOTAL"):
            ticker = winner_ticker.replace("GAME-", kind + "-", 1)
            url = ("https://external-api.kalshi.com/trade-api/v2/events/"
                   + ticker + "?with_nested_markets=true")
            event = _get_event(url)
            if event.get("event_ticker") != ticker:
                raise ValueError("Kalshi parent identity mismatch")
            event_map[ticker] = slug
            kalshi_events.append(event)
            sources.append(url)
        url = "https://gateway.polymarket.us/v1/events/slug/" + slug
        event = _get_event(url)
        if event.get("slug") != slug:
            raise ValueError("Polymarket parent identity mismatch")
        poly_events.append(event)
        sources.append(url)

    # Equal per-parent limits; preserve full-game families before partial games/props.
    kr = [m for e in kalshi_events for m in sorted(
        _objects(e.get("markets"), ctx="Kalshi children"),
        key=lambda m: str(m.get("ticker")))[:10]]
    pr: list[dict[str, object]] = []
    for e in poly_events:
        counts: Counter[str] = Counter()
        children = sorted(_objects(e.get("markets"), ctx="Polymarket children"),
                          key=lambda m: ("full_game" not in _family(m),
                                         _family(m), str(m.get("slug"))))
        for m in children:
            family = _family(m)
            cap = 3 if "full_game" in family else 1
            if counts[family] < cap and sum(counts.values()) < 24:
                counts[family] += 1
                pr.append(m)
    ke, pe = enrich_kalshi_markets(kr, kalshi_events), enrich_polymarket_us_markets(pr, poly_events)
    d = diagnose_candidates(ke.profiles, pe.profiles, candidate_limit=20)
    if d.mlb_totals_family_excluded == 0:
        raise RuntimeError("STOP: MLB full-game total policy was not exercised")
    km = {str(m['ticker']): m for m in kr}
    pm = {str(m['slug']): m for m in pr}
    ordinary = Counter(
        _family(m) for m in pr
        if classify_polymarket_us_combo(m) is ComboClassification.ORDINARY_CONTRACT)
    # Count all surfaced relationships, not only the top-20 ranking truncation.
    relationships: dict[str, _Relationship] = {}
    same_event_passed = 0
    exact_proposition_passed = 0
    research: dict[str, _Research] = {}
    for left in ke.profiles:
        for right in pe.profiles:
            single = diagnose_candidates([left], [right], candidate_limit=1, near_miss_limit=1)
            if not single.passed:
                continue
            series = left.family_metadata.kalshi_series or "UNKNOWN"
            league = right.family_metadata.polymarket_league or "UNKNOWN"
            kind = right.family_metadata.sports_market_type or "UNKNOWN"
            same_event = event_map.get(left.event_identifier or "") == right.event_identifier
            key = f"{series} <-> {league}/{kind}"
            if key not in relationships:
                relationships[key] = _Relationship()
            row = relationships[key]
            row.candidate_pairs += 1
            if same_event:
                row.same_event_pairs += 1
                row.event_overlaps.add(right.event_identifier or "UNKNOWN")
                same_event_passed += 1
            name = _RESEARCH_FAMILIES.get((series, league, kind))
            if name is None or not same_event:
                continue
            exact_proposition_passed += 1
            if name not in research:
                research[name] = _Research()
            r = research[name]
            r.events.add(right.event_identifier or "UNKNOWN")
            r.candidate_pairs += 1
            rawk, rawp = km[left.identifier], pm[right.identifier]
            if rawk.get("status") == "active" and rawp.get("closed") is False:
                r.active_events.add(right.event_identifier or "UNKNOWN")
            strike, line = rawk.get("floor_strike"), rawp.get("line")
            comparable = False
            if isinstance(strike, (int, float, str)) and isinstance(line, (int, float, str)):
                # Spread magnitude is a research lead only; direction is unverified.
                comparable = abs(Decimal(str(strike))) == abs(Decimal(str(line)))
            if comparable:
                r.line_events.add(right.event_identifier or "UNKNOWN")
            examples = r.examples
            if comparable and len(examples) < 3:
                examples.append({"kalshi": left.identifier, "polymarket_us": right.identifier,
                                 "kalshi_floor_strike": str(strike), "polymarket_line": str(line),
                                 "orientation_equivalence": "UNVERIFIED"})
    aggregate = []
    for key, row in sorted(relationships.items()):
        aggregate.append({"relationship": key, "candidate_pairs": row.candidate_pairs,
                          "same_event_pairs": row.same_event_pairs,
                          "distinct_event_overlaps": len(row.event_overlaps)})
    ranked = []
    for name, r in research.items():
        ne = len(r.events)
        na = len(r.active_events)
        nl = len(r.line_events)
        # Equal event weights, bounded 0..3; no child-count or price term.
        score = 3 * min(ne, 3) + 2 * min(nl, 3) + 2 * min(na, 3)
        ranked.append({"family": name, "research_priority_score": score,
                       "distinct_event_overlaps": ne, "active_event_overlaps": na,
                       "shared_line_magnitude_events": nl, "candidate_pairs": r.candidate_pairs,
                       "events": sorted(r.events), "examples": r.examples,
                       "metadata_quality": "explicit parent series, league and full-game type",
                       "rule_availability": "generic rules available; family terms not audited",
                       "known_rule_risk": "HIGH: related sports families fail exceptional states"})
    ranked.sort(key=lambda r: (-cast(int, r["research_priority_score"]), str(r["family"])))
    return {
        "observed_at": datetime.now(UTC).isoformat(), "policy_id": POLICY_ID,
        "policy_entries": [asdict(p) for p in FAMILY_EXCLUSIONS], "sources": sources,
        "command": ".venv/bin/python scripts/reassess_discovery_families.py",
        "enrichment": {"kalshi": asdict(ke.stats), "polymarket_us": asdict(pe.stats)},
        "ordinary_polymarket_families_retained_after_combo": dict(ordinary),
        "diagnostics": {k: v for k, v in _diagnostics_json(d).items()
                        if k != "top_below_threshold_near_misses"},
        "top_candidates_retained": len(d.passed_candidates),
        "all_passed_same_event_pairs": same_event_passed,
        "all_passed_same_event_exact_research_family_pairs": exact_proposition_passed,
        "remaining_relationships": aggregate, "research_ranking": ranked[:5],
        "sampling": "six evidenced game overlaps; <=10 Kalshi children/parent; <=24 Polymarket "
                    "children/event, <=3 per full-game type and <=1 per other type",
        "coverage_limits": "targeted NFL/MLB games only; politics, company/IPO, futures and other "
                           "sports are UNASSESSED, not shown to be absent; partial-period and "
                           "cross-family lexical candidates do not prove proposition overlap",
        "score_definition": "3*min(distinct events,3) + 2*min(shared line magnitude events,3) "
                            "+ 2*min(active events,3); research priority only, not profit; "
                            "metadata/rule availability and known-rule risk reported separately",
        "safety": "24 public metadata GETs only; no books/prices used, authentication, accounts, "
                  "registry writes, strategy/arbitrage/execution, orders or real money",
    }


if __name__ == "__main__":
    print(json.dumps(observe(), indent=2, sort_keys=True))
