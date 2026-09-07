"""Deterministic paper broker (Milestone M2.4).

Simulates order execution against normalized :class:`OrderBook` depth with an
injected latency, slippage, and fee model — no venue, no wall-clock, no
randomness. Produces immutable :class:`Order` / :class:`Fill` snapshots that
convert to the M2.2 recorder row models (``event_rows()`` / ``to_row()``), and a
:class:`LegRiskSnapshot` measuring one-legged exposure between two orders.

See ``docs/DECISIONS.md`` D-018 and ``docs/ROADMAP.md`` M2.4.
"""

from __future__ import annotations

from .broker import PaperBroker, PaperBrokerConfig
from .errors import PaperBrokerError
from .models import (
    BrokerEvent,
    Fill,
    LegRiskSnapshot,
    Order,
    OrderRequest,
    OrderStatus,
    StatusTransition,
)
from .slippage import (
    FixedOffsetSlippage,
    NoSlippage,
    PerLevelSlippage,
    SlippageModel,
)

__all__ = [
    "BrokerEvent",
    "Fill",
    "FixedOffsetSlippage",
    "LegRiskSnapshot",
    "NoSlippage",
    "Order",
    "OrderRequest",
    "OrderStatus",
    "PaperBroker",
    "PaperBrokerConfig",
    "PaperBrokerError",
    "PerLevelSlippage",
    "SlippageModel",
    "StatusTransition",
]
