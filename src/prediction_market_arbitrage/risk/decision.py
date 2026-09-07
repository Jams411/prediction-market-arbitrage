"""The risk manager's verdict (Milestone M2.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Explicit allow / reject with every failing reason (not just the first)."""

    allowed: bool
    reasons: tuple[str, ...]
    checks_run: tuple[str, ...]
    as_of: datetime

    @property
    def rejected(self) -> bool:
        return not self.allowed

    def raise_if_rejected(self) -> None:
        """Convenience for callers that treat a rejection as a hard stop."""
        if not self.allowed:
            from .errors import RiskError

            raise RiskError("risk rejected: " + "; ".join(self.reasons))
