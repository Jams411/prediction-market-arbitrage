"""Deterministic slippage models for the paper broker (Milestone M2.4).

Walking real order-book depth already produces the *visible* price impact. A
``SlippageModel`` layers an **additional, deterministic** adverse adjustment on
each filled level — hidden liquidity, queue position, adverse selection — as a
pure function of the fill, never a random draw.

``adjust`` returns the executed price for one level slice. For a **buy** the
model may only return a price ``>=`` the level price (you pay up); for a
**sell**, ``<=`` (you receive less). The broker clamps the result into
``(0, 1)`` (A-033).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from .errors import PaperBrokerError

Side = Literal["buy", "sell"]
_ZERO = Decimal(0)


class SlippageModel(Protocol):
    """Deterministic per-level execution-price adjustment."""

    def adjust(
        self,
        *,
        side: Side,
        level_price: Decimal,
        level_index: int,
        filled_quantity: Decimal,
        cumulative_quantity: Decimal,
    ) -> Decimal:
        """The executed price for this level slice (see module docstring)."""
        ...


class NoSlippage:
    """Execute exactly at the walked level price — the deterministic baseline."""

    def adjust(
        self,
        *,
        side: Side,
        level_price: Decimal,
        level_index: int,
        filled_quantity: Decimal,
        cumulative_quantity: Decimal,
    ) -> Decimal:
        return level_price


class FixedOffsetSlippage:
    """Add a flat ``offset`` (in price units) against the taker on every level.

    Buy fills at ``level_price + offset``, sell at ``level_price - offset``.
    """

    def __init__(self, offset: Decimal) -> None:
        if not isinstance(offset, Decimal) or not offset.is_finite() or offset < _ZERO:
            raise PaperBrokerError("FixedOffsetSlippage.offset must be a finite Decimal >= 0")
        self._offset = offset

    @property
    def offset(self) -> Decimal:
        return self._offset

    def adjust(
        self,
        *,
        side: Side,
        level_price: Decimal,
        level_index: int,
        filled_quantity: Decimal,
        cumulative_quantity: Decimal,
    ) -> Decimal:
        return level_price + self._offset if side == "buy" else level_price - self._offset


class PerLevelSlippage:
    """Adverse ``step`` per level walked past the top of book (``level_index``).

    Deepening into the book costs ``step * level_index`` extra — a deterministic
    proxy for the book being thinner than it looks.
    """

    def __init__(self, step: Decimal) -> None:
        if not isinstance(step, Decimal) or not step.is_finite() or step < _ZERO:
            raise PaperBrokerError("PerLevelSlippage.step must be a finite Decimal >= 0")
        self._step = step

    @property
    def step(self) -> Decimal:
        return self._step

    def adjust(
        self,
        *,
        side: Side,
        level_price: Decimal,
        level_index: int,
        filled_quantity: Decimal,
        cumulative_quantity: Decimal,
    ) -> Decimal:
        penalty = self._step * level_index
        return level_price + penalty if side == "buy" else level_price - penalty
