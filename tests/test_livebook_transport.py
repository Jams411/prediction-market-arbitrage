"""Deterministic tests for the M2.1 transport boundary: backoff, frame decoders,
and the connect / subscribe / pump / reconnect / resync manager driven with
in-memory fakes.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from livebook_support import (
    T0,
    FakeSnapshotSource,
    FakeWebSocketTransport,
    RecordingSleep,
    kalshi_contract,
    kalshi_delta_frame,
    kalshi_snapshot_frame,
    levels,
    poly_contract,
    poly_market_data_frame,
)

from prediction_market_arbitrage.livebook import (
    BackoffPolicy,
    BookSnapshot,
    Handshake,
    HealthStatus,
    LiveBookConnection,
    LiveBookError,
    LiveBookFeed,
    TransportClosed,
    kalshi_frame_decoder,
    kalshi_subscribe_command,
    polymarket_us_frame_decoder,
)

D = Decimal
STALE = timedelta(seconds=30)


def _clock():  # type: ignore[no-untyped-def]
    return T0


# --------------------------------------------------------------------------- #
# BackoffPolicy
# --------------------------------------------------------------------------- #


def test_backoff_is_exponential_and_capped() -> None:
    policy = BackoffPolicy(base_seconds=1.0, factor=2.0, max_seconds=10.0)
    assert [policy.delay(a) for a in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


def test_backoff_give_up_honours_max_attempts() -> None:
    policy = BackoffPolicy(max_attempts=3)
    assert [policy.give_up(a) for a in range(5)] == [False, False, False, True, True]
    assert BackoffPolicy(max_attempts=None).give_up(999) is False


def test_backoff_rejects_bad_config() -> None:
    with pytest.raises(LiveBookError):
        BackoffPolicy(base_seconds=0)
    with pytest.raises(LiveBookError):
        BackoffPolicy(base_seconds=5, max_seconds=1)


# --------------------------------------------------------------------------- #
# Frame decoders
# --------------------------------------------------------------------------- #


def test_kalshi_frame_decoder_routes_by_type() -> None:
    snap_updates = kalshi_frame_decoder(
        kalshi_snapshot_frame(seq=2, yes_fp=[("0.20", "5")], no_fp=[("0.50", "3")])
    )
    assert {u.contract_id for u in snap_updates} == {
        "LIVEBOOK-TEST-T1:YES",
        "LIVEBOOK-TEST-T1:NO",
    }
    assert kalshi_frame_decoder({"type": "ok", "id": 1, "sid": 3, "seq": 2}) == []
    assert kalshi_frame_decoder({"type": "error", "msg": {"code": 8}}) == []


def test_polymarket_us_frame_decoder_routes_market_data_only() -> None:
    updates = polymarket_us_frame_decoder(
        poly_market_data_frame(bids=[("0.55", "1")], offers=[("0.56", "1")])
    )
    assert [u.contract_id for u in updates] == ["livebook-test-market:LONG"]
    assert polymarket_us_frame_decoder({"subscriptionType": "SUBSCRIPTION_TYPE_TRADE"}) == []
    assert polymarket_us_frame_decoder({"requestId": "x"}) == []


# --------------------------------------------------------------------------- #
# LiveBookConnection — Kalshi (snapshot + delta, two feeds)
# --------------------------------------------------------------------------- #


def _kalshi_conn(
    transport: FakeWebSocketTransport,
    snapshots: FakeSnapshotSource,
    *,
    backoff: BackoffPolicy | None = None,
) -> tuple[LiveBookConnection, LiveBookFeed, LiveBookFeed]:
    yes = LiveBookFeed(contract=kalshi_contract("YES"), venue="kalshi", max_staleness=STALE)
    no = LiveBookFeed(contract=kalshi_contract("NO"), venue="kalshi", max_staleness=STALE)
    conn = LiveBookConnection(
        venue="kalshi",
        feeds=[yes, no],
        transport=transport,
        handshake_factory=lambda: Handshake(url="wss://x/trade-api/ws/v2", headers={}),
        subscribe_command=kalshi_subscribe_command(
            command_id=1, market_tickers=["LIVEBOOK-TEST-T1"]
        ),
        decode=kalshi_frame_decoder,
        snapshot_source=snapshots,
        clock=_clock,
        backoff=backoff,
    )
    return conn, yes, no


def test_connect_and_subscribe_sends_the_subscribe_json() -> None:
    transport = FakeWebSocketTransport()
    conn, _, _ = _kalshi_conn(transport, FakeSnapshotSource({}))
    conn.connect_and_subscribe()
    assert len(transport.connected_with) == 1
    assert json.loads(transport.sent[0]) == {
        "id": 1,
        "cmd": "subscribe",
        "params": {"channels": ["orderbook_delta"], "market_tickers": ["LIVEBOOK-TEST-T1"]},
    }


def test_pump_routes_snapshot_then_delta_to_the_right_feeds() -> None:
    transport = FakeWebSocketTransport(
        inbound=[
            json.dumps({"type": "ok", "id": 1}),
            json.dumps(
                kalshi_snapshot_frame(seq=2, yes_fp=[("0.20", "100")], no_fp=[("0.50", "40")])
            ),
            json.dumps(
                kalshi_delta_frame(seq=3, side="yes", price_dollars="0.2000", delta_fp="25.00")
            ),
        ]
    )
    conn, yes, no = _kalshi_conn(transport, FakeSnapshotSource({}))
    conn.connect_and_subscribe()

    assert conn.pump_one() == ()  # the "ok" ack
    applied = conn.pump_one()  # snapshot -> both feeds
    assert {u.contract_id for u in applied} == {"LIVEBOOK-TEST-T1:YES", "LIVEBOOK-TEST-T1:NO"}
    assert conn.all_healthy() is True

    conn.pump_one()  # yes delta +25 -> YES bid 100->125, NO ask (0.80) 100->125
    ob = yes.current_order_book(T0)
    assert ob is not None and ob.bids[0].quantity == D("125.00")
    assert no.current_order_book(T0) is not None


def test_disconnect_marks_every_feed_unhealthy() -> None:
    transport = FakeWebSocketTransport(
        inbound=[
            json.dumps(
                kalshi_snapshot_frame(seq=2, yes_fp=[("0.20", "1")], no_fp=[("0.50", "1")])
            ),
        ]
    )
    conn, yes, no = _kalshi_conn(transport, FakeSnapshotSource({}))
    conn.connect_and_subscribe()
    conn.pump_one()
    assert conn.all_healthy() is True

    with pytest.raises(TransportClosed):
        conn.pump_one()  # script exhausted
    conn.handle_disconnect()
    assert yes.health(T0).status is HealthStatus.DISCONNECTED
    assert no.health(T0).status is HealthStatus.DISCONNECTED
    assert conn.all_healthy() is False


def test_reconnect_backs_off_then_resync_restores_health() -> None:
    # First two connect attempts drop; third succeeds.
    class FlakyTransport(FakeWebSocketTransport):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def connect(self, handshake: Handshake) -> None:
            self.attempts += 1
            if self.attempts < 3:
                raise TransportClosed("connect failed")
            super().connect(handshake)

    transport = FlakyTransport()
    snapshots = FakeSnapshotSource(
        {
            "LIVEBOOK-TEST-T1:YES": BookSnapshot(
                venue="kalshi",
                contract_id="LIVEBOOK-TEST-T1:YES",
                bids=levels([("0.30", "10")]),
                asks=levels([("0.40", "10")]),
                sequence=99,
                source_time=None,
            ),
            "LIVEBOOK-TEST-T1:NO": BookSnapshot(
                venue="kalshi",
                contract_id="LIVEBOOK-TEST-T1:NO",
                bids=levels([("0.60", "10")]),
                asks=levels([("0.70", "10")]),
                sequence=99,
                source_time=None,
            ),
        }
    )
    conn, yes, no = _kalshi_conn(
        transport, snapshots, backoff=BackoffPolicy(base_seconds=1, factor=2, max_seconds=10)
    )
    sleep = RecordingSleep()

    succeeded_on = conn.reconnect(sleep)
    assert succeeded_on == 2
    assert sleep.calls == [1.0, 2.0]

    health = conn.resync()
    assert snapshots.fetched == ["LIVEBOOK-TEST-T1:YES", "LIVEBOOK-TEST-T1:NO"]
    assert all(h.status is HealthStatus.HEALTHY for h in health.values())
    assert yes.last_sequence == 99 and no.last_sequence == 99


def test_reconnect_gives_up_after_max_attempts() -> None:
    class DeadTransport(FakeWebSocketTransport):
        def connect(self, handshake: Handshake) -> None:
            raise TransportClosed("always down")

    conn, _, _ = _kalshi_conn(
        DeadTransport(), FakeSnapshotSource({}), backoff=BackoffPolicy(max_attempts=2)
    )
    with pytest.raises(TransportClosed):
        conn.reconnect(RecordingSleep())


def test_run_forever_pumps_reconnects_and_resyncs_within_a_bounded_loop() -> None:
    snap_yes = kalshi_snapshot_frame(seq=2, yes_fp=[("0.20", "5")], no_fp=[("0.50", "5")])
    transport = FakeWebSocketTransport(
        inbound=[json.dumps(snap_yes), TransportClosed]  # one good frame, then a drop
    )
    resync = {
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
    conn, yes, _ = _kalshi_conn(
        transport, FakeSnapshotSource(resync), backoff=BackoffPolicy(base_seconds=1)
    )
    steps = {"n": 0}

    def should_continue() -> bool:
        steps["n"] += 1
        return steps["n"] <= 3  # 1st pump ok, 2nd raises -> reconnect+resync, then stop

    conn.run_forever(RecordingSleep(), should_continue=should_continue)
    ob = yes.current_order_book(T0)
    assert ob is not None and ob.bids[0].price == D("0.21")  # resync snapshot applied
    assert yes.last_sequence == 50


def test_connection_rejects_feed_from_another_venue() -> None:
    poly_feed = LiveBookFeed(
        contract=poly_contract("LONG"), venue="polymarket_us", max_staleness=STALE
    )
    with pytest.raises(LiveBookError, match="does not match connection venue"):
        LiveBookConnection(
            venue="kalshi",
            feeds=[poly_feed],
            transport=FakeWebSocketTransport(),
            handshake_factory=lambda: Handshake(url="wss://x", headers={}),
            subscribe_command={},
            decode=kalshi_frame_decoder,
            snapshot_source=FakeSnapshotSource({}),
            clock=_clock,
        )
