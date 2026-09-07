"""Row -> object reconstruction helpers for the replay adapter (M2.3).

Inverse of ``recorder._convert``:
- naive-``TIMESTAMP`` values come back from DuckDB as naive ``datetime``; replay
  **reattaches UTC explicitly** (``.replace(tzinfo=UTC)``) because the recorder
  stored a UTC instant (A-031).
- ``VARCHAR`` money / price / quantity text is turned back into an exact
  :class:`~decimal.Decimal` via ``Decimal(text)`` — bit-for-bit, any scale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from prediction_market_arbitrage.domain import (
    Contract,
    DomainValidationError,
    Market,
    Venue,
)

from .errors import ReplayError


def to_utc(value: datetime) -> datetime:
    """Reattach UTC to a stored naive-UTC timestamp (A-031)."""
    if not isinstance(value, datetime):
        raise ReplayError(f"expected a stored datetime, got {type(value).__name__}")
    if value.tzinfo is not None:
        # Already aware (shouldn't happen for our columns) — normalize.
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def opt_to_utc(value: datetime | None) -> datetime | None:
    return None if value is None else to_utc(value)


def to_decimal(text: str, *, field: str) -> Decimal:
    if not isinstance(text, str):
        raise ReplayError(f"{field}: expected stored Decimal text, got {type(text).__name__}")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ReplayError(f"{field}: cannot parse Decimal from {text!r}") from exc
    if not value.is_finite():
        raise ReplayError(f"{field}: non-finite Decimal {text!r}")
    return value


def opt_to_decimal(text: str | None, *, field: str) -> Decimal | None:
    return None if text is None else to_decimal(text, field=field)


def rebuild_contract(venue_id: str, market_id: str, contract_id: str, outcome: str) -> Contract:
    """Reconstruct the domain :class:`Contract`.

    The recorder stores identifiers only, not display names, so ``Venue.name`` /
    ``Market.title`` are synthesized from the ids (A-032). ``Contract.id``,
    ``outcome``, ``venue.id`` and ``market.id`` — the fields strategy / engine
    code actually joins on — are exact.
    """
    try:
        venue = Venue(id=venue_id, name=venue_id)
        market = Market(venue=venue, id=market_id, title=market_id, close_time=None)
        return Contract(market=market, id=contract_id, outcome=outcome)
    except DomainValidationError as exc:
        raise ReplayError(f"cannot rebuild contract {contract_id!r}: {exc}") from exc
