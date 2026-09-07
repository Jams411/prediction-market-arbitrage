"""Deterministic risk manager (Milestone M2.5).

Enforces config-injected limits — max position, max exposure, max order size,
minimum net edge, max data age, max unhedged time, consecutive-error limit, max
daily loss, kill switch — over the objects the earlier milestones produce
(M1.5 ``OpportunityEvaluation``, M2.1 ``FeedHealth``, M2.4 positions /
``LegRiskSnapshot``). Returns an explicit :class:`RiskDecision`; fails closed
when a required input is missing or unhealthy. No new dependency, no strategy
logic. See ``docs/DECISIONS.md`` D-019 and ``docs/ROADMAP.md`` M2.5.
"""

from __future__ import annotations

from .decision import RiskDecision
from .errors import RiskError
from .limits import RiskLimits
from .manager import RiskManager, RiskSnapshot
from .state import RiskState

__all__ = [
    "RiskDecision",
    "RiskError",
    "RiskLimits",
    "RiskManager",
    "RiskSnapshot",
    "RiskState",
]
