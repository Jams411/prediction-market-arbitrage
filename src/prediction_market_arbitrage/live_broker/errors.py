"""Exception types for the live-broker interface boundary (Milestone M3.4)."""

from __future__ import annotations


class LiveBrokerError(Exception):
    """Base class for every live-broker failure."""


class LiveTradingDisabledError(LiveBrokerError):
    """A live operation was attempted while the :class:`LiveTradingGate` is not
    active. This is the default state and the safe one."""


class UnsupportedLiveOperationError(LiveBrokerError):
    """A venue live-broker operation has **no primary-evidence-backed**
    request/response shape in ``docs/API_SOURCES.md`` and is therefore left
    explicitly unimplemented rather than guessed."""

    def __init__(self, *, venue: str, operation: str, reason: str) -> None:
        self.venue = venue
        self.operation = operation
        self.reason = reason
        super().__init__(f"{venue}.{operation}: unsupported — {reason}")


class DuplicateOrderError(LiveBrokerError):
    """The interface-level idempotency guard rejected a re-used
    ``client_order_id`` before any venue call was made."""


class LiveBrokerCredentialError(LiveBrokerError):
    """Trading credentials are missing or malformed."""
