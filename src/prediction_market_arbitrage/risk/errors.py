"""Errors raised by the deterministic risk manager (Milestone M2.5)."""

from __future__ import annotations


class RiskError(Exception):
    """Misuse of the risk manager: a malformed limit, a naive datetime, a
    non-``Decimal`` value, or time moving backwards. A limit being **breached**
    — or a required input being **missing / unhealthy** — is not an error: it
    produces a :class:`~.decision.RiskDecision` with ``allowed = False`` and a
    reason (fail-closed).
    """
