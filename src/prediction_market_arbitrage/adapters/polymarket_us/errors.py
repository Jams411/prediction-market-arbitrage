"""Exception types raised by the Polymarket US market-data adapter.

All adapter failures subclass :class:`PolymarketError` so callers can catch the
whole family at one boundary without swallowing unrelated exceptions. Kept
separate from the Kalshi adapter's error family on purpose — the two adapters
are independent replaceable components (``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations


class PolymarketError(Exception):
    """Base class for every Polymarket US adapter failure."""


class PolymarketTransportError(PolymarketError):
    """A network-level failure that is not an HTTP error response (DNS, refused)."""


class PolymarketTimeoutError(PolymarketError):
    """The HTTP request exceeded the configured timeout."""


class PolymarketHTTPError(PolymarketError):
    """The API returned a non-2xx HTTP status.

    Polymarket US error bodies are shaped ``{"code": <int>, "message": <str>,
    "details": [...]}`` (gRPC-style), unlike Kalshi's ``{"error": {...}}``.
    """

    def __init__(
        self, *, status: int, code: int | None = None, message: str | None = None
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        detail = f" code={code}" if code is not None else ""
        detail += f" message={message!r}" if message else ""
        super().__init__(f"Polymarket US API returned HTTP {status}{detail}")


class PolymarketPayloadError(PolymarketError):
    """A response was reachable and 2xx but its body was missing/invalid/malformed."""
