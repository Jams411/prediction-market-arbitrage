"""Interface-boundary duplicate-order guard (Milestone M3.4).

A per-process, in-memory record of every ``client_order_id`` already submitted
through this interface. It rejects a re-submit **before** any venue call — the
*local* half of duplicate-order prevention.

It is **not** a substitute for venue-side idempotency: whether a venue honours a
client-supplied order key is unverified for both venues (``docs/API_SOURCES.md``
has no order-endpoint evidence), so a real deployment still needs the venue to
dedupe on its side. This guard only guarantees this process will not *send* the
same ``client_order_id`` twice.
"""

from __future__ import annotations

from .errors import DuplicateOrderError, LiveBrokerError


class IdempotencyGuard:
    """Tracks submitted ``client_order_id``s for one process / broker instance."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def register(self, client_order_id: str) -> None:
        """Record ``client_order_id`` as submitted. Raise
        :class:`DuplicateOrderError` if it was already recorded."""
        if not isinstance(client_order_id, str) or not client_order_id.strip():
            raise LiveBrokerError("client_order_id must be a non-empty string")
        if client_order_id in self._seen:
            raise DuplicateOrderError(
                f"client_order_id {client_order_id!r} was already submitted through "
                "this interface; refusing to resend"
            )
        self._seen.add(client_order_id)

    def seen(self, client_order_id: str) -> bool:
        return client_order_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)
