"""Deterministic tests for ``scripts/observe_kalshi_demo_shard_transfer.py``.

Network is never touched — the shared GET helper
(``observe_kalshi_demo_shard_balance._request``) and ``keychain_key_id`` are
stubbed. The properties pinned here: the probe is **GET-only** (no `POST` to any
transfer / allocation endpoint), it hits exactly the documented read-only
diagnosis endpoints, and only the public ``/exchange/status`` body is kept
verbatim (every account body goes through the D-024 sanitiser).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import observe_kalshi_demo as obs
import observe_kalshi_demo_shard_balance as shbal
import observe_kalshi_demo_shard_transfer as st

_EXPECTED = {
    ("GET", "/exchange/status"),
    ("GET", "/portfolio/balance"),
    ("GET", "/portfolio/intra_exchange_instance_transfers"),
    ("GET", "/portfolio/target_balance_allocation"),
}


def test_probe_is_get_only_and_hits_the_documented_readonly_endpoints(
    monkeypatch: Any, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, dict[str, Any] | None, str | None]] = []

    def fake_request(
        path: str, query: dict[str, Any] | None, key_id: str | None
    ) -> dict[str, Any]:
        calls.append(("GET", path, query, key_id))
        body = {"exchange_active": True} if path == "/exchange/status" else {"balance": 1}
        return {"request": {"method": "GET", "path": path, "query": query or {}},
                "status": 200, "headers": {}, "body": body}

    monkeypatch.setattr(shbal, "_request", fake_request)
    monkeypatch.setattr(obs, "keychain_key_id", lambda: "demo-key-id")
    monkeypatch.setattr(st, "OUT_DIR", tmp_path)

    assert st.observe() == 0

    # Every probe is a GET; the plan hits exactly the documented read-only set.
    assert all(m == "GET" for m, _p, _q, _k in calls)
    assert {(m, p) for m, p, _q, _k in calls} == _EXPECTED
    # `/exchange/status` is the only unauthenticated probe; it is never the
    # write path `/portfolio/intra_exchange_instance_transfer` (singular).
    for _m, path, _q, key_id in calls:
        assert (key_id is None) == (path == "/exchange/status")
        assert not path.endswith("/intra_exchange_instance_transfer")


def test_only_exchange_status_body_is_kept_verbatim(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_request(
        path: str, query: dict[str, Any] | None, key_id: str | None
    ) -> dict[str, Any]:
        if path == "/exchange/status":
            body: dict[str, Any] = {
                "exchange_active": True,
                "exchange_index_statuses": [{"description": "Demo shard 1"}],
            }
        else:
            body = {
                "transfers": [
                    {"transfer_id": "abc123", "amount": "10.0000", "status": "pending"}
                ]
            }
        return {"request": {"method": "GET", "path": path, "query": query or {}},
                "status": 200, "headers": {}, "body": body}

    monkeypatch.setattr(shbal, "_request", fake_request)
    monkeypatch.setattr(obs, "keychain_key_id", lambda: "demo-key-id")
    monkeypatch.setattr(st, "OUT_DIR", tmp_path)
    st.observe()

    status_body = json.loads((tmp_path / "exchange_status.json").read_text())["body"]
    assert status_body["exchange_index_statuses"][0]["description"] == "Demo shard 1"

    xfer_body = json.loads(
        (tmp_path / "intra_exchange_instance_transfers.json").read_text()
    )["body"]
    row = xfer_body["transfers"][0]
    assert row["transfer_id"] == "<redacted>"  # account-specific id redacted
    assert row["amount"] == "<redacted>"  # amount redacted
    assert row["status"] == "pending"  # enum constant kept (shape evidence)
