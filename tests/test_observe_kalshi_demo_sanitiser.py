"""Deterministic tests for the structure-first fixture sanitiser in
``scripts/observe_kalshi_demo.py``.

The sanitiser must be *fail-safe*: it keeps JSON structure, every field name,
and a short allowlist of fixed API constants, and redacts every other body
scalar by default — including fields that did not exist when it was written.
"""

from __future__ import annotations

from typing import Any

import observe_kalshi_demo as obs


def test_allowlisted_constants_pass_through() -> None:
    body = {
        "cursor": "",
        "error": {
            "code": "authentication_error",
            "details": "INCORRECT_API_KEY_SIGNATURE",
            "message": "We could not authenticate your request",
        },
    }
    assert obs.sanitise_body(body) == body


def test_order_endpoint_error_constants_pass_through() -> None:
    # Added after the 2026-09-08 demo order-lifecycle attempt (K-TR-OBS-11/12).
    for code, message in (
        ("deprecated_v1_order_endpoint", "Please switch to the V2 endpoints"),
        ("user_not_found", "user not found"),
    ):
        body = {"error": {"code": code, "message": message, "details": "context-specific"}}
        assert obs.sanitise_body(body) == {
            "error": {"code": code, "message": message, "details": "<redacted>"}
        }


def test_transfer_enum_constants_pass_through_but_account_scalars_do_not() -> None:
    # Added for the 2026-09-08 demo shard-transfer diagnosis (K-TR-OBS-18):
    # GetIntraExchangeInstanceTransfersResponse rows.
    body = {
        "transfers": [
            {
                "transfer_id": "9f8e-0001",
                "source": "margined",
                "destination": "event_contract",
                "source_exchange_shard": 0,
                "destination_exchange_shard": 1,
                "amount": "10.0000",
                "status": "pending",
                "created_ts": 1788850000000,
            }
        ]
    }
    assert obs.sanitise_body(body) == {
        "transfers": [
            {
                "transfer_id": "<redacted>",
                "source": "margined",
                "destination": "event_contract",
                "source_exchange_shard": "<number>",
                "destination_exchange_shard": "<number>",
                "amount": "<redacted>",
                "status": "pending",
                "created_ts": "<number>",
            }
        ]
    }


def test_empty_containers_and_structure_preserved() -> None:
    body = {"cursor": "", "fills": [], "market_positions": [], "meta": {}}
    assert obs.sanitise_body(body) == body


def test_numbers_and_numeric_strings_are_redacted() -> None:
    body = {
        "balance": 123456,
        "balance_dollars": "1234.56",
        "portfolio_value": 0,
        "updated_ts": 1788849422,
    }
    assert obs.sanitise_body(body) == {
        "balance": "<number>",
        "balance_dollars": "<redacted>",
        "portfolio_value": "<number>",
        "updated_ts": "<number>",
    }


def test_nested_objects_and_lists_are_walked() -> None:
    body = {
        "market_positions": [
            {
                "ticker": "KXSECRET-25",
                "position": 7,
                "realized_pnl": "12.34",
                "fees_paid": 5,
            },
            {
                "ticker": "KXSECRET-26",
                "position": -3,
                "nested": {"lot_ids": ["a1", "b2"], "count": 2},
            },
        ],
        "cursor": "opaque-cursor-token",
    }
    assert obs.sanitise_body(body) == {
        "market_positions": [
            {
                "ticker": "<redacted>",
                "position": "<number>",
                "realized_pnl": "<redacted>",
                "fees_paid": "<number>",
            },
            {
                "ticker": "<redacted>",
                "position": "<number>",
                "nested": {"lot_ids": ["<redacted>", "<redacted>"], "count": "<number>"},
            },
        ],
        "cursor": "<redacted>",
    }


def test_unexpected_sensitive_fields_are_redacted_by_default() -> None:
    # None of these key names were anticipated by the original key-name denylist.
    body = {
        "member_id": "9f8e7d6c-0000-1111-2222-333344445555",
        "email": "trader@example.com",
        "client_order_id": "PMA-CLIENT-0001",
        "api_key_id": "kalshi-key-abcdef",
        "some_future_field": "sensitive-value",
        "deeply": {"nested": [{"unknown_scalar": "leak-me"}]},
    }
    out = obs.sanitise_body(body)
    assert out == {
        "member_id": "<redacted>",
        "email": "<redacted>",
        "client_order_id": "<redacted>",
        "api_key_id": "<redacted>",
        "some_future_field": "<redacted>",
        "deeply": {"nested": [{"unknown_scalar": "<redacted>"}]},
    }
    # Field names (structure) survive; no original value string remains anywhere.
    flat = repr(out)
    for secret in ("9f8e7d6c", "trader@example.com", "PMA-CLIENT-0001", "abcdef", "leak-me"):
        assert secret not in flat


def test_none_and_booleans_are_structural_and_kept() -> None:
    body: dict[str, Any] = {"is_taker": True, "resting": False, "expiration_ts": None}
    assert obs.sanitise_body(body) == body


def test_scalar_root_body_is_redacted() -> None:
    assert obs.sanitise_body("raw-string-body") == "<redacted>"
    assert obs.sanitise_body(42) == "<number>"
    assert obs.sanitise_body(None) is None


def test_unknown_error_strings_are_not_trusted() -> None:
    # A future error string not in the allowlist must still be redacted.
    body = {"error": {"code": "account_locked", "message": "Account 12345 is suspended"}}
    assert obs.sanitise_body(body) == {
        "error": {"code": "<redacted>", "message": "<redacted>"}
    }
