"""Shared construction-boundary validation helpers for the domain layer.

These helpers are deliberately small, pure, and deterministic. They raise
:class:`DomainValidationError` (a :class:`ValueError` subclass) so callers can
catch domain-invariant failures without catching unrelated ``ValueError``s.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)


class DomainValidationError(ValueError):
    """Raised when a domain model invariant is violated at a construction boundary."""


def to_decimal(value: Decimal | int | str, *, field: str) -> Decimal:
    """Explicitly build a finite :class:`Decimal` from a boundary input.

    Accepts ``Decimal``, ``int``, or a numeric ``str``. ``float`` and ``bool`` are
    rejected so binary floating-point rounding never enters the domain layer
    implicitly. Non-finite values (``NaN``/``Infinity``) are rejected.

    This is intended for adapter/parsing code (M1.2+). Domain models themselves
    require an already-constructed :class:`Decimal`; see :func:`as_decimal`.
    """
    if isinstance(value, bool):
        raise DomainValidationError(f"{field}: bool is not an accepted numeric input")
    if isinstance(value, float):
        raise DomainValidationError(
            f"{field}: float input is rejected; pass Decimal, int, or a numeric string"
        )
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int | str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise DomainValidationError(
                f"{field}: cannot parse Decimal from {value!r}"
            ) from exc
    else:  # pragma: no cover - defensive; unreachable for correctly typed callers
        raise DomainValidationError(
            f"{field}: unsupported numeric input type {type(value).__name__}"
        )
    if not result.is_finite():
        raise DomainValidationError(f"{field}: non-finite Decimal ({result}) is not allowed")
    return result


def as_decimal(value: object, *, field: str) -> Decimal:
    """Assert that a domain field already holds a finite :class:`Decimal`.

    Domain models require explicit ``Decimal`` construction. Anything else passed
    dynamically (``float``, ``int``, ``str``, ...) is rejected here rather than
    silently coerced.
    """
    if not isinstance(value, Decimal):
        raise DomainValidationError(
            f"{field}: expected an explicit Decimal, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise DomainValidationError(f"{field}: non-finite Decimal ({value}) is not allowed")
    return value


def require_positive(value: Decimal, *, field: str) -> Decimal:
    """Reject values that are not strictly greater than zero."""
    if value <= ZERO:
        raise DomainValidationError(f"{field}: must be > 0, got {value}")
    return value


def require_probability_price(value: Decimal, *, field: str) -> Decimal:
    """Reject normalized prices outside the inclusive ``[0, 1]`` probability range."""
    if value < ZERO or value > ONE:
        raise DomainValidationError(
            f"{field}: normalized probability price must be within [0, 1], got {value}"
        )
    return value


def require_non_empty(value: str, *, field: str) -> str:
    """Reject empty or whitespace-only identifiers."""
    if not value or not value.strip():
        raise DomainValidationError(f"{field}: must be a non-empty identifier")
    return value


def require_aware(value: datetime, *, field: str) -> datetime:
    """Reject naive timestamps; require an offset-carrying ``datetime``."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field}: must be a timezone-aware datetime")
    return value
