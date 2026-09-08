"""Deterministic tests for the request-body sanitiser in
``scripts/observe_kalshi_demo_order_lifecycle.py``.

The persisted request body must keep the known non-sensitive schema fields
(public ticker, order params) verbatim, replace ``client_order_id`` with a
fixed placeholder, and fall back to the D-024 fail-safe redactor for anything
unexpected.
"""

from __future__ import annotations

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
