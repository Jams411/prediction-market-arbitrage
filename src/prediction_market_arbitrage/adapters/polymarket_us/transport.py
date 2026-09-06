"""Minimal HTTP transport for the Polymarket US adapter.

Standard library only (``urllib``), same shape as the Kalshi adapter's transport
but with this adapter's own error family — the adapters stay independent. The
:class:`Transport` protocol is the seam tests replace with a deterministic fake,
so the suite never touches the network.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .errors import PolymarketTimeoutError, PolymarketTransportError

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
            raise PolymarketTimeoutError(
                f"request to {url} timed out after {timeout}s"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise PolymarketTimeoutError(
                    f"request to {url} timed out after {timeout}s"
                ) from exc
            raise PolymarketTransportError(
                f"request to {url} failed: {exc.reason}"
            ) from exc
