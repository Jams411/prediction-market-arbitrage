#!/usr/bin/env python3
"""One bounded PUBLIC metadata observation of the two sports-family exclusions.

Fetch six previously audited event pairs and four same-game spread/total
controls. Never fetch books, credentials, registry records, or execution code.
Print compact evidence only; raw responses live only in memory.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from urllib.request import urlopen

from discover_contract_pairs import _diagnostics_json, _objects

from prediction_market_arbitrage.pair_discovery import (
    ComboClassification,
    classify_polymarket_us_combo,
    diagnose_candidates,
    enrich_kalshi_markets,
    enrich_polymarket_us_markets,
)
from prediction_market_arbitrage.pair_discovery.family_policy import (
    EVIDENCE_REFERENCE,
    POLICY_ID,
    family_exclusion,
)

_TARGETS = (
    ("KXNFLGAME-26SEP13ARILAC", "nfl-ari-lac-2026-09-13"),
    ("KXNFLGAME-26SEP13ATLPIT", "nfl-atl-pit-2026-09-13"),
    ("KXNFLGAME-26SEP13BALIND", "nfl-bal-ind-2026-09-13"),
    ("KXMLBGAME-26SEP111840COLDET", "mlb-col-det-2026-09-11"),
    ("KXMLBGAME-26SEP111845LAAWSH", "mlb-laa-wsh-2026-09-11"),
    ("KXMLBGAME-26SEP111905NYMNYY", "mlb-nym-nyy-2026-09-11"),
)
_CONTROLS = (
    "KXNFLSPREAD-26SEP13ARILAC",
    "KXNFLTOTAL-26SEP13ARILAC",
    "KXMLBSPREAD-26SEP111840COLDET",
    "KXMLBTOTAL-26SEP111840COLDET",
)


def _get_event(url: str) -> dict[str, object]:
    with urlopen(url, timeout=20) as response:
        payload = json.load(response)
    event = payload.get("event")
    if not isinstance(event, dict):
        raise ValueError("public response missing event")
    return {str(k): v for k, v in event.items()}


def observe() -> dict[str, object]:
    kalshi_events: list[dict[str, object]] = []
    poly_events: list[dict[str, object]] = []
    urls: list[str] = []
    for ticker in [item[0] for item in _TARGETS] + list(_CONTROLS):
        url = (
            "https://external-api.kalshi.com/trade-api/v2/events/"
            f"{ticker}?with_nested_markets=true"
        )
        event = _get_event(url)
        if event.get("event_ticker") != ticker:
            raise ValueError("Kalshi event identity mismatch")
        urls.append(url)
        kalshi_events.append(event)
    for _, slug in _TARGETS:
        url = f"https://gateway.polymarket.us/v1/events/slug/{slug}"
        event = _get_event(url)
        if event.get("slug") != slug:
            raise ValueError("Polymarket event identity mismatch")
        urls.append(url)
        poly_events.append(event)

    # Bound computation and persisted samples, preserving moneylines and controls.
    kalshi_raw = [m for e in kalshi_events
                  for m in sorted(_objects(e.get("markets"), ctx="Kalshi children"),
                                  key=lambda m: str(m.get("ticker")))[:10]]
    poly_raw: list[dict[str, object]] = []
    for event in poly_events:
        counts: Counter[str] = Counter()
        for market in sorted(_objects(event.get("markets"), ctx="Polymarket children"),
                             key=lambda m: str(m.get("slug"))):
            family = str(market.get("marketType"))
            if counts[family] < 3 and sum(counts.values()) < 30:
                poly_raw.append(market)
                counts[family] += 1
    ke = enrich_kalshi_markets(kalshi_raw, kalshi_events)
    pe = enrich_polymarket_us_markets(poly_raw, poly_events)
    diagnostic = diagnose_candidates(ke.profiles, pe.profiles, candidate_limit=20)
    if not diagnostic.nfl_family_excluded or not diagnostic.mlb_family_excluded:
        raise RuntimeError("STOP: expected real ordinary-moneyline exclusions were not exercised")

    ordinary_ids = {str(m.get("slug")) for m in poly_raw
                    if classify_polymarket_us_combo(m) is ComboClassification.ORDINARY_CONTRACT}
    moneylines = Counter(p.family_metadata.polymarket_league for p in pe.profiles
                         if p.identifier in ordinary_ids
                         and p.family_metadata.market_type == "moneyline")
    exclusions: dict[str, list[dict[str, str]]] = defaultdict(list)
    controls: dict[str, list[dict[str, str]]] = defaultdict(list)
    for left in sorted(ke.profiles, key=lambda p: p.identifier):
        for right in sorted(pe.profiles, key=lambda p: p.identifier):
            policy = family_exclusion(left, right)
            if policy is not None and len(exclusions[policy.polymarket_league]) < 2:
                exclusions[policy.polymarket_league].append(
                    {"kalshi": left.identifier, "polymarket_us": right.identifier})
            # A surfaced control must share the audited game, sport and family.
            series = left.family_metadata.kalshi_series or ""
            expected = "spreads" if series.endswith("SPREAD") else "totals"
            if not series.endswith(("SPREAD", "TOTAL")):
                continue
            league = "nfl" if series.startswith("KXNFL") else "mlb"
            target = dict(_TARGETS).get(
                left.event_identifier.replace("SPREAD", "GAME").replace("TOTAL", "GAME")
                if left.event_identifier else "")
            if (right.event_identifier != target
                    or right.family_metadata.market_type != expected):
                continue
            check = diagnose_candidates([left], [right], candidate_limit=1)
            if check.passed and len(controls[f"{league}_{expected}"]) < 2:
                controls[f"{league}_{expected}"].append(
                    {"kalshi": left.identifier, "polymarket_us": right.identifier})
    if not controls:
        raise RuntimeError("STOP: no unrelated same-game control surfaced")
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "evidence_status": "OBSERVED",
        "policy_id": POLICY_ID,
        "prior_family_evidence": EVIDENCE_REFERENCE,
        "command": ".venv/bin/python scripts/observe_sports_family_policy.py",
        "sources": urls,
        "sampling": "fixed audited games; <=10 Kalshi children/event; <=3 Polymarket "
                    "children/marketType/event, <=30/event; no active-status restriction",
        "events_inspected": {"kalshi": len(kalshi_events), "polymarket_us": len(poly_events)},
        "nested_markets_inspected": {
            "kalshi": sum(len(_objects(e.get("markets"), ctx="children")) for e in kalshi_events),
            "polymarket_us": sum(len(_objects(e.get("markets"), ctx="children"))
                                 for e in poly_events),
        },
        "enrichment": {"kalshi": asdict(ke.stats), "polymarket_us": asdict(pe.stats)},
        "ordinary_moneylines_retained_after_combo": dict(moneylines),
        "kalshi_sample_statuses": dict(Counter(str(m.get("status")) for m in kalshi_raw)),
        "polymarket_sample_closed": dict(Counter(str(m.get("closed")) for m in poly_raw)),
        "diagnostics": {k: v for k, v in _diagnostics_json(diagnostic).items()
                        if k != "top_below_threshold_near_misses"},
        "positive_exclusion_samples": dict(exclusions),
        "unaffected_same_game_control_candidates": dict(controls),
        "candidate_rows_retained": len(diagnostic.passed_candidates),
        "remaining_candidate_samples": [
            {"kalshi": p.kalshi.identifier, "polymarket_us": p.polymarket_us.identifier,
             "kalshi_series": p.kalshi.family_metadata.kalshi_series,
             "polymarket_family": p.polymarket_us.family_metadata.market_type,
             "status": p.status} for p in diagnostic.passed_candidates[:10]
        ],
        "known_moneyline_pairings_surfaced": any(
            family_exclusion(p.kalshi, p.polymarket_us) is not None
            for p in diagnostic.passed_candidates),
        "safety": "16 public metadata GETs only; no books, authentication, credentials, "
                  "registry writes, strategy, execution, orders, production execution "
                  "or real money",
    }


if __name__ == "__main__":
    print(json.dumps(observe(), indent=2, sort_keys=True))
