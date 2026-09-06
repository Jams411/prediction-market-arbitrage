"""Decode Polymarket US Markets-WebSocket ``MARKET_DATA`` frames into updates.

Evidence: ``docs.polymarket.us/api-reference/websocket/markets`` (see
``docs/API_SOURCES.md`` P-WS-01..P-WS-04). A ``SUBSCRIPTION_TYPE_MARKET_DATA``
message carries a **complete** ``marketData`` object every time — the same
schema as the REST ``/v1/markets/{slug}/book`` payload (``API_SOURCES.md``
P-06/P-07): ``bids[]`` + ``offers[]`` of ``{px:{value,currency}, qty}``, plus
``state`` and ``transactTime``. There is **no sequence number** and no delta
message on this channel, so every frame is a full :class:`BookSnapshot` that
replaces prior state.

Frame shape (verbatim from the docs example)::

    {"requestId":"md-sub-1","subscriptionType":"SUBSCRIPTION_TYPE_MARKET_DATA",
     "marketData":{"marketSlug":"market-slug-1",
        "bids":[{"px":{"value":"0.555","currency":"USD"},"qty":"0.50"}],
        "offers":[{"px":{"value":"0.560","currency":"USD"},"qty":"0.80"}],
        "state":"MARKET_STATE_OPEN",
        "transactTime":"2024-01-15T10:30:00Z"}}

The book is attributed to the ``:LONG`` contract, consistent with the REST
adapter (A-013 — an UNVERIFIED interpretation; not for live use).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from prediction_market_arbitrage.domain import DomainValidationError, PriceLevel, to_decimal

from .errors import LiveBookError
from .updates import BookSnapshot

POLYMARKET_US_VENUE_ID = "polymarket_us"
_MARKET_DATA_TYPE = "SUBSCRIPTION_TYPE_MARKET_DATA"


def decode_market_data(frame: Mapping[str, object]) -> BookSnapshot:
    """Decode one ``SUBSCRIPTION_TYPE_MARKET_DATA`` frame into a full snapshot
    for the market's ``:LONG`` contract."""
    subscription_type = frame.get("subscriptionType")
    if subscription_type != _MARKET_DATA_TYPE:
        raise LiveBookError(
            f"expected subscriptionType {_MARKET_DATA_TYPE!r}, got {subscription_type!r}"
        )
    market_data = frame.get("marketData")
    if not isinstance(market_data, Mapping):
        raise LiveBookError("'marketData': expected an object")

    slug = _require_str(market_data, "marketSlug")
    bids = _levels(market_data, "bids")
    asks = _levels(market_data, "offers")
    source_time = _optional_timestamp(market_data.get("transactTime"))
    raw_state = market_data.get("state")
    if raw_state is not None and not isinstance(raw_state, str):
        raise LiveBookError("'state': expected a string or absent")

    return BookSnapshot(
        venue=POLYMARKET_US_VENUE_ID,
        contract_id=f"{slug}:LONG",
        bids=bids,
        asks=asks,
        sequence=None,
        source_time=source_time,
        market_state=raw_state,
    )


# --------------------------------------------------------------------------- #
# Field extraction (mirrors adapters/polymarket_us/normalize)
# --------------------------------------------------------------------------- #


def _levels(market_data: Mapping[str, object], key: str) -> tuple[PriceLevel, ...]:
    raw = market_data.get(key)
    if not isinstance(raw, list):
        raise LiveBookError(f"{key!r}: expected a list of book entries")
    out: list[PriceLevel] = []
    for index, element in enumerate(raw):
        if not isinstance(element, Mapping):
            raise LiveBookError(f"{key}[{index}]: expected an object")
        px = element.get("px")
        if not isinstance(px, Mapping):
            raise LiveBookError(f"{key}[{index}].px: expected an object")
        value = px.get("value")
        currency = px.get("currency")
        qty = element.get("qty")
        if not isinstance(value, str):
            raise LiveBookError(f"{key}[{index}].px.value: expected a string")
        if currency != "USD":
            raise LiveBookError(f"{key}[{index}].px.currency: expected 'USD', got {currency!r}")
        if not isinstance(qty, str):
            raise LiveBookError(f"{key}[{index}].qty: expected a string")
        try:
            out.append(
                PriceLevel(
                    price=to_decimal(value, field=f"{key}[{index}].px.value"),
                    quantity=to_decimal(qty, field=f"{key}[{index}].qty"),
                )
            )
        except DomainValidationError as exc:
            raise LiveBookError(f"{key}[{index}]: {exc}") from exc
    return tuple(out)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LiveBookError(f"{key!r}: expected a non-empty string")
    return value


def _optional_timestamp(raw: object) -> datetime | None:
    """Parse an RFC-3339 UTC ``transactTime``; nanosecond precision is truncated
    to microseconds (P-09). Absent -> ``None``."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise LiveBookError("'transactTime': expected a non-empty string or absent")
    text = raw
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, _, tail = text.partition(".")
        frac = ""
        offset = ""
        for char in tail:
            if char.isdigit():
                frac += char
            else:
                offset = tail[len(frac):]
                break
        text = f"{head}.{frac[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise LiveBookError(f"'transactTime': malformed timestamp {raw!r}") from exc
    if parsed.tzinfo is None:
        raise LiveBookError(f"'transactTime': {raw!r} has no timezone offset")
    return parsed
