"""Deterministic tests for ``scripts/observe_kalshi_demo_shard_balance.py``.

Network is never touched: ``urllib.request.urlopen`` and the RSA signer are
stubbed. The properties pinned here are the ones that matter for a *read-only*
observation script — GET only, demo base URL, the query string carried on the
URL but **excluded** from the signed message, and no auth headers on the public
``/exchange/status`` probe.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import observe_kalshi_demo as obs
import observe_kalshi_demo_shard_balance as sb


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status = 200
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.signed: list[str] = []

    def install(self, monkeypatch: Any, payload: dict[str, Any]) -> None:
        def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResponse:
            self.requests.append(req)
            return _FakeResponse(payload)

        def fake_sign(message: str) -> str:
            self.signed.append(message)
            return "fake-signature=="

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(obs, "sign", fake_sign)


def test_demo_base_url_and_shard_indexes() -> None:
    assert "demo" in sb.DEMO_BASE_URL
    assert sb.SHARD_INDEXES == (0, 1, 2, 3)


def test_authenticated_get_signs_path_only_query_stays_on_url(monkeypatch: Any) -> None:
    cap = _Capture()
    cap.install(monkeypatch, {"balance": 0})

    result = sb._request("/portfolio/balance", {"exchange_index": 1}, "demo-key-id")

    assert result["request"]["method"] == "GET"
    req = cap.requests[0]
    assert req.method == "GET"
    assert req.full_url.endswith("/portfolio/balance?exchange_index=1")
    # Signed message excludes the query string.
    assert cap.signed == [f"{cap_ts(req)}GET{sb.SIGN_PATH_PREFIX}/portfolio/balance"]
    assert "?" not in cap.signed[0]
    assert req.get_header("Kalshi-access-key") == "demo-key-id"


def cap_ts(req: Any) -> str:
    return str(req.get_header("Kalshi-access-timestamp"))


def test_public_exchange_status_probe_sends_no_auth_headers(monkeypatch: Any) -> None:
    cap = _Capture()
    cap.install(monkeypatch, {"exchange_active": True})

    sb._request("/exchange/status", None, None)

    assert cap.signed == []
    req = cap.requests[0]
    assert req.get_header("Kalshi-access-key") is None
    assert req.get_header("Kalshi-access-signature") is None
    assert req.full_url.endswith("/exchange/status")
