"""Deterministic tests for the request-body sanitiser in
``scripts/observe_kalshi_demo_order_lifecycle.py``.

The persisted request body must keep the known non-sensitive schema fields
(public ticker, order params) verbatim, replace ``client_order_id`` with a
fixed placeholder, and fall back to the D-024 fail-safe redactor for anything
unexpected. Also pins the shard-routing query param on ``request()``.
"""

from __future__ import annotations

import urllib.request
from typing import Any

import observe_kalshi_demo as obs
import observe_kalshi_demo_order_lifecycle as lc


def test_client_order_id_is_always_a_placeholder() -> None:
    out = lc._sanitise_request_body(
        {"client_order_id": "pma-demo-lc-1788881347", "ticker": "KXSYNTH-DEMO-1"}
    )
    assert out["client_order_id"] == "<demo-synthetic-client-order-id>"


def test_known_schema_fields_kept_verbatim() -> None:
    body = {
        "ticker": "KXSYNTH-DEMO-1",
        "side": "bid",
        "count": "1",
        "price": "0.01",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "maker",
        "post_only": True,
        "client_order_id": "pma-demo-lc-x",
    }
    out = lc._sanitise_request_body(body)
    assert out == {**body, "client_order_id": "<demo-synthetic-client-order-id>"}


def test_unexpected_request_field_is_redacted() -> None:
    out = lc._sanitise_request_body(
        {"ticker": "KXSYNTH-DEMO-1", "account_ref": "acct-12345", "nested": {"k": "v"}}
    )
    assert out["ticker"] == "KXSYNTH-DEMO-1"
    assert out["account_ref"] == "<redacted>"
    assert out["nested"] == {"k": "<redacted>"}


def test_order_body_constant_is_non_marketable_and_minimal() -> None:
    assert lc._ORDER_BODY["count"] == "1"
    assert lc._ORDER_BODY["price"] == "0.01"
    assert lc._ORDER_BODY["post_only"] is True
    assert "demo" in lc.DEMO_BASE_URL


class _FakeResp:
    status = 200
    headers = {"content-type": "application/json; charset=utf-8"}

    def read(self) -> bytes:
        return b'{"order_id": "x", "reduced_by": "1.00"}'

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_cancel_query_is_on_url_but_not_in_signed_message(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResp:
        seen["url"] = req.full_url
        seen["method"] = req.method
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(obs, "sign", lambda message: seen.setdefault("signed", message) or "sig==")

    rec = lc.request(
        "DELETE",
        "/portfolio/events/orders/abc",
        "key-id",
        query={"market_ticker": "KX-SHARD1-DEMO"},
    )

    assert seen["method"] == "DELETE"
    assert seen["url"].endswith("/portfolio/events/orders/abc?market_ticker=KX-SHARD1-DEMO")
    # Signed string is the bare path — no query.
    assert seen["signed"].endswith("DELETE/trade-api/v2/portfolio/events/orders/abc")
    assert "?" not in seen["signed"]
    # The query is recorded verbatim in the fixture record for traceability.
    assert rec["request"]["query"] == {"market_ticker": "KX-SHARD1-DEMO"}


def test_request_without_query_records_no_query_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResp())
    monkeypatch.setattr(obs, "sign", lambda message: "sig==")
    rec = lc.request("GET", "/portfolio/orders", "key-id")
    assert "query" not in rec["request"]


def test_order_id_is_scrubbed_from_persisted_paths() -> None:
    oid = "01a083c3-1f70-79cd-baf9-81d02246dbcf"
    steps = [
        ("00_orders_before", {"request": {"method": "GET", "path": "/portfolio/orders"}}),
        ("04_get_order", {"request": {"method": "GET", "path": f"/portfolio/orders/{oid}"}}),
        (
            "06_cancel",
            {"request": {"method": "DELETE", "path": f"/portfolio/events/orders/{oid}"}},
        ),
    ]
    lc._redact_order_id_in_paths(steps, oid)
    assert steps[0][1]["request"]["path"] == "/portfolio/orders"
    assert steps[1][1]["request"]["path"] == "/portfolio/orders/{order_id}"
    assert steps[2][1]["request"]["path"] == "/portfolio/events/orders/{order_id}"
    assert not any(oid in s[1]["request"]["path"] for s in steps)


def test_redact_order_id_is_a_noop_when_no_order_created() -> None:
    steps = [("x", {"request": {"method": "GET", "path": "/portfolio/orders"}})]
    lc._redact_order_id_in_paths(steps, None)
    assert steps[0][1]["request"]["path"] == "/portfolio/orders"
