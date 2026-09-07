"""Config-injected, redacted credentials for the authenticated market-data
WebSockets (Milestone M2.1).

Both venues' market-data WebSockets require API-key auth in the handshake
(``docs/API_SOURCES.md`` K-WS-01 / P-WS-01). These containers hold the secret
material; they are **built by the caller from configuration** (e.g. env vars via
:func:`kalshi_credentials_from_env` / :func:`polymarket_us_credentials_from_env`)
and never hard-coded, logged, or written to disk. ``repr`` / ``str`` are
redacted so a stray log line cannot leak them.

The actual signing (RSA-PSS for Kalshi, Ed25519 for Polymarket US) is done by an
injected :class:`~.ws_auth.Signer` — this package takes **no** cryptography
dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import LiveBookError

_KALSHI_KEY_ID_ENV = "KALSHI_API_KEY_ID"
_KALSHI_PRIVATE_KEY_ENV = "KALSHI_API_PRIVATE_KEY_PEM"
_POLY_KEY_ID_ENV = "POLYMARKET_US_KEY_ID"
_POLY_SECRET_ENV = "POLYMARKET_US_SECRET_KEY"


def _require(value: str | None, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveBookError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class KalshiCredentials:
    """Kalshi API key id + RSA private key (PEM). Redacted in ``repr``."""

    api_key_id: str
    private_key_pem: str

    def __post_init__(self) -> None:
        _require(self.api_key_id, name="KalshiCredentials.api_key_id")
        _require(self.private_key_pem, name="KalshiCredentials.private_key_pem")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        tail = self.api_key_id[-4:]
        return f"KalshiCredentials(api_key_id='***{tail}', private_key_pem=<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class PolymarketUsCredentials:
    """Polymarket US key id + base64 secret key (Ed25519). Redacted in ``repr``."""

    key_id: str
    secret_key: str

    def __post_init__(self) -> None:
        _require(self.key_id, name="PolymarketUsCredentials.key_id")
        _require(self.secret_key, name="PolymarketUsCredentials.secret_key")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"PolymarketUsCredentials(key_id='***{self.key_id[-4:]}', secret_key=<redacted>)"

    __str__ = __repr__


def kalshi_credentials_from_env(env: dict[str, str] | None = None) -> KalshiCredentials:
    """Build :class:`KalshiCredentials` from ``KALSHI_API_KEY_ID`` and
    ``KALSHI_API_PRIVATE_KEY_PEM``. Raises :class:`LiveBookError` if unset."""
    source = env if env is not None else dict(os.environ)
    return KalshiCredentials(
        api_key_id=_require(source.get(_KALSHI_KEY_ID_ENV), name=_KALSHI_KEY_ID_ENV),
        private_key_pem=_require(source.get(_KALSHI_PRIVATE_KEY_ENV), name=_KALSHI_PRIVATE_KEY_ENV),
    )


def polymarket_us_credentials_from_env(
    env: dict[str, str] | None = None,
) -> PolymarketUsCredentials:
    """Build :class:`PolymarketUsCredentials` from ``POLYMARKET_US_KEY_ID`` and
    ``POLYMARKET_US_SECRET_KEY``. Raises :class:`LiveBookError` if unset."""
    source = env if env is not None else dict(os.environ)
    return PolymarketUsCredentials(
        key_id=_require(source.get(_POLY_KEY_ID_ENV), name=_POLY_KEY_ID_ENV),
        secret_key=_require(source.get(_POLY_SECRET_ENV), name=_POLY_SECRET_ENV),
    )
