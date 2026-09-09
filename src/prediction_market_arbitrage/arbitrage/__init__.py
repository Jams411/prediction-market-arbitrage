"""Deterministic arbitrage calculation (Milestone M1.5).

Pure math over already-normalized order books (and, for the cross-venue path, an
already-verified pair record). No venue APIs, no order submission, no positions,
no wall-clock time. Two buy-only models: cross-venue complementary buy/buy
(:meth:`ArbitrageEngine.evaluate`) and same-market complete-set buy
(:meth:`ArbitrageEngine.evaluate_complete_set`). See
``docs/ARBITRAGE_METHODOLOGY.md`` and ``docs/DECISIONS.md`` D-012 / D-025.
"""

from __future__ import annotations

from .engine import (
    ArbitrageEngine,
    CompleteSetEvaluation,
    EngineConfig,
    LegEvaluation,
    LegFill,
    OpportunityEvaluation,
)
from .errors import ArbitrageError
from .fees import (
    FeeModel,
    FixedPerUnitFeeModel,
    KalshiTradingFeeModel,
    PolymarketUsTradingFeeModel,
    VenueFeeModel,
    ZeroFeeModel,
)

__all__ = [
    "ArbitrageEngine",
    "ArbitrageError",
    "CompleteSetEvaluation",
    "EngineConfig",
    "FeeModel",
    "FixedPerUnitFeeModel",
    "KalshiTradingFeeModel",
    "LegEvaluation",
    "LegFill",
    "OpportunityEvaluation",
    "PolymarketUsTradingFeeModel",
    "VenueFeeModel",
    "ZeroFeeModel",
]
