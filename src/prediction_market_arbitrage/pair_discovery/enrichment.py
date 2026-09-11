"""Bounded parent-event enrichment for unverified contract discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import ComboClassification, EnrichmentResult, EnrichmentStats, SemanticContract
from .profiles import from_kalshi_market, from_polymarket_us_market


def enrich_kalshi_markets(
    markets: Iterable[Mapping[str, object]],
    events: Iterable[Mapping[str, object]],
) -> EnrichmentResult:
    """Join Kalshi markets to one in-run event index and filter structured MVEs."""
    market_items = tuple(markets)
    event_items = tuple(events)
    event_index, ambiguous = _index_events(event_items, ("event_ticker",))
    profiles: list[SemanticContract] = []
    parents_used: set[str] = set()
    combo_filtered = 0
    missing = 0
    ambiguous_count = 0

    for market in market_items:
        if _kalshi_is_multivariate(market):
            combo_filtered += 1
            continue
        parent_id = _text(market.get("event_ticker"))
        parent = event_index.get(parent_id) if parent_id else None
        if parent_id in ambiguous:
            parent = None
            ambiguous_count += 1
        elif parent is None:
            missing += 1
        elif parent_id is not None:
            parents_used.add(parent_id)
        profiles.append(from_kalshi_market(market, parent))

    return _result(
        market_items,
        event_items,
        profiles,
        parents_used,
        len(profiles),
        combo_filtered,
        0,
        missing,
        ambiguous_count,
    )


def enrich_polymarket_us_markets(
    markets: Iterable[Mapping[str, object]],
    events: Iterable[Mapping[str, object]],
) -> EnrichmentResult:
    """Join Polymarket US markets through nested event children and filter combos."""
    market_items = tuple(markets)
    event_items = tuple(events)
    child_index: dict[str, Mapping[str, object]] = {}
    child_parent: dict[str, str] = {}
    ambiguous: set[str] = set()
    for event in event_items:
        parent_id = _first_identifier(event, ("slug", "ticker", "id"))
        children = event.get("markets")
        if parent_id is None or not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, Mapping):
                continue
            slug = _text(child.get("slug"))
            if slug is None:
                continue
            previous = child_parent.get(slug)
            if previous is not None and previous != parent_id:
                ambiguous.add(slug)
                child_index.pop(slug, None)
                continue
            child_parent[slug] = parent_id
            child_index[slug] = event

    profiles: list[SemanticContract] = []
    parents_used: set[str] = set()
    ordinary_retained = 0
    combo_filtered = 0
    combo_unknown = 0
    missing = 0
    ambiguous_count = 0
    for market in market_items:
        combo_classification = classify_polymarket_us_combo(market)
        if combo_classification is ComboClassification.CONFIRMED_COMBO:
            combo_filtered += 1
            continue
        if combo_classification is ComboClassification.UNKNOWN:
            combo_unknown += 1
        else:
            ordinary_retained += 1
        slug = _text(market.get("slug"))
        parent = child_index.get(slug) if slug else None
        if slug in ambiguous:
            parent = None
            ambiguous_count += 1
        elif parent is None:
            missing += 1
        elif slug is not None:
            parent_id = child_parent[slug]
            parents_used.add(parent_id)
        profiles.append(from_polymarket_us_market(market, parent))

    return _result(
        market_items,
        event_items,
        profiles,
        parents_used,
        ordinary_retained,
        combo_filtered,
        combo_unknown,
        missing,
        ambiguous_count,
    )


def _result(
    markets: tuple[Mapping[str, object], ...],
    events: tuple[Mapping[str, object], ...],
    profiles: list[SemanticContract],
    parents_used: set[str],
    ordinary_retained: int,
    combo_filtered: int,
    combo_unknown: int,
    missing: int,
    ambiguous: int,
) -> EnrichmentResult:
    enriched_children = len(profiles) - missing - ambiguous
    return EnrichmentResult(
        profiles=tuple(profiles),
        stats=EnrichmentStats(
            markets_input=len(markets),
            profiles_output=len(profiles),
            parent_event_records_fetched=len(events),
            parent_events_used=len(parents_used),
            parent_cache_reuses=max(0, enriched_children - len(parents_used)),
            ordinary_markets_retained=ordinary_retained,
            combo_markets_filtered=combo_filtered,
            combo_metadata_unknown=combo_unknown,
            missing_parent_metadata=missing,
            ambiguous_parent_metadata=ambiguous,
        ),
    )


def _index_events(
    events: tuple[Mapping[str, object], ...], keys: tuple[str, ...]
) -> tuple[dict[str, Mapping[str, object]], set[str]]:
    index: dict[str, Mapping[str, object]] = {}
    ambiguous: set[str] = set()
    for event in events:
        identifier = _first_identifier(event, keys)
        if identifier is None:
            continue
        previous = index.get(identifier)
        if previous is not None and previous != event:
            ambiguous.add(identifier)
            index.pop(identifier, None)
        elif identifier not in ambiguous:
            index[identifier] = event
    return index, ambiguous


def _kalshi_is_multivariate(market: Mapping[str, object]) -> bool:
    if _text(market.get("mve_collection_ticker")) is not None:
        return True
    legs = market.get("mve_selected_legs")
    return isinstance(legs, list) and bool(legs)


def classify_polymarket_us_combo(
    market: Mapping[str, object],
) -> ComboClassification:
    """Classify whether a record is itself a Polymarket US combo instrument.

    ``comboEnabled`` is a base-market capability flag, not contract identity.
    Official combo records use a ``caoc-`` identifier and contain 2--10 legs.
    Partial or malformed combo structure remains unknown and is not excluded.
    """
    identifier = _first_identifier(market, ("slug", "id"))
    legs = market.get("legs")
    combo_identifier = identifier is not None and identifier.casefold().startswith("caoc-")
    valid_legs = (
        isinstance(legs, list)
        and 2 <= len(legs) <= 10
        and all(_valid_combo_leg(leg) for leg in legs)
    )
    if combo_identifier and valid_legs:
        return ComboClassification.CONFIRMED_COMBO
    if combo_identifier or "legs" in market:
        return ComboClassification.UNKNOWN
    if isinstance(market.get("comboEnabled"), bool):
        return ComboClassification.ORDINARY_CONTRACT
    return ComboClassification.UNKNOWN


def _valid_combo_leg(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    symbol = _text(value.get("symbol"))
    side = _text(value.get("side"))
    return symbol is not None and side in {"SIDE_BUY", "SIDE_SELL"}


def _first_identifier(event: Mapping[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = event.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
