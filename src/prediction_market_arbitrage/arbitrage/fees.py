"""Injected, deterministic fee models for the arbitrage engine.

The engine never hardcodes a real venue fee schedule. A ``FeeModel`` is supplied
by the caller; it returns the **total** fee (a non-negative ``Decimal``) for one
leg's fills.

- ``ZeroFeeModel`` / ``FixedPerUnitFeeModel`` — M1.5 baseline / synthetic only.
- ``KalshiTradingFeeModel`` / ``PolymarketUsTradingFeeModel`` — M1.6
  evidence-backed venue fee formulas (taker path). Each carries its own
  published coefficient and rounding rule; see ``docs/DECISIONS.md`` D-013 and
  ``docs/ASSUMPTIONS.md`` A-024 / A-025 / A-026 for the primary sources and the
  open reconciliation blocker.
- ``VenueFeeModel`` — routes each leg's fills to the model registered for its
  venue, so one injected value covers both legs and fails closed on an unknown
  venue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from typing import Protocol

from .errors import ArbitrageError

#: One filled slice of an ask level: ``(price, quantity)``.
Fill = tuple[Decimal, Decimal]

_ZERO = Decimal(0)
_ONE = Decimal(1)
_CENT = Decimal("0.01")


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


# --------------------------------------------------------------------------- #
# M1.6 — evidence-backed real venue fee models (taker path)
# --------------------------------------------------------------------------- #
#
# Both venues publish the *same shape* of variable fee — a coefficient times the
# per-contract expected earnings ``P * (1 - P)`` times the contract count — and
# differ only in the coefficient and the cent-rounding rule. The buy/buy
# arbitrage engine always lifts resting asks, so every fill is a **taker** fill;
# the taker coefficients are the defaults here. Maker formulas are recorded in
# the docstrings and ``docs/`` but are not modelled (the engine has no maker
# leg, and Polymarket US's maker side is a *rebate* — a negative fee the
# ``FeeModel`` contract does not represent).


def _require_coefficient(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal):
        raise ArbitrageError(f"{label} must be a Decimal, not float")
    if not value.is_finite() or value < _ZERO:
        raise ArbitrageError(f"{label} must be a finite Decimal >= 0")


def _require_fill_component(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ArbitrageError(f"fill {label} must be a finite Decimal")


def _round_up_cent(value: Decimal) -> Decimal:
    """Kalshi "rounds to the next cent". Exact cent multiples are unchanged
    (the published table lists a flat $1.75 for 100 contracts at $0.50, where
    ``0.07 * 100 * 0.25`` is exactly 1.75)."""
    return (value / _CENT).to_integral_value(rounding=ROUND_CEILING) * _CENT


def _round_half_even_cent(value: Decimal) -> Decimal:
    """Polymarket US: "rounded to the nearest $0.01 using banker's rounding
    (round half to even)" — e.g. $0.285 -> $0.28, $0.035 -> $0.04."""
    return value.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _sum_variable_fee(
    coefficient: Decimal,
    fills: Sequence[Fill],
    round_fill: Callable[[Decimal], Decimal],
) -> Decimal:
    """``sum_i round_fill(coefficient * qty_i * P_i * (1 - P_i))``.

    Rounding is applied **per fill slice** and the rounded slices are summed
    (A-026): neither venue's published schedule states how a single taker order
    that sweeps several price levels is rounded, and every worked example is a
    single price. A price outside ``(0, 1)`` makes the slice's expected-earnings
    term non-positive; that slice contributes ``0`` rather than a negative fee.
    """
    total = _ZERO
    for price, quantity in fills:
        _require_fill_component(price, "price")
        _require_fill_component(quantity, "quantity")
        if quantity < _ZERO:
            raise ArbitrageError("fill quantity must be >= 0")
        expected_earnings = price * (_ONE - price)
        raw = coefficient * quantity * expected_earnings
        if raw > _ZERO:
            total += round_fill(raw)
    return total


class KalshiTradingFeeModel:
    """Kalshi trading fee, taker path.

    Primary source: Kalshi published fee schedule PDF, "Fee Schedule for
    July 2026 — 7.7.26 Update" (``kalshi.com/docs/kalshi-fee-schedule.pdf``;
    retained extract: ``docs/evidence/kalshi-fee-schedule-2026-07-07.txt``).

        general taker: fee = round_up_cent(M * 0.07   * C * P * (1 - P))
        maker:         fee = round_up_cent(M * 0.0175 * C * P * (1 - P))   [not modelled]

    ``P`` is the contract price in dollars (domain ``OrderBook`` prices are
    already dollars); ``C`` is the contract count; "round up" is to the next
    cent. There is no settlement fee.

    ``M`` is the per-contract multiplier: ``1`` by default ("unless otherwise
    indicated"), overridden only for the series listed in Kalshi's current
    "non-standard fees" table. The pre-July-2026 standalone ``0.035`` S&P 500 /
    Nasdaq-100 fee table has been folded into this per-series multiplier system
    and is no longer a separate coefficient. This model cannot read a series or
    market type from an ``OrderBook``; a caller evaluating a non-standard series
    passes an evidence-backed ``multiplier`` explicitly (A-024).
    """

    VENUE = "kalshi"
    BASE_TAKER_COEFFICIENT = Decimal("0.07")
    BASE_MAKER_COEFFICIENT = Decimal("0.0175")
    DEFAULT_MULTIPLIER = Decimal("1")

    def __init__(self, *, multiplier: Decimal | None = None) -> None:
        multiplier = (
            self.DEFAULT_MULTIPLIER if multiplier is None else multiplier
        )
        _require_coefficient(multiplier, "KalshiTradingFeeModel multiplier")
        self._multiplier = multiplier
        self._coefficient = multiplier * self.BASE_TAKER_COEFFICIENT

    @property
    def multiplier(self) -> Decimal:
        return self._multiplier

    @property
    def coefficient(self) -> Decimal:
        """Effective taker coefficient: ``multiplier * 0.07``."""
        return self._coefficient

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        if venue != self.VENUE:
            raise ArbitrageError(
                f"KalshiTradingFeeModel applied to non-Kalshi venue {venue!r}"
            )
        return _sum_variable_fee(self._coefficient, fills, _round_up_cent)


class PolymarketUsTradingFeeModel:
    """Polymarket US trading fee, taker path.

    Primary source: Polymarket US docs, "Fee Schedule" (``docs.polymarket.us/fees``;
    retained copy: ``docs/evidence/polymarket-us-fee-schedule.txt``).

        Fee = Θ * C * p * (1 - p)
        taker:  Θ =  0.06     (max $1.50 at p = $0.50)
        maker:  Θ = -0.0125   (a rebate; not modelled)

    ``p`` is the trade price in dollars ($0.01–$0.99); ``C`` is the contract
    count; fees are rounded to the nearest cent with banker's rounding. Fees are
    only charged on execution and can round to $0.00 on small trades. The
    volume-tiered *taker rebate* (>= $250k prior-month volume, paid weekly) is a
    retrospective account-level credit, not a per-trade term, so it is not
    applied here (A-025).
    """

    VENUE = "polymarket_us"
    TAKER_COEFFICIENT = Decimal("0.06")
    MAKER_REBATE_COEFFICIENT = Decimal("0.0125")

    def __init__(self, *, taker_coefficient: Decimal | None = None) -> None:
        coefficient = (
            self.TAKER_COEFFICIENT
            if taker_coefficient is None
            else taker_coefficient
        )
        _require_coefficient(coefficient, "PolymarketUsTradingFeeModel coefficient")
        self._coefficient = coefficient

    @property
    def coefficient(self) -> Decimal:
        return self._coefficient

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        if venue != self.VENUE:
            raise ArbitrageError(
                f"PolymarketUsTradingFeeModel applied to non-Polymarket-US venue {venue!r}"
            )
        return _sum_variable_fee(self._coefficient, fills, _round_half_even_cent)


class VenueFeeModel:
    """Routes each leg's fills to the ``FeeModel`` registered for its venue.

    Injected as a single ``FeeModel`` so one config value covers both legs.
    Fails closed: a venue with no registered model raises ``ArbitrageError``
    rather than silently charging zero or the wrong venue's schedule.
    """

    def __init__(self, models: Mapping[str, FeeModel]) -> None:
        if not models:
            raise ArbitrageError("VenueFeeModel requires at least one venue model")
        self._models: dict[str, FeeModel] = dict(models)

    def fee(self, *, venue: str, fills: Sequence[Fill]) -> Decimal:
        model = self._models.get(venue)
        if model is None:
            raise ArbitrageError(
                f"VenueFeeModel has no fee model for venue {venue!r} "
                f"(registered: {sorted(self._models)})"
            )
        return model.fee(venue=venue, fills=fills)

    @classmethod
    def real_taker(cls) -> VenueFeeModel:
        """Kalshi + Polymarket US taker models with each venue's published rate.

        Kalshi uses the default per-contract multiplier ``M = 1``; build the
        dict directly with ``KalshiTradingFeeModel(multiplier=...)`` for a series
        that carries a non-standard multiplier in Kalshi's current fee table.
        """
        return cls(
            {
                KalshiTradingFeeModel.VENUE: KalshiTradingFeeModel(),
                PolymarketUsTradingFeeModel.VENUE: PolymarketUsTradingFeeModel(),
            }
        )
