"""Deterministic tests for M2.1 credential isolation."""

from __future__ import annotations

import pytest
from livebook_support import (
    FAKE_KALSHI_KEY_ID,
    FAKE_KALSHI_PEM,
    FAKE_POLY_KEY_ID,
    FAKE_POLY_SECRET,
)

from prediction_market_arbitrage.livebook import (
    KalshiCredentials,
    LiveBookError,
    PolymarketUsCredentials,
    kalshi_credentials_from_env,
    polymarket_us_credentials_from_env,
)


def test_repr_and_str_redact_the_secret() -> None:
    kalshi = KalshiCredentials(api_key_id=FAKE_KALSHI_KEY_ID, private_key_pem=FAKE_KALSHI_PEM)
    for text in (repr(kalshi), str(kalshi)):
        assert "NOT-A-REAL-KEY" not in text
        assert "<redacted>" in text
        assert FAKE_KALSHI_KEY_ID not in text  # only a masked tail

    poly = PolymarketUsCredentials(key_id=FAKE_POLY_KEY_ID, secret_key=FAKE_POLY_SECRET)
    for text in (repr(poly), str(poly)):
        assert FAKE_POLY_SECRET not in text
        assert "<redacted>" in text


@pytest.mark.parametrize(
    "ctor",
    [
        lambda: KalshiCredentials(api_key_id="", private_key_pem="x"),
        lambda: KalshiCredentials(api_key_id="x", private_key_pem="  "),
        lambda: PolymarketUsCredentials(key_id="", secret_key="x"),
        lambda: PolymarketUsCredentials(key_id="x", secret_key=""),
    ],
)
def test_empty_fields_are_rejected(ctor) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LiveBookError, match="non-empty string"):
        ctor()


def test_env_loaders_read_the_documented_var_names() -> None:
    env = {
        "KALSHI_API_KEY_ID": FAKE_KALSHI_KEY_ID,
        "KALSHI_API_PRIVATE_KEY_PEM": FAKE_KALSHI_PEM,
        "POLYMARKET_US_KEY_ID": FAKE_POLY_KEY_ID,
        "POLYMARKET_US_SECRET_KEY": FAKE_POLY_SECRET,
    }
    assert kalshi_credentials_from_env(env).api_key_id == FAKE_KALSHI_KEY_ID
    assert polymarket_us_credentials_from_env(env).key_id == FAKE_POLY_KEY_ID


def test_env_loader_raises_when_unset() -> None:
    with pytest.raises(LiveBookError, match="KALSHI_API_KEY_ID"):
        kalshi_credentials_from_env({})
    with pytest.raises(LiveBookError, match="POLYMARKET_US_SECRET_KEY"):
        polymarket_us_credentials_from_env({"POLYMARKET_US_KEY_ID": FAKE_POLY_KEY_ID})


# Real-money gate #14 (Credential isolation) hardening: the market-data prod
# credentials are in active use (Kalshi WS observation), so the no-leak
# guarantee must hold for every render path, not just repr()+str().
def test_market_data_credentials_never_leak_via_format_or_exception() -> None:
    cred = KalshiCredentials(api_key_id=FAKE_KALSHI_KEY_ID, private_key_pem=FAKE_KALSHI_PEM)
    renders = [
        f"{cred}",
        f"{cred!r}",
        f"{cred!s}",
        format(cred),
        str([cred]),  # container repr
        repr({"cred": cred}),
    ]
    for text in renders:
        assert "NOT-A-REAL-KEY" not in text
        assert "<redacted>" in text
    with pytest.raises(LiveBookError) as exc:
        KalshiCredentials("id", "")
    assert "NOT-A-REAL-KEY" not in str(exc.value)
    assert "private_key_pem" in str(exc.value)
