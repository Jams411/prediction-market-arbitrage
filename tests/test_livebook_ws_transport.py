"""Tests for the concrete ``WebsocketsTransport`` against a local ``websockets``
server on loopback (Milestone M2.1).

This is a real socket round-trip but fully offline and deterministic: the local
server accepts any handshake headers, so it is **not** evidence that a real
Kalshi / Polymarket US server accepts our handshake (A-030 stays unresolved).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from livebook_support import T0, kalshi_contract, kalshi_snapshot_frame, levels

from prediction_market_arbitrage.livebook import (
    BackoffPolicy,
    BookSnapshot,
    Handshake,
    HealthStatus,
    LiveBookConnection,
    LiveBookError,
    LiveBookFeed,
    TransportClosed,
    WebsocketsTransport,
    kalshi_frame_decoder,
    kalshi_subscribe_command,
)
from prediction_market_arbitrage.livebook.transport import SnapshotSource

websockets_server = pytest.importorskip("websockets.sync.server")

D = Decimal
STALE = timedelta(seconds=30)


@contextmanager
def local_server(handler: Callable[[object], None]) -> Iterator[str]:
    """Run ``handler`` as a websockets server on an ephemeral loopback port;
    yield the ``ws://`` URL."""
    server = websockets_server.serve(handler, "127.0.0.1", 0)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"ws://127.0.0.1:{port}/trade-api/ws/v2"
    finally:
        server.shutdown()
        thread.join(timeout=5)


class _StaticSnapshots:
    def __init__(self, snapshots: dict[str, BookSnapshot]) -> None:
        self._snapshots = snapshots

    def fetch(self, contract_id: str) -> BookSnapshot:
        return self._snapshots[contract_id]


def test_connect_send_receive_close_round_trip() -> None:
    seen: dict[str, object] = {}

    def handler(conn: object) -> None:
        seen["headers"] = {
            k: conn.request.headers.get(k)  # type: ignore[attr-defined]
            for k in ("KALSHI-ACCESS-KEY", "KALSHI-ACCESS-SIGNATURE", "KALSHI-ACCESS-TIMESTAMP")
        }
        seen["first"] = conn.recv()  # type: ignore[attr-defined]
        conn.send(json.dumps({"type": "ok", "id": 1}))  # type: ignore[attr-defined]
        conn.send('{"frame": 2}')  # type: ignore[attr-defined]
        conn.close()  # type: ignore[attr-defined]

    with local_server(handler) as url:
        transport = WebsocketsTransport(recv_timeout=5.0)
        transport.connect(
            Handshake(
                url=url,
                headers={
                    "KALSHI-ACCESS-KEY": "k-id",
                    "KALSHI-ACCESS-SIGNATURE": "sig",
                    "KALSHI-ACCESS-TIMESTAMP": "1769947200000",
                },
            )
        )
        transport.send("subscribe-payload")
        assert json.loads(transport.receive()) == {"type": "ok", "id": 1}
        assert transport.receive() == '{"frame": 2}'
        with pytest.raises(TransportClosed):
            transport.receive()  # server closed
        transport.close()

    assert seen["first"] == "subscribe-payload"
    assert seen["headers"] == {
        "KALSHI-ACCESS-KEY": "k-id",
        "KALSHI-ACCESS-SIGNATURE": "sig",
        "KALSHI-ACCESS-TIMESTAMP": "1769947200000",
    }


def test_receive_times_out_into_transport_closed() -> None:
    def handler(conn: object) -> None:
        # Hold the connection open without sending, until the client goes away.
        try:
            conn.recv()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - client closed
            pass

    with local_server(handler) as url:
        transport = WebsocketsTransport(recv_timeout=0.2)
        transport.connect(Handshake(url=url, headers={}))
        with pytest.raises(TransportClosed, match="recv_timeout"):
            transport.receive()
        transport.close()


def test_use_before_connect_and_double_connect_raise() -> None:
    transport = WebsocketsTransport()
    with pytest.raises(LiveBookError, match="before connect"):
        transport.receive()
    with pytest.raises(LiveBookError, match="before connect"):
        transport.send("x")


def test_connect_to_dead_address_raises_transport_closed() -> None:
    transport = WebsocketsTransport(open_timeout=0.5)
    with pytest.raises(TransportClosed, match="connect failed"):
        transport.connect(Handshake(url="ws://127.0.0.1:1/x", headers={}))


def test_live_book_connection_drives_real_transport_against_local_server() -> None:
    """The concrete transport plugs into the existing manager: connect →
    subscribe → snapshot → delta → HEALTHY, then server close → DISCONNECTED."""
    snap_frame = kalshi_snapshot_frame(
        seq=2, yes_fp=[("0.20", "100")], no_fp=[("0.50", "40")]
    )

    def handler(conn: object) -> None:
        conn.recv()  # type: ignore[attr-defined]  # the subscribe command
        conn.send(json.dumps({"type": "ok", "id": 1}))  # type: ignore[attr-defined]
        conn.send(json.dumps(snap_frame))  # type: ignore[attr-defined]
        conn.close()  # type: ignore[attr-defined]

    with local_server(handler) as url:
        yes = LiveBookFeed(contract=kalshi_contract("YES"), venue="kalshi", max_staleness=STALE)
        no = LiveBookFeed(contract=kalshi_contract("NO"), venue="kalshi", max_staleness=STALE)
        resync: dict[str, BookSnapshot] = {
            "LIVEBOOK-TEST-T1:YES": BookSnapshot(
                venue="kalshi",
                contract_id="LIVEBOOK-TEST-T1:YES",
                bids=levels([("0.21", "9")]),
                asks=levels([("0.41", "9")]),
                sequence=50,
                source_time=None,
            ),
            "LIVEBOOK-TEST-T1:NO": BookSnapshot(
                venue="kalshi",
                contract_id="LIVEBOOK-TEST-T1:NO",
                bids=levels([("0.59", "9")]),
                asks=levels([("0.79", "9")]),
                sequence=50,
                source_time=None,
            ),
        }
        conn = LiveBookConnection(
            venue="kalshi",
            feeds=[yes, no],
            transport=WebsocketsTransport(recv_timeout=5.0),
            handshake_factory=lambda: Handshake(url=url, headers={"KALSHI-ACCESS-KEY": "k"}),
            subscribe_command=kalshi_subscribe_command(
                command_id=1, market_tickers=["LIVEBOOK-TEST-T1"]
            ),
            decode=kalshi_frame_decoder,
            snapshot_source=_typed_source(_StaticSnapshots(resync)),
            clock=lambda: T0,
            backoff=BackoffPolicy(base_seconds=0.01, max_attempts=1),
        )
        conn.connect_and_subscribe()
        assert conn.pump_one() == ()  # ok ack
        conn.pump_one()  # snapshot -> both feeds
        assert conn.all_healthy() is True
        ob = yes.current_order_book(T0)
        assert ob is not None and ob.bids[0].quantity == D("100")

        with pytest.raises(TransportClosed):
            conn.pump_one()  # server closed
        conn.handle_disconnect()
        assert yes.health(T0).status is HealthStatus.DISCONNECTED


def _typed_source(source: _StaticSnapshots) -> SnapshotSource:
    return source
