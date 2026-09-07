"""Deterministic paper-performance report from a recorded session (Milestone M3.3).

Reads one M2.2 recording through the M2.3 :class:`~prediction_market_arbitrage.replay.ReplaySession`
and computes opportunities observed vs rejected, paper-trade fill / partial-fill
rates, mean / median net edge, derived opportunity duration, available-depth
statistics, paper PnL and drawdown. Leg-risk events are **not persisted** by the
recorder and are reported as unavailable, not as zero. A metric the recording
cannot support is ``None`` (rendered "n/a"), kept distinct from a real ``0``.

Pure: no wall-clock, no persistence write, no order submission. See
``docs/DECISIONS.md`` D-022 and ``docs/ROADMAP.md`` M3.3.
"""

from __future__ import annotations

from .build import build_report
from .errors import PerfReportError
from .models import (
    DepthStats,
    LegRiskStats,
    OpportunityDurationStats,
    OpportunityStats,
    PerfReport,
    PnlStats,
    Stats,
    TradeStats,
)
from .render import render_text

__all__ = [
    "DepthStats",
    "LegRiskStats",
    "OpportunityDurationStats",
    "OpportunityStats",
    "PerfReport",
    "PerfReportError",
    "PnlStats",
    "Stats",
    "TradeStats",
    "build_report",
    "render_text",
]
