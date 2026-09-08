"""Config-injected, redacted **trading** credentials (Milestone M3.4).

Kept isolated from the M2.1 market-data credentials
(``livebook.credentials``): trading keys are strictly more dangerous, so they
have their **own** container types and their **own** environment variables. As
with M2.1 these are built by the caller from configuration, never hard-coded,
logged, or written to disk; ``repr`` / ``str`` are redacted.

No signing / no network here — these are plain containers. The venue adapters
that would use them are, by design, unimplemented (no primary evidence for a
trading endpoint — ``docs/API_SOURCES.md``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import LiveBrokerCredentialError

_KALSHI_KEY_ID_ENV = "KALSHI_TRADING_API_KEY_ID"
_KALSHI_PRIVATE_KEY_ENV = "KALSHI_TRADING_API_PRIVATE_KEY_PEM"
_POLY_KEY_ID_ENV = "POLYMARKET_US_TRADING_KEY_ID"
_POLY_SECRET_ENV = "POLYMARKET_US_TRADING_SECRET_KEY"


def _require(value: str | None, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveBrokerCredentialError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class KalshiTradingCredentials:
    """Kalshi trading API key id + RSA private key (PEM). Redacted in ``repr``."""

    api_key_id: str
    private_key_pem: str

    def __post_init__(self) -> None:
        _require(self.api_key_id, name="KalshiTradingCredentials.api_key_id")
        _require(self.private_key_pem, name="KalshiTradingCredentials.private_key_pem")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"KalshiTradingCredentials(api_key_id='***{self.api_key_id[-4:]}', "
            "private_key_pem=<redacted>)"
        )

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class PolymarketUsTradingCredentials:
    """Polymarket US trading key id + base64 secret key. Redacted in ``repr``."""

    key_id: str
    secret_key: str

    def __post_init__(self) -> None:
        _require(self.key_id, name="PolymarketUsTradingCredentials.key_id")
        _require(self.secret_key, name="PolymarketUsTradingCredentials.secret_key")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"PolymarketUsTradingCredentials(key_id='***{self.key_id[-4:]}', "
            "secret_key=<redacted>)"
        )

    __str__ = __repr__


def kalshi_trading_credentials_from_env(
    env: dict[str, str] | None = None,
) -> KalshiTradingCredentials:
    """Build :class:`KalshiTradingCredentials` from
    ``KALSHI_TRADING_API_KEY_ID`` + ``KALSHI_TRADING_API_PRIVATE_KEY_PEM``."""
    source = env if env is not None else dict(os.environ)
    return KalshiTradingCredentials(
        api_key_id=_require(source.get(_KALSHI_KEY_ID_ENV), name=_KALSHI_KEY_ID_ENV),
        private_key_pem=_require(
            source.get(_KALSHI_PRIVATE_KEY_ENV), name=_KALSHI_PRIVATE_KEY_ENV
        ),
    )


def polymarket_us_trading_credentials_from_env(
    env: dict[str, str] | None = None,
) -> PolymarketUsTradingCredentials:
    """Build :class:`PolymarketUsTradingCredentials` from
    ``POLYMARKET_US_TRADING_KEY_ID`` + ``POLYMARKET_US_TRADING_SECRET_KEY``."""
    source = env if env is not None else dict(os.environ)
    return PolymarketUsTradingCredentials(
        key_id=_require(source.get(_POLY_KEY_ID_ENV), name=_POLY_KEY_ID_ENV),
        secret_key=_require(source.get(_POLY_SECRET_ENV), name=_POLY_SECRET_ENV),
    )
