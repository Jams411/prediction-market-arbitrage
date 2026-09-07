"""Mutable state the risk manager owns — the parts not held by other components
(Milestone M2.5).

Deterministic: every mutation takes an injected timezone-aware ``datetime``;
there is no wall-clock read. The kill switch, the consecutive-error counter, the
per-UTC-day realized-PnL ledger, and the "unhedged since" map live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from .errors import RiskError

_ZERO = Decimal(0)


def _require_aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RiskError(f"{name} must be a timezone-aware datetime")
    return value


def _require_decimal(value: Decimal, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise RiskError(f"{name} must be a finite Decimal")
    return value


@dataclass(slots=True)
class RiskState:
    """Kill switch + error streak + daily PnL ledger + unhedged timers."""

    _killed: bool = field(default=False)
    _kill_reason: str = field(default="")
    _consecutive_errors: int = field(default=0)
    _daily_pnl: dict[date, Decimal] = field(default_factory=dict)
    _unhedged_since: dict[str, datetime] = field(default_factory=dict)

    # -- kill switch --------------------------------------------------- #

    @property
    def killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def engage_kill_switch(self, reason: str) -> None:
        self._killed = True
        self._kill_reason = reason or "kill switch engaged"

    def release_kill_switch(self) -> None:
        self._killed = False
        self._kill_reason = ""

    # -- consecutive errors ----------------------------------------- #

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    def record_error(self) -> int:
        self._consecutive_errors += 1
        return self._consecutive_errors

    def record_success(self) -> None:
        self._consecutive_errors = 0

    # -- daily realized PnL --------------------------------------- #

    def record_realized_pnl(self, amount: Decimal, *, at: datetime) -> None:
        """Add ``amount`` (negative = loss) to the UTC-day bucket for ``at``."""
        _require_decimal(amount, name="realized pnl amount")
        day = _require_aware(at, name="at").astimezone(UTC).date()
        self._daily_pnl[day] = self._daily_pnl.get(day, _ZERO) + amount

    def daily_realized_pnl(self, day: date) -> Decimal:
        return self._daily_pnl.get(day, _ZERO)

    def daily_loss(self, day: date) -> Decimal:
        """Loss magnitude for ``day`` (``0`` when the day is flat or profitable)."""
        pnl = self._daily_pnl.get(day, _ZERO)
        return -pnl if pnl < _ZERO else _ZERO

    # -- unhedged timers --------------------------------------- #

    def note_unhedged(self, pair_key: str, *, at: datetime) -> datetime:
        """Record when ``pair_key`` first became unhedged; idempotent while it
        stays unhedged. Returns the first-seen time."""
        _require_aware(at, name="at")
        return self._unhedged_since.setdefault(pair_key, at)

    def note_hedged(self, pair_key: str) -> None:
        self._unhedged_since.pop(pair_key, None)

    def unhedged_since(self, pair_key: str) -> datetime | None:
        return self._unhedged_since.get(pair_key)

    def unhedged_pairs(self) -> tuple[tuple[str, datetime], ...]:
        """All currently-unhedged pairs and when each first became unhedged."""
        return tuple((key, self._unhedged_since[key]) for key in sorted(self._unhedged_since))
