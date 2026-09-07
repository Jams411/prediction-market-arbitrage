"""Deterministic replay of M2.2 recordings through the strategy-facing interfaces
(Milestone M2.3).

Read-only: :class:`ReplaySession` reconstructs each recorded stream for one
session in the recorder's append order, reattaching UTC to stored naive-UTC
timestamps (A-031) and turning stored text back into exact ``Decimal``. Timing
is injected — :func:`no_sleep` (deterministic, the default) or :func:`realtime`.
Replayed order books are handed to ``livebook.LiveBookFeed`` unchanged via
:meth:`ReplaySession.feed_book_snapshots`.

See ``docs/DECISIONS.md`` D-017 and ``docs/ROADMAP.md`` M2.3.
"""

from __future__ import annotations

from .errors import ReplayError
from .models import (
    RecordedFill,
    RecordedHealthEvent,
    RecordedOpportunity,
    RecordedOrderBook,
    RecordedOrderEvent,
    RecordedPnl,
    RecordedPosition,
    ReplayEvent,
)
from .session import ReplaySession, no_sleep, realtime

__all__ = [
    "RecordedFill",
    "RecordedHealthEvent",
    "RecordedOpportunity",
    "RecordedOrderBook",
    "RecordedOrderEvent",
    "RecordedPnl",
    "RecordedPosition",
    "ReplayError",
    "ReplayEvent",
    "ReplaySession",
    "no_sleep",
    "realtime",
]
