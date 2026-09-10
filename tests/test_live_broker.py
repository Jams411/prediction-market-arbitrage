"""Deterministic tests for the M3.4 live-broker interface boundary.

No network, no venue, no real order. Every test either exercises the gate /
idempotency / validation wrapper, or asserts a venue adapter is explicitly
unsupported.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal

import pytest
from live_broker_support import (
    FAKE_KALSHI_KEY_ID,
    FAKE_KALSHI_PEM,
    FAKE_POLY_KEY_ID,
    FAKE_POLY_SECRET,
    T0,
    RecordingLiveBroker,
    order_request,
)

from prediction_market_arbitrage.live_broker import (
    LIVE_TRADING_ENABLED,
    REQUIRED_PHRASE,
    CancelRequest,
    DuplicateOrderError,
    IdempotencyGuard,
    KalshiLiveBroker,
    KalshiTradingCredentials,
    LiveBroker,
    LiveBrokerCredentialError,
    LiveBrokerError,
    LiveTradingDisabledError,
    LiveTradingGate,
    PolymarketUsLiveBroker,
    PolymarketUsTradingCredentials,
    UnsupportedLiveOperationError,
    kalshi_trading_credentials_from_env,
    polymarket_us_trading_credentials_from_env,
)

D = Decimal


def _kalshi() -> KalshiTradingCredentials:
    return KalshiTradingCredentials(FAKE_KALSHI_KEY_ID, FAKE_KALSHI_PEM)


def _poly() -> PolymarketUsTradingCredentials:
    return PolymarketUsTradingCredentials(FAKE_POLY_KEY_ID, FAKE_POLY_SECRET)


def _armed() -> LiveTradingGate:
    return LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE)


# ==================================================================== #
# The live-trading gate — off by default, hard to arm
# ==================================================================== #


def test_module_constant_and_default_gate_are_disabled() -> None:
    assert LIVE_TRADING_ENABLED is False
    assert LiveTradingGate().active is False
    assert LiveTradingGate.disabled().active is False


def test_gate_cannot_be_armed_without_the_exact_phrase() -> None:
    with pytest.raises(LiveTradingDisabledError):
        LiveTradingGate(enabled=True)  # no phrase
    with pytest.raises(LiveTradingDisabledError):
        LiveTradingGate(enabled=True, confirmation_phrase="yes")
    with pytest.raises(LiveTradingDisabledError):
        LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE.lower())


def test_gate_arms_only_with_the_exact_phrase() -> None:
    gate = LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE)
    assert gate.active is True
    gate.assert_live_allowed(operation="submit_order")  # no raise


def test_disabled_gate_assert_raises() -> None:
    with pytest.raises(LiveTradingDisabledError):
        LiveTradingGate.disabled().assert_live_allowed(operation="submit_order")


@pytest.mark.parametrize("value", ["", "1", "true", "TRUE", "yes", "on", "enabled"])
def test_from_env_ignores_truthy_looking_values(value: str) -> None:
    assert LiveTradingGate.from_env({"PMA_LIVE_TRADING": value}).active is False


def test_from_env_arms_only_on_the_exact_phrase() -> None:
    assert LiveTradingGate.from_env({"PMA_LIVE_TRADING": REQUIRED_PHRASE}).active is True
    assert LiveTradingGate.from_env({}).active is False


def test_gate_is_frozen() -> None:
    gate = LiveTradingGate.disabled()
    with pytest.raises(FrozenInstanceError):
        gate.enabled = True  # type: ignore[misc]


# ==================================================================== #
# Interface wrapper — gate + dedupe enforced before any venue hook
# ==================================================================== #


def test_disabled_gate_blocks_submit_before_reaching_the_venue_hook() -> None:
    broker = RecordingLiveBroker()  # default (disabled) gate
    with pytest.raises(LiveTradingDisabledError):
        broker.submit_order(order_request(), now=T0)
    assert broker.calls == []  # _do_submit was never reached


def test_all_operations_are_gated() -> None:
    broker = RecordingLiveBroker()
    with pytest.raises(LiveTradingDisabledError):
        broker.cancel_order(CancelRequest(client_order_id="cid-1"), now=T0)
    with pytest.raises(LiveTradingDisabledError):
        broker.get_order("cid-1", now=T0)
    with pytest.raises(LiveTradingDisabledError):
        broker.get_positions(now=T0)
    assert broker.calls == []


def test_armed_gate_reaches_the_hook() -> None:
    broker = RecordingLiveBroker(gate=_armed())
    ack = broker.submit_order(order_request(client_order_id="cid-A"), now=T0)
    assert broker.calls == ["submit:cid-A"]
    assert ack.accepted is True


def test_idempotency_guard_blocks_a_duplicate_client_order_id() -> None:
    broker = RecordingLiveBroker(gate=_armed())
    broker.submit_order(order_request(client_order_id="dup"), now=T0)
    with pytest.raises(DuplicateOrderError):
        broker.submit_order(order_request(client_order_id="dup"), now=T0)
    assert broker.calls == ["submit:dup"]  # second submit never reached the hook


def test_idempotency_guard_allows_distinct_ids() -> None:
    broker = RecordingLiveBroker(gate=_armed())
    broker.submit_order(order_request(client_order_id="a"), now=T0)
    broker.submit_order(order_request(client_order_id="b"), now=T0)
    assert broker.calls == ["submit:a", "submit:b"]


def test_shared_idempotency_guard_is_honoured() -> None:
    guard = IdempotencyGuard()
    b1 = RecordingLiveBroker(gate=_armed(), idempotency=guard)
    b2 = RecordingLiveBroker(gate=_armed(), idempotency=guard)
    b1.submit_order(order_request(client_order_id="shared"), now=T0)
    with pytest.raises(DuplicateOrderError):
        b2.submit_order(order_request(client_order_id="shared"), now=T0)


def test_submit_rejects_a_venue_mismatch() -> None:
    broker = RecordingLiveBroker(gate=_armed())  # venue 'kalshi'
    with pytest.raises(LiveBrokerError):
        broker.submit_order(order_request(venue="polymarket_us"), now=T0)


def test_naive_now_is_rejected() -> None:
    broker = RecordingLiveBroker(gate=_armed())
    with pytest.raises(LiveBrokerError):
        broker.submit_order(order_request(), now=datetime(2026, 5, 1, 12, 0, 0))


# ==================================================================== #
# IdempotencyGuard unit
# ==================================================================== #


def test_idempotency_guard_unit() -> None:
    g = IdempotencyGuard()
    g.register("x")
    assert g.seen("x") and not g.seen("y")
    with pytest.raises(DuplicateOrderError):
        g.register("x")
    with pytest.raises(LiveBrokerError):
        g.register("  ")
    assert len(g) == 1


# ==================================================================== #
# LiveOrderRequest validation
# ==================================================================== #


@pytest.mark.parametrize(
    "kwargs",
    [
        {"client_order_id": ""},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"limit_price": None},  # limit order without a price
        {"order_type": "market", "limit_price": "0.5"},  # market with a price
        {"limit_price": "1.5"},  # outside (0, 1)
        {"side": "hold"},
    ],
)
def test_live_order_request_validation(kwargs: dict[str, str | None]) -> None:
    with pytest.raises(LiveBrokerError):
        order_request(**kwargs)  # type: ignore[arg-type]


def test_market_order_without_price_is_valid() -> None:
    req = order_request(order_type="market", limit_price=None)
    assert req.limit_price is None


# ==================================================================== #
# Credentials — isolated + redacted
# ==================================================================== #


def test_trading_credentials_are_redacted() -> None:
    cred = _kalshi()
    text = repr(cred) + str(cred)
    assert FAKE_KALSHI_PEM not in text
    assert "redacted" in text
    assert FAKE_KALSHI_KEY_ID[-4:] in text  # last-4 hint only

    pcred = _poly()
    assert FAKE_POLY_SECRET not in repr(pcred)


def test_trading_credentials_env_is_isolated_from_market_data_env() -> None:
    env = {
        "KALSHI_TRADING_API_KEY_ID": "k-id",
        "KALSHI_TRADING_API_PRIVATE_KEY_PEM": "k-pem",
        "POLYMARKET_US_TRADING_KEY_ID": "p-id",
        "POLYMARKET_US_TRADING_SECRET_KEY": "p-secret",
    }
    k = kalshi_trading_credentials_from_env(env)
    p = polymarket_us_trading_credentials_from_env(env)
    assert k.api_key_id == "k-id"
    assert p.key_id == "p-id"
    # the M2.1 market-data variable names must NOT be consulted
    with pytest.raises(LiveBrokerCredentialError):
        kalshi_trading_credentials_from_env({"KALSHI_API_KEY_ID": "x"})


def test_missing_trading_credentials_raise() -> None:
    with pytest.raises(LiveBrokerCredentialError):
        kalshi_trading_credentials_from_env({})
    with pytest.raises(LiveBrokerCredentialError):
        KalshiTradingCredentials("", "pem")


# ==================================================================== #
# Venue adapters — defined, explicitly unsupported (no primary evidence)
# ==================================================================== #


@pytest.mark.parametrize("venue", ["kalshi", "polymarket_us"])
def test_every_venue_operation_is_unsupported_even_when_armed(venue: str) -> None:
    broker: LiveBroker
    if venue == "kalshi":
        broker = KalshiLiveBroker(_kalshi(), gate=_armed())
    else:
        broker = PolymarketUsLiveBroker(_poly(), gate=_armed())

    with pytest.raises(UnsupportedLiveOperationError) as e1:
        broker.submit_order(order_request(venue=venue, client_order_id="u1"), now=T0)
    assert e1.value.venue == venue
    assert "API_SOURCES" in e1.value.reason

    with pytest.raises(UnsupportedLiveOperationError):
        broker.cancel_order(CancelRequest(client_order_id="u1"), now=T0)
    with pytest.raises(UnsupportedLiveOperationError):
        broker.get_order("u1", now=T0)
    with pytest.raises(UnsupportedLiveOperationError):
        broker.get_positions(now=T0)


def test_venue_adapter_is_gated_before_unsupported() -> None:
    # With the default disabled gate, the gate check wins over "unsupported".
    broker = KalshiLiveBroker(_kalshi())
    with pytest.raises(LiveTradingDisabledError):
        broker.submit_order(order_request(client_order_id="g1"), now=T0)


def test_venue_adapter_rejects_wrong_credential_type() -> None:
    with pytest.raises(TypeError):
        KalshiLiveBroker(_poly())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PolymarketUsLiveBroker(_kalshi())  # type: ignore[arg-type]


def test_venue_adapter_defaults_to_disabled() -> None:
    assert KalshiLiveBroker(_kalshi()).live_trading_active is False
    assert PolymarketUsLiveBroker(_poly()).live_trading_active is False


def test_cannot_instantiate_the_abstract_interface() -> None:
    with pytest.raises(TypeError):
        LiveBroker()  # type: ignore[abstract]


# ==================================================================== #
# Real-money gate hardening (audit obs/realmoney-gates-9-11-15)
#   #9  Duplicate-order prevention — local half, offline-provable
#   #14 Credential isolation      — no-leak matrix + gitignore guard
#   #15 Live mode cannot activate accidentally — near-miss / bypass cases
# These lock the offline-provable behaviour only; A-037 / D-023 still
# require a captured trading API + live run before any box is checked.
# ==================================================================== #


class _RaisingLiveBroker(RecordingLiveBroker):
    """``_do_submit`` fails downstream — models a venue call that errored
    *after* the interface already registered the ``client_order_id``."""

    def _do_submit(self, request, *, now):  # type: ignore[no-untyped-def]
        self.calls.append(f"submit:{request.client_order_id}")
        raise RuntimeError("downstream venue failure")


def test_gate9_duplicate_id_blocked_even_after_a_failed_submit() -> None:
    broker = _RaisingLiveBroker(gate=_armed())
    with pytest.raises(RuntimeError):
        broker.submit_order(order_request(client_order_id="cid-x"), now=T0)
    # the id was registered before the hook ran, so a re-send is refused
    with pytest.raises(DuplicateOrderError):
        broker.submit_order(order_request(client_order_id="cid-x"), now=T0)
    assert broker.calls == ["submit:cid-x"]  # hook reached exactly once


def test_gate9_duplicate_id_blocked_on_the_concrete_kalshi_adapter() -> None:
    broker = KalshiLiveBroker(_kalshi(), gate=_armed())
    with pytest.raises(UnsupportedLiveOperationError):
        broker.submit_order(order_request(client_order_id="k-dup"), now=T0)
    with pytest.raises(DuplicateOrderError):
        broker.submit_order(order_request(client_order_id="k-dup"), now=T0)


@pytest.mark.parametrize(
    "value",
    [
        " I_UNDERSTAND_THIS_PLACES_REAL_ORDERS",
        "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS ",
        "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS\n",
        "I_UNDERSTAND_THIS_PLACES_REAL_ORDERSX",
        "XI_UNDERSTAND_THIS_PLACES_REAL_ORDERS",
    ],
)
def test_gate15_from_env_requires_an_exact_match_no_trimming(value: str) -> None:
    assert LiveTradingGate.from_env({"PMA_LIVE_TRADING": value}).active is False


def test_gate15_phrase_without_the_enabled_flag_stays_inactive() -> None:
    gate = LiveTradingGate(enabled=False, confirmation_phrase=REQUIRED_PHRASE)
    assert gate.active is False
    with pytest.raises(LiveTradingDisabledError):
        gate.assert_live_allowed(operation="submit_order")


def test_gate15_replace_cannot_sneak_enabled_past_post_init() -> None:
    from dataclasses import replace

    with pytest.raises(LiveTradingDisabledError):
        replace(LiveTradingGate.disabled(), enabled=True)


def test_gate15_from_env_defaults_to_disabled_when_the_var_is_absent() -> None:
    assert LiveTradingGate.from_env({}).active is False
    assert LiveTradingGate.from_env({"OTHER_VAR": REQUIRED_PHRASE}).active is False


def test_gate14_trading_credentials_never_leak_via_format_or_exception() -> None:
    cred = _kalshi()
    renders = [
        f"{cred}",
        f"{cred!r}",
        f"{cred!s}",
        format(cred),
        str([cred]),  # container repr
        repr({"cred": cred}),
    ]
    for text in renders:
        assert FAKE_KALSHI_PEM not in text
        assert "NOT-A-REAL-TRADING-KEY" not in text
    # a validation error names the field, never echoes the value
    with pytest.raises(LiveBrokerCredentialError) as exc:
        KalshiTradingCredentials("k-id", "")
    assert "private_key_pem" in str(exc.value)


def test_gate14_gitignore_excludes_key_material_and_env_files() -> None:
    from pathlib import Path

    body = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
    for pattern in ("*.pem", "*.key", ".env", ".env.*"):
        assert pattern in body, f".gitignore no longer excludes {pattern!r}"
