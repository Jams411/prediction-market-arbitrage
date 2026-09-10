"""Kalshi **DEMO-only** execution orchestrator (Milestone M3.5).

Composes the *existing* components — :class:`~..risk.RiskManager` (unchanged
fail-closed vetoes), :class:`~..live_broker.LiveBroker` (unchanged gate +
idempotency wrapper), and the M2.2 :class:`~..recorder.Recorder` — into one
demo execution path. The only new pieces are:

- :class:`KalshiDemoLiveBroker` — a concrete ``LiveBroker`` that maps the
  evidence-backed Kalshi **demo** order endpoints (K-TR-04..10, OBSERVED
  K-TR-OBS-26..33) over an injected :class:`DemoTransport`, and is **hard-pinned
  to the demo host** at construction (:func:`assert_demo_host`);
- :class:`DemoExecutionOrchestrator` — intent → risk → submit → record, plus
  explicit ``cancel`` / ``reconcile``.

This does **not** enable production trading. There is no production endpoint,
no production credential path, and no ``LIVE_TRADING`` read/write here.
Production live trading stays disabled (D-002 / D-023 / A-037). See
``docs/DECISIONS.md`` D-030.
"""

from __future__ import annotations

from .broker import KalshiDemoLiveBroker
from .errors import DemoCapabilityError, DemoExecutionError, DemoHostError
from .orchestrator import DemoExecutionOrchestrator, ExecutionOutcome
from .transport import (
    DEMO_HOST_MARKER,
    PROD_HOST_MARKERS,
    DemoResponse,
    DemoTransport,
    assert_demo_host,
)

__all__ = [
    "DEMO_HOST_MARKER",
    "PROD_HOST_MARKERS",
    "DemoCapabilityError",
    "DemoExecutionError",
    "DemoExecutionOrchestrator",
    "DemoHostError",
    "DemoResponse",
    "DemoTransport",
    "ExecutionOutcome",
    "KalshiDemoLiveBroker",
    "assert_demo_host",
]
