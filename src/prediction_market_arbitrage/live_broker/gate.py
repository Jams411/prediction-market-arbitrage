"""The live-trading gate (Milestone M3.4).

``LIVE_TRADING`` is **off by default and cannot be flipped by accident**:

- the default constructed gate is disabled;
- the gate is a frozen dataclass — there is no setter, no mutable flag;
- constructing an *enabled* gate requires passing the exact
  :data:`REQUIRED_PHRASE` string, or ``__post_init__`` raises;
- the env path (:meth:`LiveTradingGate.from_env`) enables the gate **only** when
  ``PMA_LIVE_TRADING`` equals that same awkward phrase — ``"1"`` / ``"true"`` /
  ``"yes"`` do nothing;
- even an *active* gate does not make real orders possible: every venue adapter
  still raises :class:`UnsupportedLiveOperationError` because no order endpoint
  has primary evidence (``docs/API_SOURCES.md``).

Real-money trading stays disabled (``docs/DECISIONS.md`` D-002; ROADMAP
"Real-money gate").
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import LiveTradingDisabledError

#: The literal a caller must supply to arm the gate. Deliberately long and
#: unquotable-by-accident.
REQUIRED_PHRASE = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"

#: Environment variable consulted by :meth:`LiveTradingGate.from_env`.
LIVE_TRADING_ENV_VAR = "PMA_LIVE_TRADING"

#: Module-level advertised default — always ``False``. The authoritative control
#: is a :class:`LiveTradingGate` instance; this constant exists so callers /
#: tests can assert the default posture.
LIVE_TRADING_ENABLED = False


@dataclass(frozen=True, slots=True)
class LiveTradingGate:
    """Immutable authorization token for live trading. Default: disabled."""

    enabled: bool = False
    confirmation_phrase: str = ""

    def __post_init__(self) -> None:
        if self.enabled and self.confirmation_phrase != REQUIRED_PHRASE:
            raise LiveTradingDisabledError(
                "LiveTradingGate(enabled=True) requires confirmation_phrase == "
                f"{REQUIRED_PHRASE!r}; refusing to arm the gate"
            )

    @property
    def active(self) -> bool:
        """``True`` only when explicitly enabled *and* the phrase matches."""
        return self.enabled and self.confirmation_phrase == REQUIRED_PHRASE

    def assert_live_allowed(self, *, operation: str) -> None:
        """Raise :class:`LiveTradingDisabledError` unless the gate is active."""
        if not self.active:
            raise LiveTradingDisabledError(
                f"live operation {operation!r} blocked: LIVE_TRADING is disabled "
                "(default). Arm an explicit LiveTradingGate to proceed."
            )

    @classmethod
    def disabled(cls) -> LiveTradingGate:
        """The safe default gate."""
        return cls(enabled=False, confirmation_phrase="")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LiveTradingGate:
        """Armed **only** when ``PMA_LIVE_TRADING`` == :data:`REQUIRED_PHRASE`
        exactly; every other value (including ``"1"`` / ``"true"``) yields a
        disabled gate."""
        source = env if env is not None else dict(os.environ)
        value = source.get(LIVE_TRADING_ENV_VAR, "")
        if value == REQUIRED_PHRASE:
            return cls(enabled=True, confirmation_phrase=REQUIRED_PHRASE)
        return cls.disabled()
