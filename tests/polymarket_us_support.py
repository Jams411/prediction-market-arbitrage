"""Shared, offline test helpers for the Polymarket US adapter tests.

Not collected by pytest (no ``test_`` prefix). Deterministic fake transport and
fixture loader so the suite never touches the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from prediction_market_arbitrage.adapters.polymarket_us import HttpResponse

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "polymarket_us"


def load_fixture_bytes(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def load_fixture_json(name: str) -> dict[str, object]:
    parsed: object = json.loads(load_fixture_bytes(name))
    assert isinstance(parsed, dict)
    return parsed


def market_data(name: str) -> dict[str, object]:
    """Return the ``marketData`` object from a book/bbo fixture."""
    inner = load_fixture_json(name)["marketData"]
    assert isinstance(inner, dict)
    return inner


def market_object(name: str = "market_single.json") -> dict[str, object]:
    """Return the ``market`` object from a single-market fixture."""
    inner = load_fixture_json(name)["market"]
    assert isinstance(inner, dict)
    return inner


def json_response(status: int, payload: object) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(payload).encode())


@dataclass
class FakeTransport:
    """A :class:`~...polymarket_us.Transport` that replays canned responses by URL match."""

    routes: list[tuple[str, HttpResponse]] = field(default_factory=list)
    raises: BaseException | None = None
    calls: list[str] = field(default_factory=list)

    def request(self, method: str, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)
        if self.raises is not None:
            raise self.raises
        for needle, response in self.routes:
            if needle in url:
                return response
        raise AssertionError(f"FakeTransport: no route configured for {url!r}")
