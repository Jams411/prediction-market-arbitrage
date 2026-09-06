"""Deterministic tests for the M1.6 evidence-backed venue fee models.

Known-answer vectors are taken verbatim from each venue's published fee table
(Kalshi multiplier scaling uses independently-calculated cases):

- Kalshi: ``docs/evidence/kalshi-fee-schedule-2026-07-07.txt``
  (``kalshi.com/docs/kalshi-fee-schedule.pdf``, "7.7.26 Update").
- Polymarket US: ``docs/evidence/polymarket-us-fee-schedule.txt``
  (``docs.polymarket.us/fees``, effective July 1, 2026).

Every price is a contract price in dollars; every quantity is a contract count.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from arbitrage_support import EVAL_TIME, kalshi_book, make_record, polymarket_book

from prediction_market_arbitrage.arbitrage import (
    ArbitrageEngine,
    ArbitrageError,
    EngineConfig,
    KalshiTradingFeeModel,
    PolymarketUsTradingFeeModel,
    VenueFeeModel,
)

D = Decimal


# --------------------------------------------------------------------------- #
# Kalshi — base taker coefficient 0.07, per-contract multiplier M (default 1),
# round up to the next cent
# --------------------------------------------------------------------------- #

# (price, contracts, published fee) from the "General Trading Fees Table" (M = 1).
KALSHI_GENERAL_VECTORS = [
    ("0.01", 1, "0.01"),
    ("0.05", 1, "0.01"),
    ("0.10", 1, "0.01"),
    ("0.20", 1, "0.02"),
    ("0.35", 1, "0.02"),
    ("0.50", 1, "0.02"),
    ("0.99", 1, "0.01"),
    ("0.01", 100, "0.07"),
    ("0.05", 100, "0.34"),
    ("0.10", 100, "0.63"),
    ("0.20", 100, "1.12"),
    ("0.35", 100, "1.60"),
    ("0.50", 100, "1.75"),
    ("0.99", 100, "0.07"),
]


@pytest.mark.parametrize(("price", "contracts", "expected"), KALSHI_GENERAL_VECTORS)
def test_kalshi_general_matches_published_table(
    price: str, contracts: int, expected: str
) -> None:
    model = KalshiTradingFeeModel()
    fee = model.fee(venue="kalshi", fills=[(D(price), D(contracts))])
    assert fee == D(expected)


# Independently calculated multiplier cases: fee = round_up_cent(M * 0.07 * C * P * (1-P)).
# (multiplier, price, contracts, expected)
KALSHI_MULTIPLIER_VECTORS = [
    ("0.5", "0.50", 100, "0.88"),  # 0.5*0.07*100*0.25 = 0.875 -> round up
    ("0.5", "0.40", 100, "0.84"),  # 0.5*0.07*100*0.24 = 0.84 exact
    ("2", "0.50", 100, "3.50"),  # 2*0.07*100*0.25 = 3.5 exact
    ("1.5", "0.50", 100, "2.63"),  # 1.5*0.07*100*0.25 = 2.625 -> round up
    ("0", "0.50", 100, "0"),  # M = 0 -> no fee
]


@pytest.mark.parametrize(
    ("multiplier", "price", "contracts", "expected"), KALSHI_MULTIPLIER_VECTORS
)
def test_kalshi_multiplier_scales_the_base_coefficient(
    multiplier: str, price: str, contracts: int, expected: str
) -> None:
    model = KalshiTradingFeeModel(multiplier=D(multiplier))
    assert model.coefficient == D(multiplier) * D("0.07")
    fee = model.fee(venue="kalshi", fills=[(D(price), D(contracts))])
    assert fee == D(expected)


def test_kalshi_default_multiplier_is_one() -> None:
    assert KalshiTradingFeeModel().multiplier == D("1")
    assert KalshiTradingFeeModel().coefficient == D("0.07")


def test_kalshi_rounds_each_fill_slice_then_sums() -> None:
    # Two slices at $0.50: 0.07*20*0.25 = 0.35 (exact) and 0.07*1*0.25 = 0.0175
    # -> round up to 0.02. Per-slice rounding gives 0.35 + 0.02 = 0.37.
    model = KalshiTradingFeeModel()
    fee = model.fee(venue="kalshi", fills=[(D("0.50"), D(20)), (D("0.50"), D(1))])
    assert fee == D("0.37")


def test_kalshi_exact_cent_multiple_is_not_rounded_up() -> None:
    # 0.07 * 100 * 0.5 * 0.5 = 1.75 exactly.
    model = KalshiTradingFeeModel()
    assert model.fee(venue="kalshi", fills=[(D("0.50"), D(100))]) == D("1.75")


def test_kalshi_price_at_bounds_yields_zero_fee() -> None:
    model = KalshiTradingFeeModel()
    assert model.fee(venue="kalshi", fills=[(D("0"), D(100)), (D("1"), D(100))]) == D(0)


def test_kalshi_empty_fills_is_zero() -> None:
    assert KalshiTradingFeeModel().fee(venue="kalshi", fills=[]) == D(0)


def test_kalshi_model_rejects_wrong_venue() -> None:
    with pytest.raises(ArbitrageError, match="non-Kalshi"):
        KalshiTradingFeeModel().fee(venue="polymarket_us", fills=[(D("0.5"), D(1))])


def test_kalshi_model_rejects_float_multiplier() -> None:
    with pytest.raises(ArbitrageError, match="Decimal"):
        KalshiTradingFeeModel(multiplier=0.5)  # type: ignore[arg-type]


def test_kalshi_model_rejects_negative_multiplier() -> None:
    with pytest.raises(ArbitrageError, match=">= 0"):
        KalshiTradingFeeModel(multiplier=D("-0.01"))


# --------------------------------------------------------------------------- #
# Polymarket US — taker coefficient 0.06, banker's rounding to the cent
# --------------------------------------------------------------------------- #

# (price, contracts, published "Taker Pays") from "Fee Schedule by Price" (100-lot).
POLY_TAKER_VECTORS = [
    ("0.01", 100, "0.06"),
    ("0.02", 100, "0.12"),
    ("0.03", 100, "0.17"),
    ("0.04", 100, "0.23"),
    ("0.05", 100, "0.28"),  # 0.285 -> 0.28 by round-half-to-even
]


@pytest.mark.parametrize(("price", "contracts", "expected"), POLY_TAKER_VECTORS)
def test_polymarket_us_taker_matches_published_table(
    price: str, contracts: int, expected: str
) -> None:
    model = PolymarketUsTradingFeeModel()
    fee = model.fee(venue="polymarket_us", fills=[(D(price), D(contracts))])
    assert fee == D(expected)


def test_polymarket_us_bankers_rounding_half_to_even() -> None:
    # 0.06 * 100 * 0.05 * 0.95 = 0.285 -> 0.28 (round half to EVEN, i.e. down).
    model = PolymarketUsTradingFeeModel()
    assert model.fee(venue="polymarket_us", fills=[(D("0.05"), D(100))]) == D("0.28")


def test_polymarket_us_small_trade_rounds_to_zero() -> None:
    # 0.06 * 1 * 0.5 * 0.5 = 0.015 -> 0.02 by half-to-even. Use a tinier trade:
    # 0.06 * 1 * 0.01 * 0.99 = 0.000594 -> 0.00.
    model = PolymarketUsTradingFeeModel()
    assert model.fee(venue="polymarket_us", fills=[(D("0.01"), D(1))]) == D(0)


def test_polymarket_us_price_at_bounds_yields_zero_fee() -> None:
    model = PolymarketUsTradingFeeModel()
    fills = [(D("0"), D(100)), (D("1"), D(100))]
    assert model.fee(venue="polymarket_us", fills=fills) == D(0)


def test_polymarket_us_model_rejects_wrong_venue() -> None:
    with pytest.raises(ArbitrageError, match="non-Polymarket-US"):
        PolymarketUsTradingFeeModel().fee(venue="kalshi", fills=[(D("0.5"), D(1))])


def test_polymarket_us_model_rejects_float_coefficient() -> None:
    with pytest.raises(ArbitrageError, match="Decimal"):
        PolymarketUsTradingFeeModel(taker_coefficient=0.06)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Shared fill-input validation
# --------------------------------------------------------------------------- #


_VenueModel = KalshiTradingFeeModel | PolymarketUsTradingFeeModel

_VENUE_MODELS: list[_VenueModel] = [
    KalshiTradingFeeModel(),
    PolymarketUsTradingFeeModel(),
]


@pytest.mark.parametrize("model", _VENUE_MODELS, ids=["kalshi", "polymarket_us"])
def test_models_reject_float_fill_components(model: _VenueModel) -> None:
    venue = model.VENUE
    with pytest.raises(ArbitrageError, match="finite Decimal"):
        model.fee(venue=venue, fills=[(0.5, D(1))])  # type: ignore[list-item]
    with pytest.raises(ArbitrageError, match="finite Decimal"):
        model.fee(venue=venue, fills=[(D("0.5"), 1)])  # type: ignore[list-item]


@pytest.mark.parametrize("model", _VENUE_MODELS, ids=["kalshi", "polymarket_us"])
def test_models_reject_negative_quantity(model: _VenueModel) -> None:
    with pytest.raises(ArbitrageError, match="quantity must be >= 0"):
        model.fee(venue=model.VENUE, fills=[(D("0.5"), D(-1))])


# --------------------------------------------------------------------------- #
# VenueFeeModel router
# --------------------------------------------------------------------------- #


def test_venue_fee_model_routes_each_leg_to_its_schedule() -> None:
    router = VenueFeeModel.real_taker()
    # Kalshi general 0.07 at $0.50 x100 -> 1.75; Polymarket US 0.06 -> 1.50.
    assert router.fee(venue="kalshi", fills=[(D("0.50"), D(100))]) == D("1.75")
    assert router.fee(venue="polymarket_us", fills=[(D("0.50"), D(100))]) == D("1.50")


def test_venue_fee_model_fails_closed_on_unknown_venue() -> None:
    router = VenueFeeModel.real_taker()
    with pytest.raises(ArbitrageError, match="no fee model for venue"):
        router.fee(venue="predictit", fills=[(D("0.5"), D(1))])


def test_venue_fee_model_requires_at_least_one_model() -> None:
    with pytest.raises(ArbitrageError, match="at least one"):
        VenueFeeModel({})


def test_venue_fee_model_passes_venue_through_to_child_guard() -> None:
    # A misconfigured router that points "polymarket_us" at the Kalshi model
    # still fails closed via the child model's own venue guard.
    router = VenueFeeModel({"polymarket_us": KalshiTradingFeeModel()})
    with pytest.raises(ArbitrageError, match="non-Kalshi"):
        router.fee(venue="polymarket_us", fills=[(D("0.5"), D(1))])


# --------------------------------------------------------------------------- #
# Integration with the M1.5 engine
# --------------------------------------------------------------------------- #


def test_real_taker_fees_plug_into_engine_with_exact_net_edge() -> None:
    """Kalshi YES $0.40 x100 + Polymarket US SHORT $0.50 x100, no buffer.

    gross cost   = 40 + 50 = 90;  gross edge = 100 - 90 = 10
    Kalshi fee   = round_up(0.07 * 100 * 0.40 * 0.60) = round_up(1.68)   = 1.68
    Polymkt fee  = bankers(0.06 * 100 * 0.50 * 0.50)  = bankers(1.50)    = 1.50
    net edge     = 10 - (1.68 + 1.50) = 6.82
    """
    engine = ArbitrageEngine(
        config=EngineConfig(fee_model=VenueFeeModel.real_taker())
    )
    result = engine.evaluate(
        make_record(),
        kalshi_book([("0.40", "100")]),
        polymarket_book([("0.50", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("100"),
    )
    assert result.executable_quantity == D("100")
    assert result.fees == D("3.18")
    assert result.net_edge == D("6.82")
    assert result.has_opportunity is True


def test_real_taker_fees_can_eliminate_a_thin_positive_gross_edge() -> None:
    """Kalshi YES $0.48 x100 + Polymarket US SHORT $0.50 x100.

    gross edge = 100 - 98 = 2
    Kalshi fee = round_up(0.07 * 100 * 0.48 * 0.52) = round_up(1.7472) = 1.75
    Polymkt fee = bankers(0.06 * 100 * 0.50 * 0.50) = 1.50
    net edge   = 2 - 3.25 = -1.25  -> no opportunity
    """
    engine = ArbitrageEngine(
        config=EngineConfig(fee_model=VenueFeeModel.real_taker())
    )
    result = engine.evaluate(
        make_record(),
        kalshi_book([("0.48", "100")]),
        polymarket_book([("0.50", "100")]),
        evaluation_time=EVAL_TIME,
        requested_quantity=D("100"),
    )
    assert result.fees == D("3.25")
    assert result.net_edge == D("-1.25")
    assert result.has_opportunity is False
