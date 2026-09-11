#!/usr/bin/env python3
"""Bounded, public/read-only cross-venue contract discovery.

This command performs only unauthenticated ``GET /markets`` calls through the
repository's public market-data clients.  Its output is triage evidence, never
a verified-pair registry record and never an execution instruction.
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
    RejectedNearMiss,
    SemanticContract,
    diagnose_candidates,
    discover_candidates,
    from_kalshi_market,
    from_polymarket_us_market,
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

    kalshi_raw = _kalshi_markets(KalshiClient(), args.kalshi_pages, args.page_size)
    polymarket_raw = _polymarket_markets(
        PolymarketClient(), args.polymarket_pages, args.page_size
    )
    kalshi_profiles = tuple(from_kalshi_market(item) for item in kalshi_raw)
    polymarket_profiles = tuple(from_polymarket_us_market(item) for item in polymarket_raw)
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
        "candidate_pairs": [_candidate_json(candidate) for candidate in candidates],
    }
    if diagnostics is not None:
        output["candidate_generation_diagnostics"] = _diagnostics_json(diagnostics)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _kalshi_markets(client: KalshiClient, pages: int, page_size: int) -> list[_JsonObject]:
    markets: list[_JsonObject] = []
    cursor: str | None = None
    for _ in range(pages):
        payload = client.list_markets(status="open", limit=page_size, cursor=cursor)
        markets.extend(_objects(payload.get("markets"), ctx="Kalshi markets"))
        raw_cursor = payload.get("cursor")
        cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
        if cursor is None:
            break
    return markets


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


def _objects(value: object, *, ctx: str) -> list[_JsonObject]:
    if not isinstance(value, list):
        raise ValueError(f"{ctx}: response is missing the markets list")
    objects: list[_JsonObject] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"{ctx}[{index}]: expected an object")
        objects.append(cast("_JsonObject", dict(item)))
    return objects


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
        },
        "polymarket_us": {
            "identifier": candidate.polymarket_us.identifier,
            "title": candidate.polymarket_us.title,
            "rule_sources": candidate.polymarket_us.rule_sources,
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
    }


if __name__ == "__main__":
    raise SystemExit(main())
