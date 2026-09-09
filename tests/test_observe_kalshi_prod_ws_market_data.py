"""Deterministic, offline tests for
``scripts/observe_kalshi_prod_ws_market_data.py``.

No socket is ever opened and no real credential is read: the WebSocket
transport, the Keychain lookup, and the public REST helper are all stubbed. The
properties pinned here are the ones that make this a *safe, read-only*
observation script — no account/order code path, ``--check`` never connects,
``--observe`` refuses without the env guard, and the stream consumer only sends
``subscribe`` frames and only records sanitised structure.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import observe_kalshi_prod_ws_market_data as obs
import pytest

from prediction_market_arbitrage.livebook import TransportClosed

SOURCE = Path(obs.__file__).read_text()


def _string_literals_in_code() -> list[str]:
    """Every string-constant value in the module, minus the module docstring and
    the ``_FORBIDDEN_PATH_MARKERS`` definition itself. A forbidden path appearing
    in one of these would be a real request target."""
    tree = ast.parse(SOURCE)
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # drop module docstring
    forbidden_def_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_FORBIDDEN_PATH_MARKERS" for t in node.targets
        ):
            forbidden_def_lines = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    out: list[str] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.lineno not in forbidden_def_lines
            ):
                out.append(node.value)
    return out



SNAPSHOT_FRAME = {
    "type": "orderbook_snapshot",
    "sid": 2,
    "seq": 1,
    "msg": {
        "market_ticker": "KXBTCD-26SEP0904-T84299.99",
        "market_id": "1f0e8a00-0000-0000-0000-000000000000",
        "yes_dollars_fp": [["0.0800", "300.00"], ["0.2200", "333.00"]],
        "no_dollars_fp": [["0.5400", "20.00"]],
    },
}
DELTA_FRAME = {
    "type": "orderbook_delta",
    "sid": 2,
    "seq": 2,
    "msg": {
        "market_ticker": "KXBTCD-26SEP0904-T84299.99",
        "market_id": "1f0e8a00-0000-0000-0000-000000000000",
        "price_dollars": "0.960",
        "delta_fp": "-54.00",
        "side": "yes",
        "ts_ms": 1669149841000,
    },
}


class FakeTransport:
    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []
        self.closed = False

    def send(self, text: str) -> None:
        self.sent.append(text)

    def receive(self) -> str:
        if not self._frames:
            raise TransportClosed("no more frames")
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------- #
# Static safety properties
# --------------------------------------------------------------------------- #


def test_uses_the_shipped_production_ws_url() -> None:
    assert obs.PROD_WS_URL == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"


def test_no_account_or_order_path_literal_in_code() -> None:
    """No string literal that looks like a URL or request path references an
    account / order / trading endpoint."""
    pathy = [
        s for s in _string_literals_in_code()
        if "://" in s or s.strip().startswith("/")
    ]
    assert pathy, "expected at least the /markets and ws paths"
    for literal in pathy:
        low = literal.lower()
        for marker in obs._FORBIDDEN_PATH_MARKERS:
            assert marker not in low, f"forbidden path {marker!r} in literal {literal!r}"
        assert "polymarket" not in low


def test_public_rest_base_is_unauthenticated_prod_host() -> None:
    assert obs.PUBLIC_REST_BASE == "https://external-api.kalshi.com/trade-api/v2"


def test_no_trading_identifiers_or_imports_in_code() -> None:
    tree = ast.parse(SOURCE)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "LIVE_TRADING" not in names | attrs
    assert not any(w in names | attrs for w in ("place_order", "cancel_order", "submit"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("live_broker" in m or "trading" in m for m in imported)


# --------------------------------------------------------------------------- #
# --check / --observe entry point
# --------------------------------------------------------------------------- #


def _stub_preflight(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    report = {
        "openssl_on_path": True,
        "private_key_file_present": False,
        "private_key_path": "/x/kalshi-prod-private-key.pem",
        "keychain_key_id": "absent",
        "env_guard_set": False,
        "ready": False,
    }
    report.update(overrides)
    monkeypatch.setattr(obs, "preflight", lambda: report)


def test_check_mode_never_opens_a_socket(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    _stub_preflight(monkeypatch)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("run_observation must not be called in --check mode")

    monkeypatch.setattr(obs, "run_observation", boom)
    assert obs.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "Account & security" in out and "Create Key" in out


def test_check_is_the_default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch)
    monkeypatch.setattr(obs, "run_observation", lambda: (_ for _ in ()).throw(AssertionError()))
    assert obs.main([]) == 0


def test_observe_refuses_without_env_guard(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    _stub_preflight(monkeypatch, ready=True, env_guard_set=False)
    monkeypatch.setattr(obs, "run_observation", lambda: (_ for _ in ()).throw(AssertionError()))
    assert obs.main(["--observe"]) == 2
    assert "PMA_KALSHI_PROD_WS_OBSERVE=1" in capsys.readouterr().err


def test_observe_refuses_when_preflight_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch, ready=False, env_guard_set=True)
    monkeypatch.setattr(obs, "run_observation", lambda: (_ for _ in ()).throw(AssertionError()))
    assert obs.main(["--observe"]) == 2


def test_observe_runs_when_ready_and_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_preflight(monkeypatch, ready=True, env_guard_set=True)
    monkeypatch.setattr(obs, "run_observation", lambda: 0)
    assert obs.main(["--observe"]) == 0


# --------------------------------------------------------------------------- #
# consume_book_stream
# --------------------------------------------------------------------------- #


def test_consume_book_stream_records_snapshot_delta_and_seq() -> None:
    transport = FakeTransport([json.dumps(SNAPSHOT_FRAME), json.dumps(DELTA_FRAME)])
    result = obs.consume_book_stream(
        transport, command_id=7, market_ticker="KX-TEST", want_deltas=1, max_frames=50
    )
    assert result["snapshots"] == 1
    assert result["deltas"] == 1
    assert result["seq_values"] == [1, 2]
    assert result["seq_strictly_increasing"] is True

    # Exactly one subscribe frame, correct shape, no other sends.
    assert len(transport.sent) == 1
    cmd = json.loads(transport.sent[0])
    assert cmd == {
        "id": 7,
        "cmd": "subscribe",
        "params": {"channels": ["orderbook_delta"], "market_tickers": ["KX-TEST"]},
    }


def test_consume_book_stream_sanitises_every_scalar_leaf() -> None:
    transport = FakeTransport([json.dumps(SNAPSHOT_FRAME), json.dumps(DELTA_FRAME)])
    result = obs.consume_book_stream(
        transport, command_id=1, market_ticker="KX-TEST", want_deltas=1, max_frames=50
    )
    shape = result["first_delta_shape"]
    assert shape["type"] == "<redacted>"
    assert shape["seq"] == "<number>"
    assert shape["msg"]["price_dollars"] == "<redacted>"
    assert shape["msg"]["side"] == "<redacted>"
    # No real market identifier survives anywhere in the recorded structure.
    assert "KXBTCD-26SEP0904-T84299.99" not in json.dumps(result)


def test_consume_book_stream_stops_on_transport_closed() -> None:
    transport = FakeTransport([json.dumps(SNAPSHOT_FRAME)])  # then TransportClosed
    result = obs.consume_book_stream(
        transport, command_id=1, market_ticker="KX-TEST", want_deltas=5, max_frames=50
    )
    assert result["snapshots"] == 1
    assert result["deltas"] == 0


def test_sanitise_keeps_structure_drops_values() -> None:
    out = obs.sanitise({"a": 1, "b": "secret", "c": [1, 2, 3, 4], "d": None, "e": True})
    assert out == {"a": "<number>", "b": "<redacted>", "c": ["<number>", "<number>", "<...>"],
                   "d": None, "e": True}


# --------------------------------------------------------------------------- #
# pick_liquid_market — GET-only, /markets paths only
# --------------------------------------------------------------------------- #


def test_pick_liquid_market_is_get_only_markets_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get_json(url: str) -> dict[str, Any]:
        seen.append(url)
        if "/markets?" in url:
            return {"markets": [{"ticker": "KX-A", "market_type": "binary"}]}
        return {"orderbook_fp": {"yes_dollars": [["0.5", "1"]], "no_dollars": [["0.5", "1"]]}}

    monkeypatch.setattr(obs, "_get_json", fake_get_json)
    ticker = obs.pick_liquid_market()
    assert ticker == "KX-A"
    assert all("/markets" in u for u in seen)
    assert all("portfolio" not in u for u in seen)
