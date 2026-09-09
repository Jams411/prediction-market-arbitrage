"""Concrete synchronous :class:`~.transport.WebSocketTransport` over the
``websockets`` library (Milestone M2.1).

``websockets`` is the client both the Kalshi and Polymarket US docs use
(``docs/API_SOURCES.md`` WS-A-S1); its ``additional_headers=`` argument carries
the auth headers built by :mod:`.ws_auth` into the handshake exactly as the docs
show. The library answers server Ping frames (Kalshi sends one every ~10s,
K-WS-06) automatically, so no keepalive code is needed here.

This module is the **only** part of ``livebook`` that does real network I/O and
the only one that imports a third-party package. Everything above it
(:class:`~.transport.LiveBookConnection`, the decoders, the state machine) stays
pure and is tested with fakes; this class is tested against a local
``websockets`` echo/script server on loopback — a real socket round-trip, no
credentials, no live venue.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from .errors import LiveBookError
from .transport import TransportClosed
from .ws_auth import Handshake

_DEFAULT_OPEN_TIMEOUT = 10.0
_DEFAULT_CLOSE_TIMEOUT = 5.0


class WebsocketsTransport:
    """Blocking WebSocket transport. One instance == one connection at a time.

    ``receive`` blocks until the next message unless ``recv_timeout`` (seconds)
    was given to the constructor, in which case a timeout raises
    :class:`~.transport.TransportClosed` (the connection is then unusable and
    the manager reconnects).
    """

    def __init__(
        self,
        *,
        open_timeout: float = _DEFAULT_OPEN_TIMEOUT,
        close_timeout: float = _DEFAULT_CLOSE_TIMEOUT,
        recv_timeout: float | None = None,
        max_message_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout
        self._recv_timeout = recv_timeout
        self._max_message_bytes = max_message_bytes
        self._cm: AbstractContextManager[ClientConnection] | None = None
        self._conn: ClientConnection | None = None

    def connect(self, handshake: Handshake) -> None:
        if self._conn is not None:
            raise LiveBookError("WebsocketsTransport.connect called while already connected")
        try:
            self._cm = connect(
                handshake.url,
                additional_headers=list(handshake.headers.items()),
                open_timeout=self._open_timeout,
                close_timeout=self._close_timeout,
                max_size=self._max_message_bytes,
            )
            self._conn = self._cm.__enter__()
        except (OSError, ConnectionClosed, TimeoutError) as exc:
            self._cm = None
            raise TransportClosed(f"connect failed: {exc!r}") from exc

    def send(self, text: str) -> None:
        conn = self._require_conn()
        try:
            conn.send(text)
        except ConnectionClosed as exc:
            self._release()
            raise TransportClosed(f"send after close: {exc!r}") from exc

    def receive(self) -> str:
        conn = self._require_conn()
        try:
            message = conn.recv(timeout=self._recv_timeout)
        except TimeoutError as exc:
            self._release()
            raise TransportClosed(f"no frame within recv_timeout: {exc!r}") from exc
        except ConnectionClosed as exc:
            self._release()
            raise TransportClosed(f"connection closed: {exc!r}") from exc
        if isinstance(message, bytes):
            return message.decode("utf-8")
        return message

    def close(self) -> None:
        self._release()

    def _release(self) -> None:
        """Drop the connection handle (idempotent). After a closed / timed-out
        connection surfaces as :class:`TransportClosed`, the socket is unusable
        and :class:`~.transport.LiveBookConnection` reconnects — which calls
        :meth:`connect` again, so ``_conn`` must be cleared here or that raises
        "already connected"."""
        cm, self._cm, self._conn = self._cm, None, None
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except (ConnectionClosed, OSError, TimeoutError):  # pragma: no cover - already gone
                pass

    def _require_conn(self) -> ClientConnection:
        if self._conn is None:
            raise LiveBookError("WebsocketsTransport used before connect()")
        return self._conn
