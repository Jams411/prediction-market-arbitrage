"""Decode Kalshi ``orderbook_delta`` channel frames into venue-neutral updates.

Evidence: ``docs.kalshi.com/websockets/orderbook-updates`` AsyncAPI (see
``docs/API_SOURCES.md`` K-WS-01..K-WS-05). The channel sends one
``orderbook_snapshot`` then incremental ``orderbook_delta`` messages, each
carrying a per-subscription ``seq`` counter.

Frame shapes (verbatim from the AsyncAPI examples)::

    {"type":"orderbook_snapshot","sid":2,"seq":2,"msg":{
        "market_ticker":"FED-23DEC-T3.00","market_id":"<uuid>",
        "yes_dollars_fp":[["0.0800","300.00"],["0.2200","333.00"]],   # optional
        "no_dollars_fp":[["0.5400","20.00"],["0.5600","146.00"]]}}    # optional

    {"type":"orderbook_delta","sid":2,"seq":3,"msg":{
        "market_ticker":"FED-23DEC-T3.00","market_id":"<uuid>",
        "price_dollars":"0.960","delta_fp":"-54.00","side":"yes","ts_ms":1669149841000}}

The level shape ``[price_dollars, contract_count_fp]`` (both strings) and the
bids-only-per-side YES/NO semantics are the **same** as the REST
``orderbook_fp`` payload (``API_SOURCES.md`` K-06/K-07/K-08). A YES bid at price
``X`` is a NO ask at ``1 - X`` of the same size, so each frame decodes to a pair
of updates — one for the YES contract, one for the NO contract.

Delta semantics — ``delta_fp`` is applied **additively** to the aggregated
contract count already at that ``(side, price_dollars)`` level (A-028): the
channel description ("incremental updates to maintain a live orderbook") and the
signed fixed-point value support no other reading, but it is not spelled out and
is not yet OBSERVED against a real feed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from prediction_market_arbitrage.domain import DomainValidationError, PriceLevel, to_decimal

from .errors import LiveBookError
from .updates import BookDelta, BookSnapshot

KALSHI_VENUE_ID = "kalshi"
_ONE = Decimal(1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_SNAPSHOT_TYPE = "orderbook_snapshot"
_DELTA_TYPE = "orderbook_delta"


def decode_orderbook_snapshot(frame: Mapping[str, object]) -> tuple[BookSnapshot, BookSnapshot]:
    """Decode one ``orderbook_snapshot`` frame into ``(yes_snapshot, no_snapshot)``."""
    _require_type(frame, _SNAPSHOT_TYPE)
    seq = _require_int(frame, "seq")
    msg = _require_mapping(frame, "msg")
    ticker = _require_str(msg, "market_ticker")

    yes_levels = _levels(msg.get("yes_dollars_fp"), ctx="yes_dollars_fp")
    no_levels = _levels(msg.get("no_dollars_fp"), ctx="no_dollars_fp")

    yes_snapshot = BookSnapshot(
        venue=KALSHI_VENUE_ID,
        contract_id=f"{ticker}:YES",
        bids=_price_levels(yes_levels),
        asks=_implied_ask_levels(no_levels),
        sequence=seq,
        source_time=None,
    )
    no_snapshot = BookSnapshot(
        venue=KALSHI_VENUE_ID,
        contract_id=f"{ticker}:NO",
        bids=_price_levels(no_levels),
        asks=_implied_ask_levels(yes_levels),
        sequence=seq,
        source_time=None,
    )
    return yes_snapshot, no_snapshot


def decode_orderbook_delta(frame: Mapping[str, object]) -> tuple[BookDelta, BookDelta]:
    """Decode one ``orderbook_delta`` frame into ``(direct_side, implied_opposite)``.

    A ``side: "yes"`` delta becomes a YES **bid** delta at ``price_dollars`` and
    a NO **ask** delta at ``1 - price_dollars`` (same signed size); ``side: "no"``
    is the mirror.
    """
    _require_type(frame, _DELTA_TYPE)
    seq = _require_int(frame, "seq")
    msg = _require_mapping(frame, "msg")
    ticker = _require_str(msg, "market_ticker")
    price = _decimal(_require_str(msg, "price_dollars"), ctx="price_dollars")
    delta = _decimal(_require_str(msg, "delta_fp"), ctx="delta_fp")
    side = _require_str(msg, "side")
    if side not in ("yes", "no"):
        raise LiveBookError(f"orderbook_delta.side must be 'yes' or 'no', got {side!r}")
    if delta == 0:
        raise LiveBookError("orderbook_delta.delta_fp is zero; refusing to build an empty delta")
    source_time = _optional_ts_ms(msg.get("ts_ms"))

    if side == "yes":
        direct_contract, direct_side = f"{ticker}:YES", "bid"
        implied_contract, implied_side = f"{ticker}:NO", "ask"
    else:
        direct_contract, direct_side = f"{ticker}:NO", "bid"
        implied_contract, implied_side = f"{ticker}:YES", "ask"

    direct = BookDelta(
        venue=KALSHI_VENUE_ID,
        contract_id=direct_contract,
        side=direct_side,  # type: ignore[arg-type]
        price=price,
        quantity_delta=delta,
        sequence=seq,
        source_time=source_time,
    )
    implied = BookDelta(
        venue=KALSHI_VENUE_ID,
        contract_id=implied_contract,
        side=implied_side,  # type: ignore[arg-type]
        price=_ONE - price,
        quantity_delta=delta,
        sequence=seq,
        source_time=source_time,
    )
    return direct, implied


# --------------------------------------------------------------------------- #
# Level helpers (mirror adapters/kalshi/normalize)
# --------------------------------------------------------------------------- #


def _levels(raw: object, *, ctx: str) -> tuple[tuple[Decimal, Decimal], ...]:
    """Parse an optional ``[[price_str, count_str], ...]`` array (absent -> empty)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LiveBookError(f"{ctx}: expected a list of [price, count] pairs")
    out: list[tuple[Decimal, Decimal]] = []
    for index, element in enumerate(raw):
        if not isinstance(element, list) or len(element) != 2:
            raise LiveBookError(f"{ctx}[{index}]: expected a 2-element [price, count] pair")
        price_raw, count_raw = element[0], element[1]
        if not isinstance(price_raw, str) or not isinstance(count_raw, str):
            raise LiveBookError(f"{ctx}[{index}]: price and count must be strings")
        out.append(
            (_decimal(price_raw, ctx=f"{ctx}[{index}].price"),
             _decimal(count_raw, ctx=f"{ctx}[{index}].count"))
        )
    return tuple(out)


def _implied_ask_levels(
    opposite_bids: tuple[tuple[Decimal, Decimal], ...],
) -> tuple[PriceLevel, ...]:
    """A bid at ``X`` on one side is an ask at ``1 - X`` of the same size on the
    other (API_SOURCES K-08)."""
    return _price_levels(tuple((_ONE - price, size) for price, size in opposite_bids))


def _price_levels(levels: tuple[tuple[Decimal, Decimal], ...]) -> tuple[PriceLevel, ...]:
    try:
        return tuple(PriceLevel(price=price, quantity=size) for price, size in levels)
    except DomainValidationError as exc:
        raise LiveBookError(f"invalid order-book level: {exc}") from exc


# --------------------------------------------------------------------------- #
# Field extraction
# --------------------------------------------------------------------------- #


def _require_type(frame: Mapping[str, object], expected: str) -> None:
    if frame.get("type") != expected:
        raise LiveBookError(f"expected frame type {expected!r}, got {frame.get('type')!r}")


def _require_mapping(frame: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = frame.get(key)
    if not isinstance(value, Mapping):
        raise LiveBookError(f"{key!r}: expected an object")
    return value


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LiveBookError(f"{key!r}: expected a non-empty string")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise LiveBookError(f"{key!r}: expected an integer")
    return value


def _decimal(raw: str, *, ctx: str) -> Decimal:
    try:
        return to_decimal(raw, field=ctx)
    except DomainValidationError as exc:
        raise LiveBookError(f"{ctx}: {exc}") from exc


def _optional_ts_ms(raw: object) -> datetime | None:
    """Kalshi ``ts_ms`` is a Unix millisecond timestamp (int). Absent -> ``None``."""
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise LiveBookError("ts_ms: expected an integer Unix millisecond timestamp")
    try:
        return _EPOCH + timedelta(milliseconds=raw)
    except (OverflowError, InvalidOperation) as exc:  # pragma: no cover - defensive
        raise LiveBookError(f"ts_ms: {raw!r} is out of range") from exc
