"""The Kalshi **DEMO** REST I/O seam for the execution orchestrator (M3.5).

This module defines *only* the boundary: the :class:`DemoTransport` protocol,
the :class:`DemoResponse` value object, and the hard host guard
:func:`assert_demo_host`. **No networked implementation ships here** — exactly as
``livebook`` ships no networked socket (D-015). A concrete transport (openssl
RSA-PSS signing + ``urllib``, demo Keychain credential) is a caller / script
concern and is not part of this milestone; tests inject a fake.

Safety: :func:`assert_demo_host` refuses any production Kalshi host and any URL
that is not recognisably a Kalshi demo host. It is called from
:class:`~.broker.KalshiDemoLiveBroker` construction, so a demo broker cannot be
built against production even by mistake.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .errors import DemoHostError

#: Substrings that mark a **production** Kalshi API host. Any of these in a base
#: URL is an immediate hard failure.
PROD_HOST_MARKERS: tuple[str, ...] = (
    "external-api.kalshi.com",
    "api.kalshi.com",
    "trading-api.kalshi.com",
    "//kalshi.com",
)

#: A base URL must contain this to be accepted as a Kalshi **demo** host.
DEMO_HOST_MARKER = "demo.kalshi.co"


def assert_demo_host(base_url: str) -> str:
    """Return ``base_url`` unchanged iff it is a Kalshi **demo** host; otherwise
    raise :class:`DemoHostError`. Fail-closed: an empty / unrecognised URL is
    rejected, not defaulted."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise DemoHostError("demo execution requires an explicit demo base URL; got empty")
    lowered = base_url.strip().lower()
    for marker in PROD_HOST_MARKERS:
        if marker in lowered:
            raise DemoHostError(
                f"production Kalshi host is forbidden for demo execution: {base_url!r}"
            )
    if DEMO_HOST_MARKER not in lowered:
        raise DemoHostError(
            f"base URL is not a recognised Kalshi demo host "
            f"(must contain {DEMO_HOST_MARKER!r}): {base_url!r}"
        )
    if not lowered.startswith("https://"):
        raise DemoHostError(f"demo base URL must be https://: {base_url!r}")
    return base_url


@dataclass(frozen=True, slots=True)
class DemoResponse:
    """One parsed DEMO HTTP response. ``body`` is the decoded JSON object (``{}``
    when the venue returned no/again-non-object body)."""

    status: int
    body: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@runtime_checkable
class DemoTransport(Protocol):
    """Synchronous Kalshi **demo** REST seam. Every method performs exactly one
    signed demo request and returns a :class:`DemoResponse`; nothing here is
    deterministic (this is the explicit I/O boundary). A real implementation
    signs with the demo RSA key and targets ``external-api.demo.kalshi.co``."""

    #: The demo base URL, e.g. ``https://external-api.demo.kalshi.co/trade-api/v2``.
    base_url: str

    def create_order(self, body: Mapping[str, Any]) -> DemoResponse:
        """``POST /portfolio/events/orders`` (K-TR-04 / K-TR-05)."""
        ...

    def cancel_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        """``DELETE /portfolio/events/orders/{order_id}?market_ticker=…`` (K-TR-10;
        the query param is mandatory for a sharded order — K-TR-OBS-30)."""
        ...

    def get_order(self, order_id: str, *, market_ticker: str) -> DemoResponse:
        """``GET /portfolio/orders/{order_id}?market_ticker=…`` (K-TR-08 /
        K-TR-OBS-28 — sharded reads must be routed)."""
        ...

    def get_positions(self) -> DemoResponse:
        """``GET /portfolio/positions`` (K-TR-11)."""
        ...

    def get_fills(self) -> DemoResponse:
        """``GET /portfolio/fills`` (K-TR-09)."""
        ...
