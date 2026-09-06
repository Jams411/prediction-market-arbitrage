"""Errors raised by the live-book-state layer (Milestone M2.1)."""

from __future__ import annotations


class LiveBookError(Exception):
    """Misuse of the live-book layer: a malformed WebSocket payload, an update
    for the wrong contract, a non-timezone-aware clock reading, or a delta
    applied before any snapshot.

    Conditions that simply mean "the feed is not usable right now" — a sequence
    gap, a disconnect, a stale feed, a crossed book after applying a delta — are
    **not** raised. They move the feed into an unhealthy
    :class:`~.state.HealthStatus` so ``trading_enabled`` becomes ``False``
    (fail-closed) and the caller is expected to resync.
    """
