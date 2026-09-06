"""Exception types raised by the Kalshi market-data adapter.

All adapter failures are subclasses of :class:`KalshiError` so callers can catch
the whole family at one boundary without swallowing unrelated exceptions.
"""

from __future__ import annotations


class KalshiError(Exception):
    """Base class for every Kalshi adapter failure."""


class KalshiTransportError(KalshiError):
    """A network-level failure that is not an HTTP error response (DNS, refused)."""


class KalshiTimeoutError(KalshiError):
    """The HTTP request exceeded the configured timeout."""


class KalshiHTTPError(KalshiError):
    """The API returned a non-2xx HTTP status."""

    def __init__(self, *, status: int, code: str | None = None, message: str | None = None) -> None:
        self.status = status
        self.code = code
        self.message = message
        detail = f" code={code!r}" if code else ""
        detail += f" message={message!r}" if message else ""
        super().__init__(f"Kalshi API returned HTTP {status}{detail}")


class KalshiPayloadError(KalshiError):
    """A response was reachable and 2xx but its body was missing/invalid/malformed."""
