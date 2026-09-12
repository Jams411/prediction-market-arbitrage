"""Conservative semantic profiles from public venue market metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import FamilyMetadata, SemanticContract

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)")


def from_kalshi_market(
    market: Mapping[str, object], event: Mapping[str, object] | None = None
) -> SemanticContract:
    """Build an unverified profile from one Kalshi ``GET /markets`` item."""
    ticker = _required_text(market, "ticker")
    title = _required_text(market, "title")
    primary = _text(market.get("rules_primary"))
    secondary = _text(market.get("rules_secondary"))
    rules = " ".join(value for value in (primary, secondary) if value)
    participant = _text(market.get("yes_sub_title"))
    strike_type = _text(market.get("strike_type"))
    threshold, inclusivity = _kalshi_threshold(market, strike_type)
    event = event or {}
    event_identifier = _text(market.get("event_ticker"))
    resolution_sources = _settlement_sources(event.get("settlement_sources"))

    return SemanticContract(
        venue="kalshi",
        family_metadata=FamilyMetadata(kalshi_series=_text(event.get("series_ticker"))),
        identifier=ticker,
        title=title,
        rule_sources=(
            (_kalshi_source(ticker), _kalshi_event_source(event_identifier))
            if event_identifier and event
            else (_kalshi_source(ticker),)
        ),
        event_identifier=event_identifier,
        category=_text(event.get("category")) or _text(market.get("category")),
        series_or_league=_kalshi_series_or_league(event),
        underlying_event=_text(event.get("title")) or event_identifier,
        binary_proposition=primary or title,
        participant_outcome=participant,
        participant_identifiers=_kalshi_participant_identifiers(market),
        market_type=_text(market.get("market_type")),
        resolution_sources=resolution_sources,
        threshold=threshold,
        threshold_inclusivity=inclusivity,
        measurement_unit=_measurement_unit(rules),
        event_time_window=_timestamp(market.get("occurrence_datetime")),
        close_conditions=_text(market.get("early_close_condition")) or secondary,
        resolution_source=(
            resolution_sources[0]
            if resolution_sources
            else _rule_sentence(rules, ("according to", "verified from", "source"))
        ),
        cancellation_postponement=_rule_sentence(
            rules, ("cancel", "postpon", "reschedul", "abandon")
        ),
        multiple_winner_treatment=_rule_sentence(
            rules, ("multiple winner", "multiple champion", "co-winner", "tie")
        ),
        void_refund_fair_market=_rule_sentence(
            rules, ("void", "refund", "fair market", "50-50", "50/50")
        ),
        settlement_backstop=_timestamp(
            market.get("expiration_time") or market.get("latest_expiration_time")
        ),
        yes_no_mapping=_mapping(participant, _text(market.get("no_sub_title"))),
    )


def from_polymarket_us_market(
    market: Mapping[str, object], event: Mapping[str, object] | None = None
) -> SemanticContract:
    """Build an unverified profile from one Polymarket US ``GET /markets`` item."""
    slug = _required_text(market, "slug")
    question = _required_text(market, "question")
    title = _text(market.get("title")) or question
    description = _text(market.get("description"))
    description_text = description or ""
    threshold, inclusivity = _text_threshold(f"{question} {description_text}")
    yes, no = _polymarket_sides(market.get("marketSides"))
    event = event or {}
    event_identifier = _event_identifier(event)
    structured_participant = _polymarket_participant(market)
    resolution_sources = _polymarket_resolution_sources(event)

    return SemanticContract(
        venue="polymarket_us",
        family_metadata=FamilyMetadata(
            polymarket_league=_policy_league(event, market),
            market_type=_text(market.get("marketType")),
            sports_market_type=_text(market.get("sportsMarketType")),
            sports_market_type_v2=_text(market.get("sportsMarketTypeV2")),
        ),
        identifier=slug,
        title=title,
        rule_sources=(
            (_polymarket_source(slug), _polymarket_event_source(event_identifier))
            if event_identifier
            else (_polymarket_source(slug),)
        ),
        event_identifier=event_identifier,
        category=_text(event.get("category")) or _text(market.get("category")),
        series_or_league=_polymarket_series_or_league(event, market),
        underlying_event=_text(event.get("title")) or question,
        binary_proposition=_first_sentence(description) or question,
        participant_outcome=structured_participant or title,
        participant_identifiers=_polymarket_participant_identifiers(market),
        market_type=(
            _text(market.get("sportsMarketTypeV2"))
            or _text(market.get("sportsMarketType"))
            or _text(market.get("marketType"))
        ),
        resolution_sources=resolution_sources,
        threshold=threshold,
        threshold_inclusivity=inclusivity,
        measurement_unit=_measurement_unit(f"{question} {description_text}"),
        event_time_window=_timestamp(
            event.get("startTime")
            or event.get("startDate")
            or market.get("gameStartTime")
        ),
        close_conditions=_rule_sentence(description_text, ("close", "expire", "end")),
        resolution_source=(
            resolution_sources[0]
            if resolution_sources
            else _rule_sentence(
                description_text, ("outcome sourced", "resolve based", "resolution source")
            )
        ),
        cancellation_postponement=_rule_sentence(
            description_text, ("cancel", "postpon", "reschedul", "abandon")
        ),
        multiple_winner_treatment=_rule_sentence(
            description_text, ("multiple winner", "multiple champion", "co-winner", "tie")
        ),
        void_refund_fair_market=_rule_sentence(
            description_text, ("void", "refund", "fair market", "50-50", "50/50")
        ),
        settlement_backstop=_timestamp(market.get("endDate")),
        yes_no_mapping=_mapping(yes, no),
    )


def _kalshi_threshold(
    market: Mapping[str, object], strike_type: str | None
) -> tuple[Decimal | None, str | None]:
    if strike_type == "greater":
        return _decimal(market.get("floor_strike")), ">"
    if strike_type == "less":
        return _decimal(market.get("cap_strike")), "<"
    if strike_type in {"greater_or_equal", "at_least"}:
        return _decimal(market.get("floor_strike")), ">="
    if strike_type in {"less_or_equal", "at_most"}:
        return _decimal(market.get("cap_strike")), "<="
    return None, None


def _text_threshold(text: str) -> tuple[Decimal | None, str | None]:
    lowered = text.casefold()
    phrases = (
        ("at or above", ">="),
        ("at least", ">="),
        ("greater than or equal", ">="),
        ("at or below", "<="),
        ("at most", "<="),
        ("less than or equal", "<="),
        ("above", ">"),
        ("greater than", ">"),
        ("below", "<"),
        ("less than", "<"),
    )
    for phrase, operator in phrases:
        start = lowered.find(phrase)
        if start < 0:
            continue
        match = _NUMBER.search(lowered, start + len(phrase))
        if match is not None:
            return Decimal(match.group(1)), operator
    return None, None


def _measurement_unit(text: str) -> str | None:
    lowered = text.casefold()
    for needles, unit in (
        (("fahrenheit", "°f"), "fahrenheit"),
        (("celsius", "°c"), "celsius"),
        (("percent", "%"), "percent"),
        (("basis point", "bps"), "basis_points"),
        (("seat",), "seats"),
        (("goal",), "goals"),
        (("point",), "points"),
        (("usd", "dollar", "$"), "usd"),
    ):
        if any(needle in lowered for needle in needles):
            return unit
    return None


def _rule_sentence(text: str, needles: tuple[str, ...]) -> str | None:
    for sentence in _SENTENCE.split(text):
        if any(needle in sentence.casefold() for needle in needles):
            return sentence.strip()
    return None


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    return _SENTENCE.split(text, maxsplit=1)[0].strip()


def _polymarket_sides(raw: object) -> tuple[str | None, str | None]:
    if not isinstance(raw, list):
        return None, None
    yes: str | None = None
    no: str | None = None
    for item in raw:
        if not isinstance(item, dict):
            continue
        description = _text(item.get("description"))
        long = item.get("long")
        if long is True:
            yes = description
        elif long is False:
            no = description
    return yes, no


def _event_identifier(event: Mapping[str, object]) -> str | None:
    for key in ("slug", "ticker", "id"):
        value = event.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    return None


def _kalshi_series_or_league(event: Mapping[str, object]) -> str | None:
    product = event.get("product_metadata")
    if isinstance(product, Mapping):
        competition = _text(product.get("competition"))
        if competition:
            return competition
    return _text(event.get("series_ticker"))


def _polymarket_series_or_league(
    event: Mapping[str, object], market: Mapping[str, object]
) -> str | None:
    tags = event.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, Mapping):
                continue
            league = tag.get("league")
            if isinstance(league, Mapping):
                name = _text(league.get("name")) or _text(league.get("slug"))
                if name:
                    return name
    for side in _mapping_items(market.get("marketSides")):
        team = side.get("team")
        if isinstance(team, Mapping):
            league = _text(team.get("league"))
            if league:
                return league
    return _text(event.get("seriesSlug"))


def _settlement_sources(raw: object) -> tuple[str, ...]:
    sources: set[str] = set()
    for item in _mapping_items(raw):
        url = _text(item.get("url"))
        name = _text(item.get("name"))
        if url:
            sources.add(url)
        elif name:
            sources.add(name)
    return tuple(sorted(sources))


def _polymarket_resolution_sources(event: Mapping[str, object]) -> tuple[str, ...]:
    sources: set[str] = set()
    tags = event.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, Mapping):
                continue
            league = tag.get("league")
            if isinstance(league, Mapping):
                resolution = _text(league.get("resolution"))
                if resolution:
                    sources.add(resolution)
    return tuple(sorted(sources))


def _kalshi_participant_identifiers(market: Mapping[str, object]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    primary = _text(market.get("primary_participant_key"))
    if primary:
        identifiers.add(f"primary:{primary}")
    custom = market.get("custom_strike")
    if isinstance(custom, Mapping):
        for key, value in custom.items():
            participant_words = (
                "participant",
                "team",
                "competitor",
                "player",
                "candidate",
            )
            if not any(word in str(key).casefold() for word in participant_words):
                continue
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                identifiers.add(f"{key}:{value}")
    return tuple(sorted(identifiers))


def _polymarket_participant(market: Mapping[str, object]) -> str | None:
    for side in _mapping_items(market.get("marketSides")):
        if side.get("long") is not True:
            continue
        team = side.get("team")
        if isinstance(team, Mapping):
            return _text(team.get("name")) or _text(team.get("alias"))
    return None


def _polymarket_participant_identifiers(market: Mapping[str, object]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    for side in _mapping_items(market.get("marketSides")):
        team_id = side.get("teamId")
        if isinstance(team_id, (str, int)) and not isinstance(team_id, bool):
            identifiers.add(f"team:{team_id}")
        team = side.get("team")
        if not isinstance(team, Mapping):
            continue
        for provider in _mapping_items(team.get("providerIds")):
            name = _text(provider.get("provider"))
            identifier = provider.get("providerId") or provider.get("id")
            if name and isinstance(identifier, (str, int)) and not isinstance(identifier, bool):
                identifiers.add(f"provider:{name}:{identifier}")
    return tuple(sorted(identifiers))


def _mapping_items(raw: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _mapping(yes: str | None, no: str | None) -> str | None:
    if yes is None or no is None:
        return None
    return f"YES={yes}; NO={no}"


def _required_text(market: Mapping[str, object], key: str) -> str:
    value = _text(market.get(key))
    if value is None:
        raise ValueError(f"market field {key!r} must be a non-empty string")
    return value


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _timestamp(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _kalshi_source(ticker: str) -> str:
    return f"kalshi:market:{ticker}"


def _polymarket_source(slug: str) -> str:
    return f"polymarket_us:market:{slug}"


def _kalshi_event_source(event_identifier: str) -> str:
    return f"kalshi:event:{event_identifier}"


def _polymarket_event_source(event_identifier: str) -> str:
    return f"polymarket_us:event:{event_identifier}"


def _policy_league(
    event: Mapping[str, object], market: Mapping[str, object]
) -> str | None:
    """Require unambiguous top-level parent league; never infer from tag text.

    Nested subtags are navigation context (e.g. MLB's Baseball tag also lists
    KBO), not event membership. Team league values, when supplied, must agree.
    """
    leagues: set[str] = set()
    for tag in _mapping_items(event.get("tags")):
        league = tag.get("league")
        if league is None:
            continue
        if not isinstance(league, Mapping):
            return None
        name = _text(league.get("name"))
        slug = _text(league.get("slug"))
        if name is None or slug is None or name.casefold() != slug.casefold():
            return None
        leagues.add(slug.casefold())
    if len(leagues) != 1:
        return None
    selected = next(iter(leagues))
    for side in _mapping_items(market.get("marketSides")):
        team = side.get("team")
        if isinstance(team, Mapping) and "league" in team:
            value = _text(team.get("league"))
            if value is None or value.casefold() != selected:
                return None
    return selected
