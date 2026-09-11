#!/usr/bin/env python3
"""Bounded, public/read-only cross-venue contract discovery.

This command performs only unauthenticated public ``GET /markets`` and
``GET /events`` calls through the repository's market-data clients. Its output
is triage evidence, never a verified-pair registry record or execution
instruction.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import cast

from prediction_market_arbitrage.adapters.kalshi.client import KalshiClient
from prediction_market_arbitrage.adapters.polymarket_us.client import PolymarketClient
from prediction_market_arbitrage.pair_discovery import (
    CandidatePair,
    DiscoveryDiagnostics,
    EnrichmentStats,
    RejectedNearMiss,
    SemanticContract,
    diagnose_candidates,
    discover_candidates,
    enrich_kalshi_markets,
    enrich_polymarket_us_markets,
)

_JsonObject = dict[str, object]
_WARNING = "UNVERIFIED — human/primary-source verification required"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kalshi-pages", type=int, default=1)
    parser.add_argument("--polymarket-pages", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="include reconciled gate counts and bounded below-threshold near misses",
    )
    parser.add_argument("--near-misses", type=int, default=20)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.kalshi_pages <= 10 or not 1 <= args.polymarket_pages <= 10:
        raise SystemExit("page counts must be between 1 and 10")
    if not 1 <= args.page_size <= 100:
        raise SystemExit("page size must be between 1 and 100")
    if args.top <= 0:
        raise SystemExit("--top must be positive")
    if not 1 <= args.near_misses <= 100:
        raise SystemExit("--near-misses must be between 1 and 100")

    kalshi_client = KalshiClient()
    polymarket_client = PolymarketClient()
    market_limit = args.kalshi_pages * args.page_size
    kalshi_events = _kalshi_events(
        kalshi_client, args.kalshi_pages, args.page_size, market_limit
    )
    kalshi_raw = _kalshi_markets_from_events(
        kalshi_events, market_limit
    )
    polymarket_raw = _polymarket_markets(
        polymarket_client, args.polymarket_pages, args.page_size
    )
    polymarket_events = _polymarket_events(
        polymarket_client,
        args.polymarket_pages,
        args.page_size,
        {_required_identifier(item, "slug") for item in polymarket_raw},
    )
    kalshi_enrichment = enrich_kalshi_markets(kalshi_raw, kalshi_events)
    polymarket_enrichment = enrich_polymarket_us_markets(
        polymarket_raw, polymarket_events
    )
    kalshi_profiles = kalshi_enrichment.profiles
    polymarket_profiles = polymarket_enrichment.profiles
    diagnostics: DiscoveryDiagnostics | None = None
    if args.diagnose:
        diagnostics = diagnose_candidates(
            kalshi_profiles,
            polymarket_profiles,
            candidate_limit=args.top,
            near_miss_limit=args.near_misses,
        )
        candidates = diagnostics.passed_candidates
    else:
        candidates = discover_candidates(
            kalshi_profiles,
            polymarket_profiles,
            limit=args.top,
        )
    output = {
        "status": "UNVERIFIED",
        "warning": _WARNING,
        "scope": "public read-only market metadata; no authentication or execution",
        "markets_inspected": {
            "kalshi": len(kalshi_raw),
            "polymarket_us": len(polymarket_raw),
        },
        "metadata_enrichment": {
            "kalshi": {
                **_enrichment_json(kalshi_enrichment.stats),
                "structured_combo_policy": (
                    "GET /events excludes MVEs plus defensive local filter"
                ),
                "server_filtered_count": None,
            },
            "polymarket_us": {
                **_enrichment_json(polymarket_enrichment.stats),
                "structured_combo_policy": "local comboEnabled=true filter",
            },
        },
        "candidate_pairs": [_candidate_json(candidate) for candidate in candidates],
    }
    if diagnostics is not None:
        output["candidate_generation_diagnostics"] = _diagnostics_json(diagnostics)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _polymarket_markets(
    client: PolymarketClient, pages: int, page_size: int
) -> list[_JsonObject]:
    markets: list[_JsonObject] = []
    for page in range(pages):
        payload = client.list_markets(
            active=True,
            closed=False,
            archived=False,
            limit=page_size,
            offset=page * page_size,
        )
        batch = _objects(payload.get("markets"), ctx="Polymarket US markets")
        markets.extend(batch)
        if len(batch) < page_size:
            break
    return markets


def _kalshi_events(
    client: KalshiClient, pages: int, page_size: int, market_limit: int
) -> list[_JsonObject]:
    events: list[_JsonObject] = []
    cursor: str | None = None
    for _ in range(pages):
        payload = client.list_events(
            status="open",
            with_nested_markets=True,
            limit=page_size,
            cursor=cursor,
        )
        batch = _objects(payload.get("events"), ctx="Kalshi events")
        events.extend(batch)
        active_markets = sum(
            child.get("status") == "active"
            for event in events
            for child in _objects(event.get("markets"), ctx="Kalshi event markets")
        )
        if active_markets >= market_limit:
            break
        raw_cursor = payload.get("cursor")
        cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
        if cursor is None:
            break
    return events


def _kalshi_markets_from_events(
    events: list[_JsonObject], market_limit: int
) -> list[_JsonObject]:
    markets: list[_JsonObject] = []
    for event_index, event in enumerate(events):
        children = _objects(
            event.get("markets"), ctx=f"Kalshi events[{event_index}].markets"
        )
        for market in children:
            if market.get("status") == "active":
                markets.append(market)
                if len(markets) == market_limit:
                    return markets
    return markets


def _polymarket_events(
    client: PolymarketClient,
    pages: int,
    page_size: int,
    target_market_slugs: set[str],
) -> list[_JsonObject]:
    events: list[_JsonObject] = []
    found_slugs: set[str] = set()
    for page in range(pages):
        payload = client.list_events(
            active=True,
            closed=False,
            archived=False,
            limit=page_size,
            offset=page * page_size,
        )
        batch = _objects(payload.get("events"), ctx="Polymarket US events")
        events.extend(batch)
        found_slugs.update(
            _required_identifier(child, "slug")
            for event in batch
            for child in _objects(
                event.get("markets"), ctx="Polymarket US event markets"
            )
        )
        if target_market_slugs <= found_slugs:
            break
        if len(batch) < page_size:
            break
    return events


def _objects(value: object, *, ctx: str) -> list[_JsonObject]:
    if not isinstance(value, list):
        raise ValueError(f"{ctx}: response is missing the markets list")
    objects: list[_JsonObject] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"{ctx}[{index}]: expected an object")
        objects.append(cast("_JsonObject", dict(item)))
    return objects


def _required_identifier(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"market field {key!r} must be a non-empty string")
    return value


def _candidate_json(candidate: CandidatePair) -> dict[str, object]:
    return {
        "status": candidate.status,
        "warning": candidate.warning,
        "verification_priority": candidate.verification_priority,
        "lexical_generation_signal": str(candidate.lexical_signal),
        "kalshi": {
            "identifier": candidate.kalshi.identifier,
            "title": candidate.kalshi.title,
            "rule_sources": candidate.kalshi.rule_sources,
            "authoritative_context": _contract_context(candidate.kalshi),
        },
        "polymarket_us": {
            "identifier": candidate.polymarket_us.identifier,
            "title": candidate.polymarket_us.title,
            "rule_sources": candidate.polymarket_us.rule_sources,
            "authoritative_context": _contract_context(candidate.polymarket_us),
        },
        "semantic_comparison": {
            comparison.field: {
                "classification": comparison.classification.value,
                "kalshi": comparison.kalshi_value,
                "polymarket_us": comparison.polymarket_us_value,
                "reason": comparison.reason,
            }
            for comparison in candidate.comparisons
        },
        "review_blockers": [
            f"{comparison.field}: {comparison.classification.value} — {comparison.reason}"
            for comparison in candidate.comparisons
            if comparison.classification.value in {"MISMATCH", "UNKNOWN"}
        ],
    }


def _diagnostics_json(diagnostics: DiscoveryDiagnostics) -> dict[str, object]:
    return {
        "status": diagnostics.status,
        "warning": diagnostics.warning,
        "threshold": str(diagnostics.threshold),
        "prefilter": "none; every Kalshi × Polymarket US record is considered",
        "comparisons_considered": diagnostics.considered,
        "passed_threshold": diagnostics.passed,
        "rejected_below_threshold": diagnostics.rejected,
        "counts_reconcile": diagnostics.passed + diagnostics.rejected
        == diagnostics.considered,
        "top_below_threshold_near_misses": [
            _near_miss_json(item) for item in diagnostics.near_misses
        ],
    }


def _near_miss_json(item: RejectedNearMiss) -> dict[str, object]:
    return {
        "status": item.status,
        "warning": item.warning,
        "lexical_generation_signal": str(item.lexical_signal),
        "rejection_reason": item.rejection_reason,
        "kalshi": _diagnostic_leg(item.kalshi, item.kalshi_keys.all_tokens),
        "polymarket_us": _diagnostic_leg(
            item.polymarket_us, item.polymarket_us_keys.all_tokens
        ),
        "shared_tokens": item.shared_tokens,
        "kalshi_unique_tokens": item.kalshi_unique_tokens,
        "polymarket_us_unique_tokens": item.polymarket_us_unique_tokens,
        "coarse_signals": {
            signal.field: {
                "classification": signal.classification.value,
                "kalshi": signal.kalshi_value,
                "polymarket_us": signal.polymarket_us_value,
            }
            for signal in item.coarse_signals
        },
        "missing_metadata_fields": item.missing_metadata_fields,
    }


def _diagnostic_leg(contract: SemanticContract, tokens: tuple[str, ...]) -> dict[str, object]:
    return {
        "identifier": contract.identifier,
        "title": contract.title,
        "normalized_matching_tokens": tokens,
        "authoritative_context": _contract_context(contract),
    }


def _contract_context(contract: SemanticContract) -> dict[str, object]:
    return {
        "event_identifier": contract.event_identifier,
        "event_title": contract.underlying_event,
        "category": contract.category,
        "series_or_league": contract.series_or_league,
        "event_time": contract.event_time_window.isoformat()
        if contract.event_time_window
        else None,
        "participant": contract.participant_outcome,
        "participant_identifiers": contract.participant_identifiers,
        "market_type": contract.market_type,
        "resolution_sources": contract.resolution_sources,
    }


def _enrichment_json(stats: EnrichmentStats) -> dict[str, object]:
    names = (
        "markets_input",
        "profiles_output",
        "parent_event_records_fetched",
        "parent_events_used",
        "parent_cache_reuses",
        "combo_markets_filtered",
        "combo_metadata_unknown",
        "missing_parent_metadata",
        "ambiguous_parent_metadata",
    )
    return {name: getattr(stats, name) for name in names}


if __name__ == "__main__":
    raise SystemExit(main())
