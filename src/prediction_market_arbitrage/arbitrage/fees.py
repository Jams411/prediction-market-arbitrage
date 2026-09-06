"""Injected, deterministic fee models for the arbitrage engine (M1.5).

The engine never hardcodes a real venue fee schedule. A ``FeeModel`` is supplied
by the caller; it returns the **total** fee (a non-negative ``Decimal``) for one
leg's fills. Real Kalshi / Polymarket US fee formulas are a later evidence task
(see ``docs/ASSUMPTIONS.md`` A-022) — the models here are a zero baseline and a
synthetic per-unit model for tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from .errors import ArbitrageError

#: One filled slice of an ask level: ``(price, quantity)``.
Fill = tuple[Decimal, Decimal]

_ZERO = Decimal(0)


class FeeModel(Protocol):
    """Deterministic per-leg fee. ``fee`` returns the total (>= 0) for one leg."""

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        """Total fee for acquiring ``fills`` on ``venue``. Must be a finite Decimal >= 0."""
        ...


class ZeroFeeModel:
    """No fees — the deterministic baseline and the safe default."""

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        return _ZERO


class FixedPerUnitFeeModel:
    """A flat ``Decimal`` fee per filled unit, identical on every venue.

    For tests and synthetic scenarios only — **not** a real venue schedule.
    """

    def __init__(self, per_unit: Decimal) -> None:
        if not isinstance(per_unit, Decimal):
            raise ArbitrageError("FixedPerUnitFeeModel.per_unit must be a Decimal, not float")
        if not per_unit.is_finite() or per_unit < _ZERO:
            raise ArbitrageError("FixedPerUnitFeeModel.per_unit must be finite and >= 0")
        self._per_unit = per_unit

    @property
    def per_unit(self) -> Decimal:
        return self._per_unit

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        total_qty = _ZERO
        for _, quantity in fills:
            total_qty += quantity
        return self._per_unit * total_qty
