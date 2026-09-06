"""Errors raised by the deterministic arbitrage engine (Milestone M1.5)."""

from __future__ import annotations


class ArbitrageError(Exception):
    """Misuse of the engine: a non-eligible pair, a book that does not match the
    pair's leg, a non-timezone-aware evaluation time, or a misbehaving fee model.

    Economic / data conditions that simply mean "no trade" (empty ask side,
    insufficient depth, non-positive edge, stale books) are **not** errors — the
    engine returns an :class:`~.engine.OpportunityEvaluation` with
    ``has_opportunity = False`` and a ``rejection_reason``.
    """
