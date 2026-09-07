"""Errors raised by the deterministic paper broker (Milestone M2.4)."""

from __future__ import annotations


class PaperBrokerError(Exception):
    """Misuse of the paper broker: a malformed order request, a duplicate or
    unknown ``order_id``, a naive datetime, a non-``Decimal`` value, or time
    moving backwards. Simulated outcomes that simply mean "the order did not (or
    cannot) fill" — a rejection, an expiry, an empty book — are **not** raised;
    they are recorded as order-status transitions.
    """
