"""Minimal HTTP transport for the Kalshi adapter.

Uses only the standard library (``urllib``) so the project keeps its zero
runtime-dependency posture. The :class:`Transport` protocol is the seam that
tests substitute with a deterministic fake — no network access in the test suite.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .errors import KalshiTimeoutError, KalshiTransportError

_USER_AGENT = "prediction-market-arbitrage/0.1 (market-data adapter; +https://github.com/Jams411)"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A completed HTTP response, including non-2xx statuses."""

    status: int
    body: bytes


class Transport(Protocol):
    """Something that can perform a single blocking HTTP request."""

    def request(self, method: str, url: str, *, timeout: float) -> HttpResponse:
        """Return the response. Must raise for transport/timeout failures only."""
        ...


class UrllibTransport:
    """Default :class:`Transport` backed by ``urllib.request``."""

    def request(self, method: str, url: str, *, timeout: float) -> HttpResponse:
        req = urllib.request.Request(
            url,
            method=method,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(status=resp.status, body=resp.read())
        except urllib.error.HTTPError as exc:  # non-2xx: still a usable response body
            return HttpResponse(status=exc.code, body=exc.read())
        except TimeoutError as exc:
            raise KalshiTimeoutError(f"request to {url} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise KalshiTimeoutError(
                    f"request to {url} timed out after {timeout}s"
                ) from exc
            raise KalshiTransportError(f"request to {url} failed: {exc.reason}") from exc
