"""Exception types for the Kalshi **DEMO-only** execution orchestrator (M3.5)."""

from __future__ import annotations


class DemoExecutionError(Exception):
    """Base class for every demo-execution failure."""


class DemoHostError(DemoExecutionError):
    """A base URL that is not a Kalshi **demo** host was supplied. The demo
    execution path refuses to touch production Kalshi — this is a hard failure,
    never a downgrade."""


class DemoCapabilityError(DemoExecutionError):
    """A capability or venue state required to proceed safely is missing or
    ambiguous (e.g. a 2xx create response with no ``order_id``). The
    orchestrator fails closed rather than guessing."""
