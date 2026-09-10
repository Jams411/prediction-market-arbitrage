"""Deterministic offline tests for the concrete Kalshi **DEMO** REST transport
(M3.6). Every HTTP call is an injected fake :class:`HttpSender`; the RSA-PSS
signature is a fake :class:`Signer`. No network.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest
from demo_execution_support import DEMO_URL, PROD_URL, T0

from prediction_market_arbitrage.demo_execution import (
    DemoExecutionError,
    DemoExecutionOrchestrator,
    DemoHostError,
    DemoResponse,
    DemoTransportError,
    HttpRequest,
    HttpResponse,
    KalshiDemoLiveBroker,
    KalshiDemoRestTransport,
    urllib_sender,
)
from prediction_market_arbitrage.live_broker import REQUIRED_PHRASE, LiveTradingGate
from prediction_market_arbitrage.live_broker.models import LiveOrderRequest
from prediction_market_arbitrage.recorder import Recorder
from prediction_market_arbitrage.risk import RiskLimits, RiskManager

KEY_ID = "demo-key-id-abcd"
SIG_BYTES = b"\x01\x02\x03fake-sig"
FIXED_CLOCK = 1_700_000_000.5  # -> timestamp_ms "1700000000500"
TS_MS = "1700000000500"
_CID = "KXDEMO-T1:YES"


class FakeSigner:
    def __init__(self, signature: bytes = SIG_BYTES) -> None:
        self._sig = signature
        self.messages: list[bytes] = []

    def sign(self, message: bytes) -> bytes:
        self.messages.append(message)
        return self._sig


class FakeSender:
    """Records every request; returns scripted responses (by call order, else a
    default 200)."""

    def __init__(self, *responses: HttpResponse, default: HttpResponse | None = None) -> None:
        self._queue = list(responses)
        self._default = default or HttpResponse(200, b"{}")
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest, *, timeout: float) -> HttpResponse:
        self.requests.append(request)
        return self._queue.pop(0) if self._queue else self._default


class RaisingSender:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __call__(self, request: HttpRequest, *, timeout: float) -> HttpResponse:
        raise self._exc


def _req_json(req: HttpRequest) -> dict[str, object]:
    assert req.body is not None
    result: dict[str, object] = json.loads(req.body)
    return result


def _transport(
    sender: FakeSender | RaisingSender, *, base_url: str = DEMO_URL
) -> tuple[KalshiDemoRestTransport, FakeSigner]:
    signer = FakeSigner()
    tr = KalshiDemoRestTransport(
        base_url=base_url,
        api_key_id=KEY_ID,
        signer=signer,
        http=sender,
        clock=lambda: FIXED_CLOCK,
    )
    return tr, signer


# --------------------------------------------------------------------- #
# host guard
# --------------------------------------------------------------------- #


def test_demo_host_is_accepted() -> None:
    tr, _ = _transport(FakeSender())
    assert tr.base_url == DEMO_URL


@pytest.mark.parametrize("url", [PROD_URL, "https://api.kalshi.com/trade-api/v2", "", "ftp://x"])
def test_production_or_bad_host_is_rejected_at_construction(url: str) -> None:
    with pytest.raises(DemoHostError):
        KalshiDemoRestTransport(base_url=url, api_key_id=KEY_ID, signer=FakeSigner())


def test_empty_api_key_id_is_rejected() -> None:
    with pytest.raises(DemoExecutionError):
        KalshiDemoRestTransport(base_url=DEMO_URL, api_key_id="  ", signer=FakeSigner())


# --------------------------------------------------------------------- #
# exact signed request construction
# --------------------------------------------------------------------- #


def test_create_order_signs_the_exact_string_and_sets_the_three_headers() -> None:
    sender = FakeSender(
        HttpResponse(201, b'{"order_id":"o1","fill_count":"0","remaining_count":"1"}')
    )
    tr, signer = _transport(sender)

    resp = tr.create_order({"ticker": "KXDEMO-T1", "side": "bid", "count": "1"})

    assert signer.messages == [b"1700000000500POST/trade-api/v2/portfolio/events/orders"]
    (req,) = sender.requests
    assert req.method == "POST"
    assert req.url == f"{DEMO_URL}/portfolio/events/orders"  # no query on POST
    assert req.headers["KALSHI-ACCESS-KEY"] == KEY_ID
    assert req.headers["KALSHI-ACCESS-TIMESTAMP"] == TS_MS
    assert req.headers["KALSHI-ACCESS-SIGNATURE"] == base64.b64encode(SIG_BYTES).decode()
    assert req.headers["Content-Type"] == "application/json"
    assert _req_json(req) == {"ticker": "KXDEMO-T1", "side": "bid", "count": "1"}
    assert resp == DemoResponse(201, {"order_id": "o1", "fill_count": "0", "remaining_count": "1"})


def test_get_and_delete_sign_the_path_without_the_query_string() -> None:
    sender = FakeSender(
        HttpResponse(
            200,
            b'{"order":{"status":"resting","fill_count_fp":"0","remaining_count_fp":"1"}}',
        ),
        HttpResponse(200, b'{"order_id":"o1","reduced_by":"1","ts_ms":1}'),
    )
    tr, signer = _transport(sender)

    tr.get_order("ord-123", market_ticker="KXDEMO-T1")
    tr.cancel_order("ord-123", market_ticker="KXDEMO-T1")

    assert signer.messages == [
        b"1700000000500GET/trade-api/v2/portfolio/orders/ord-123",
        b"1700000000500DELETE/trade-api/v2/portfolio/events/orders/ord-123",
    ]
    assert sender.requests[0].url == f"{DEMO_URL}/portfolio/orders/ord-123?market_ticker=KXDEMO-T1"
    assert sender.requests[1].url == (
        f"{DEMO_URL}/portfolio/events/orders/ord-123?market_ticker=KXDEMO-T1"
    )
    assert sender.requests[0].body is None


def test_positions_and_fills_are_signed_get_requests() -> None:
    sender = FakeSender(
        HttpResponse(200, b'{"market_positions":[],"event_positions":[],"cursor":""}'),
        HttpResponse(200, b'{"fills":[],"cursor":""}'),
    )
    tr, signer = _transport(sender)
    pos = tr.get_positions()
    fills = tr.get_fills()
    assert signer.messages == [
        b"1700000000500GET/trade-api/v2/portfolio/positions",
        b"1700000000500GET/trade-api/v2/portfolio/fills",
    ]
    assert pos.body["market_positions"] == []
    assert fills.body["fills"] == []


# --------------------------------------------------------------------- #
# response parsing / fail-closed
# --------------------------------------------------------------------- #


def test_non_2xx_status_flows_through_as_a_demo_response_not_an_exception() -> None:
    sender = FakeSender(
        HttpResponse(401, b'{"error":{"code":"authentication_error","message":"nope"}}')
    )
    tr, _ = _transport(sender)
    resp = tr.get_positions()
    assert resp.status == 401 and resp.ok is False
    assert resp.body["error"]["code"] == "authentication_error"


def test_409_conflict_flows_through_for_the_broker_to_map() -> None:
    sender = FakeSender(HttpResponse(409, b'{"error":{"code":"c","message":"m"}}'))
    tr, _ = _transport(sender)
    assert tr.create_order({"ticker": "T"}).status == 409


@pytest.mark.parametrize("raw", [b"", b"not json at all", b"[1,2,3]", b'"a string"', b"null"])
def test_malformed_or_non_object_body_becomes_empty_dict(raw: bytes) -> None:
    sender = FakeSender(HttpResponse(200, raw))
    tr, _ = _transport(sender)
    assert tr.get_order("x", market_ticker="T") == DemoResponse(200, {})


def test_transport_failure_raises_demo_transport_error_without_leaking_secrets() -> None:
    tr, _ = _transport(RaisingSender(ConnectionResetError("boom")))
    with pytest.raises(DemoTransportError) as exc:
        tr.create_order({"ticker": "T"})
    text = str(exc.value)
    assert "POST" in text and "/portfolio/events/orders" in text
    assert KEY_ID not in text
    assert base64.b64encode(SIG_BYTES).decode() not in text
    assert "boom" not in text  # underlying message not echoed


def test_urllib_sender_maps_url_and_timeout_errors_to_demo_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    def _boom(*_a: object, **_k: object) -> object:
        raise urllib.error.URLError("dns")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    req = HttpRequest("GET", f"{DEMO_URL}/portfolio/positions", {}, None)
    with pytest.raises(DemoTransportError) as exc:
        urllib_sender(req, timeout=1.0)
    assert "/portfolio/positions" in str(exc.value)
    assert "dns" not in str(exc.value)


def test_urllib_sender_returns_http_error_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    import email.message
    import io
    import urllib.error

    def _http_error(*_a: object, **_k: object) -> object:
        raise urllib.error.HTTPError(
            "u", 429, "Too Many Requests", email.message.Message(),
            io.BytesIO(b'{"error":"too many requests"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _http_error)
    resp = urllib_sender(HttpRequest("GET", f"{DEMO_URL}/x", {}, None), timeout=1.0)
    assert resp.status == 429 and b"too many requests" in resp.body


# --------------------------------------------------------------------- #
# through the real broker + orchestrator (still offline)
# --------------------------------------------------------------------- #


def _orch(sender: FakeSender):  # type: ignore[no-untyped-def]
    tr, _ = _transport(sender)
    broker = KalshiDemoLiveBroker(
        tr, gate=LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE)
    )
    rec = Recorder.open(":memory:", session_id="demo", opened_at=T0)
    orch = DemoExecutionOrchestrator(
        broker=broker, risk=RiskManager(RiskLimits()), recorder=rec, clock=lambda: T0
    )
    return orch, rec


def _intent(client_order_id: str = "pma-demo-1") -> LiveOrderRequest:
    return LiveOrderRequest(
        client_order_id=client_order_id,
        venue="kalshi",
        contract_id=_CID,
        side="buy",
        order_type="limit",
        quantity=Decimal("1"),
        limit_price=Decimal("0.05"),
        time_in_force="gtc",
    )


def test_create_order_body_shape_through_the_real_transport() -> None:
    sender = FakeSender(
        HttpResponse(201, b'{"order_id":"o1","fill_count":"0","remaining_count":"1"}')
    )
    orch, _ = _orch(sender)
    outcome = orch.execute(_intent("shape-1"))
    assert outcome.submitted is True
    body = _req_json(sender.requests[0])
    assert set(body) == {
        "ticker",
        "side",
        "count",
        "price",
        "time_in_force",
        "self_trade_prevention_type",
        "client_order_id",
    }
    assert body["ticker"] == "KXDEMO-T1"
    assert body["side"] == "bid"
    assert body["count"] == "1"
    assert body["price"] == "0.05"
    assert body["time_in_force"] == "good_till_canceled"
    assert body["client_order_id"] == "shape-1"


def test_duplicate_intent_cannot_issue_a_second_create_through_the_real_transport() -> None:
    sender = FakeSender(
        HttpResponse(201, b'{"order_id":"o1","fill_count":"0","remaining_count":"1"}')
    )
    orch, _ = _orch(sender)
    assert orch.execute(_intent("dup-1")).submitted is True
    second = orch.execute(_intent("dup-1"))
    assert second.submitted is False and second.duplicate is True
    posts = [r for r in sender.requests if r.method == "POST"]
    assert len(posts) == 1


def test_reconcile_is_deterministic_with_fake_venue_state_through_the_real_transport() -> None:
    def run() -> tuple[object, ...]:
        sender = FakeSender(
            HttpResponse(201, b'{"order_id":"o1","fill_count":"0","remaining_count":"1"}'),
            HttpResponse(
                200,
                b'{"order":{"status":"resting","fill_count_fp":"0","remaining_count_fp":"1"}}',
            ),
            HttpResponse(200, b'{"market_positions":[],"event_positions":[],"cursor":""}'),
        )
        orch, rec = _orch(sender)
        outcome = orch.reconcile(orch.execute(_intent("det-1")))
        rows = rec.connection.execute(
            "SELECT status, reason FROM order_events ORDER BY id"
        ).fetchall()
        return (outcome.to_evidence_dict(), rows)

    assert run() == run()
