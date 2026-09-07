"""Read-only operational dashboard (Milestone M3.1).

Composes objects the pipeline already produces — M1.4 verified pairs, M1.5
arbitrage evaluations, M2.1 feed health / WebSocket state, M2.4 paper orders /
fills / positions / leg risk, M2.5 risk snapshot — into one immutable
:class:`DashboardView`, and renders it as plain text with unhealthy / stale
states marked. No I/O, no wall-clock (``now`` is injected), no order submission,
no strategy logic. See ``docs/DECISIONS.md`` D-020 and ``docs/ROADMAP.md`` M3.1.
"""

from __future__ import annotations

from .build import build_dashboard
from .errors import DashboardError
from .models import (
    Alert,
    DashboardView,
    FeedView,
    FillView,
    LegRiskView,
    OpportunityView,
    OrderView,
    PairView,
    PnlView,
    PositionView,
    RiskView,
    Severity,
)
from .render import render_text

__all__ = [
    "Alert",
    "DashboardError",
    "DashboardView",
    "FeedView",
    "FillView",
    "LegRiskView",
    "OpportunityView",
    "OrderView",
    "PairView",
    "PnlView",
    "PositionView",
    "RiskView",
    "Severity",
    "build_dashboard",
    "render_text",
]
