"""Shared value-conversion / validation helpers for the recorder (M2.2).

Fidelity rules:
- **Decimal** values are stored as their exact ``str(Decimal)`` text in
  ``VARCHAR`` columns, never as a float or a fixed-scale ``DECIMAL`` — a
  round-trip through ``Decimal(text)`` reproduces the original bit-for-bit at
  any scale. The recorder does no arithmetic.
- **Timestamps** must be timezone-aware on the way in; they are normalized to
  UTC and stored as a naive-UTC ``TIMESTAMP`` (microsecond precision, which
  matches what the domain already carries — see A-031). A reader re-attaches
  UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from .errors import RecorderError


def dec_text(value: Decimal, *, field: str) -> str:
    """Exact text for a finite :class:`~decimal.Decimal` (rejects float / non-finite)."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise RecorderError(f"{field}: expected a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise RecorderError(f"{field}: non-finite Decimal ({value}) cannot be recorded")
    return str(value)


def opt_dec_text(value: Decimal | None, *, field: str) -> str | None:
    return None if value is None else dec_text(value, field=field)


def utc_naive(value: datetime, *, field: str) -> datetime:
    """A timezone-aware datetime normalized to naive UTC for a ``TIMESTAMP`` column."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RecorderError(f"{field}: expected a timezone-aware datetime")
    return value.astimezone(UTC).replace(tzinfo=None)


def opt_utc_naive(value: datetime | None, *, field: str) -> datetime | None:
    return None if value is None else utc_naive(value, field=field)


def require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecorderError(f"{field}: expected a non-empty string")
    return value


def require_choice(value: str, allowed: frozenset[str], *, field: str) -> str:
    if value not in allowed:
        raise RecorderError(f"{field}: {value!r} not one of {sorted(allowed)}")
    return value
