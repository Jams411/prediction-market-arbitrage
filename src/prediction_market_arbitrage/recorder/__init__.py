"""Append-only DuckDB recorder (Milestone M2.2).

Persists order-book snapshots, arbitrage-engine opportunity evaluations, order
lifecycle events, fills, position snapshots, PnL snapshots, and feed-health
events. Write-only and deterministic (no wall-clock, no random ids); every
timestamp is injected. Separate from strategy / execution — it records objects
those layers produce, and imports none of their behaviour.

See ``docs/DECISIONS.md`` D-016 and ``docs/ROADMAP.md`` M2.2.
"""

from __future__ import annotations

from . import schema
from .errors import RecorderError
from .models import (
    LIQUIDITY_KINDS,
    ORDER_SIDES,
    ORDER_STATUSES,
    ORDER_TYPES,
    PNL_SCOPES,
    FillRow,
    LegRiskEventRow,
    OrderEventRow,
    PaperLifecycleRow,
    PnlRow,
    PositionRow,
    RiskDecisionRow,
)
from .recorder import Recorder
from .schema import SCHEMA_VERSION, initialize

__all__ = [
    "LIQUIDITY_KINDS",
    "ORDER_SIDES",
    "ORDER_STATUSES",
    "ORDER_TYPES",
    "PNL_SCOPES",
    "SCHEMA_VERSION",
    "FillRow",
    "LegRiskEventRow",
    "OrderEventRow",
    "PaperLifecycleRow",
    "PnlRow",
    "PositionRow",
    "RiskDecisionRow",
    "Recorder",
    "RecorderError",
    "initialize",
    "schema",
]
