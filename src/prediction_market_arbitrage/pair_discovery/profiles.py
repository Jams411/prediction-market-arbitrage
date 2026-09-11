"""Conservative semantic profiles from public venue market metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import SemanticContract

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)")


def from_kalshi_market(market: Mapping[str, object]) -> SemanticContract:
    """Build an unverified profile from one Kalshi ``GET /markets`` item."""
    ticker = _required_text(market, "ticker")
    title = _required_text(market, "title")
    primary = _text(market.get("rules_primary"))
    secondary = _text(market.get("rules_secondary"))
    rules = " ".join(value for value in (primary, secondary) if value)
    participant = _text(market.get("yes_sub_title"))
    strike_type = _text(market.get("strike_type"))
    threshold, inclusivity = _kalshi_threshold(market, strike_type)

    return SemanticContract(
        venue="kalshi",
        identifier=ticker,
        title=title,
        rule_sources=(_kalshi_source(ticker),),
        underlying_event=_text(market.get("event_ticker")),
        binary_proposition=primary or title,
        participant_outcome=participant,
        threshold=threshold,
        threshold_inclusivity=inclusivity,
        measurement_unit=_measurement_unit(rules),
        event_time_window=_timestamp(market.get("occurrence_datetime")),
        close_conditions=_text(market.get("early_close_condition")) or secondary,
        resolution_source=_rule_sentence(rules, ("according to", "verified from", "source")),
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


def from_polymarket_us_market(market: Mapping[str, object]) -> SemanticContract:
    """Build an unverified profile from one Polymarket US ``GET /markets`` item."""
    slug = _required_text(market, "slug")
    question = _required_text(market, "question")
    title = _text(market.get("title")) or question
    description = _text(market.get("description"))
    description_text = description or ""
    threshold, inclusivity = _text_threshold(f"{question} {description_text}")
    yes, no = _polymarket_sides(market.get("marketSides"))

    return SemanticContract(
        venue="polymarket_us",
        identifier=slug,
        title=title,
        rule_sources=(_polymarket_source(slug),),
        underlying_event=question,
        binary_proposition=_first_sentence(description) or question,
        participant_outcome=title,
        threshold=threshold,
        threshold_inclusivity=inclusivity,
        measurement_unit=_measurement_unit(f"{question} {description_text}"),
        event_time_window=_timestamp(market.get("gameStartTime")),
        close_conditions=_rule_sentence(description_text, ("close", "expire", "end")),
        resolution_source=_rule_sentence(
            description_text, ("outcome sourced", "resolve based", "resolution source")
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
