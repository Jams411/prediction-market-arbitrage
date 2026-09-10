"""Concrete :class:`~.transport.DemoTransport` over the Kalshi **DEMO** REST API
(Milestone M3.6).

Standard library only (``urllib``) — no new runtime dependency. The RSA-PSS
signature is produced by an **injected** :class:`~..livebook.Signer` (the same
contract the WS path uses); the concrete openssl signer lives in ``scripts/``,
so this package still imports no cryptography. The HTTP call itself is behind an
injected :class:`HttpSender` seam so every test runs offline.

Safety: the base URL is passed through :func:`~.transport.assert_demo_host` at
construction — a production Kalshi host is a hard :class:`DemoHostError` before
any request is built or sent. Signing string (K-TR-03): ``timestamp_ms +
METHOD + "/trade-api/v2" + path`` (path **without** query). Auth headers
(K-TR-02): ``KALSHI-ACCESS-KEY`` / ``KALSHI-ACCESS-TIMESTAMP`` (ms) /
``KALSHI-ACCESS-SIGNATURE`` (base64).

Fail-closed parsing: a non-JSON or non-object body becomes ``{}`` (the broker
then fails closed — a 2xx create with no ``order_id`` is refused). A
transport/timeout error raises :class:`DemoTransportError`; the orchestrator
treats that as "state unknown" and does not assume the order was placed.
Nothing here logs or embeds the API key id or the signature.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import time as _wall_time
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

from prediction_market_arbitrage.livebook import Signer

from .errors import DemoExecutionError
from .transport import DemoResponse, assert_demo_host

_SIGN_PREFIX = "/trade-api/v2"
_USER_AGENT = (
    "prediction-market-arbitrage/0.1 "
    "(DEMO execution; +https://github.com/Jams411)"
)
_DEFAULT_TIMEOUT = 15.0


class DemoTransportError(DemoExecutionError):
    """A DEMO REST request could not be completed (DNS / connection / timeout /
    TLS). The order state is therefore unknown — callers must fail closed."""


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


@runtime_checkable
class HttpSender(Protocol):
    """Performs exactly one blocking HTTP request. Must return a
    :class:`HttpResponse` for *any* HTTP status (including 4xx/5xx) and raise
    only for transport/timeout failures."""

    def __call__(self, request: HttpRequest, *, timeout: float) -> HttpResponse: ...


def urllib_sender(request: HttpRequest, *, timeout: float) -> HttpResponse:
    """The default :class:`HttpSender` — stdlib ``urllib`` only."""
    req = urllib.request.Request(
        request.url,
        method=request.method,
        data=request.body,
        headers=dict(request.headers),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https enforced
            return HttpResponse(status=resp.status, body=resp.read())
    except urllib.error.HTTPError as exc:  # non-2xx still carries a usable body
        return HttpResponse(status=exc.code, body=exc.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DemoTransportError(
            f"{request.method} {_path_only(request.url)}: transport error "
            f"({type(exc).__name__})"
        ) from None


def _path_only(url: str) -> str:
    """The path (no scheme/host/query) — safe to put in an error message."""
    after_scheme = url.split("://", 1)[-1]
    path = "/" + after_scheme.split("/", 1)[1] if "/" in after_scheme else "/"
    return path.split("?", 1)[0]


class KalshiDemoRestTransport:
    """Kalshi **DEMO** REST transport. Host-pinned at construction."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key_id: str,
        signer: Signer,
        http: HttpSender | None = None,
        clock: Callable[[], float] = _wall_time,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = assert_demo_host(base_url).rstrip("/")
        if not isinstance(api_key_id, str) or not api_key_id.strip():
            raise DemoExecutionError("KalshiDemoRestTransport requires a non-empty api_key_id")
        self._key_id = api_key_id
        self._signer = signer
        self._http: HttpSender = http if http is not None else urllib_sender
        self._clock = clock
        self._timeout = timeout

    # -- signing / headers -------------------------------------------- #

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(self._clock() * 1000))
        message = f"{timestamp}{method}{_SIGN_PREFIX}{path}".encode()
        signature = self._signer.sign(message)
        if not isinstance(signature, bytes) or not signature:
            raise DemoExecutionError("signer returned an empty signature")
        return {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
        }

    # -- one request ------------------------------------------------- #

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> DemoResponse:
        headers = self._auth_headers(method, path)
        raw_body: bytes | None = None
        if body is not None:
            raw_body = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        qs = f"?{urlencode(dict(query))}" if query else ""
        request = HttpRequest(
            method=method,
            url=f"{self.base_url}{path}{qs}",
            headers=headers,
            body=raw_body,
        )
        try:
            response = self._http(request, timeout=self._timeout)
        except DemoTransportError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise any sender failure, no message echo
            raise DemoTransportError(
                f"{method} {path}: transport error ({type(exc).__name__})"
            ) from None
        return DemoResponse(status=response.status, body=_parse_object(response.body))

    # -- DemoTransport surface ------------------------------------- #

    def create_order(self, body: Mapping[str, Any]) -> DemoResponse:
        return self._request("POST", "/portfolio/events/orders", body=dict(body))

    def cancel_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        return self._request(
            "DELETE",
            f"/portfolio/events/orders/{order_id}",
            query={"market_ticker": market_ticker},
        )

    def get_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        return self._request(
            "GET",
            f"/portfolio/orders/{order_id}",
            query={"market_ticker": market_ticker},
        )

    def get_positions(self) -> DemoResponse:
        return self._request("GET", "/portfolio/positions")

    def get_fills(self) -> DemoResponse:
        return self._request("GET", "/portfolio/fills")


def _parse_object(raw: bytes) -> dict[str, Any]:
    """Decode a JSON object body; anything else (empty, array, scalar, invalid)
    -> ``{}`` so the broker's fail-closed checks take over."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
