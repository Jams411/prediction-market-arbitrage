"""Deterministic cross-venue arbitrage calculation (Milestone M1.5).

Pure math over already-normalized order books and already-verified pair records.
No venue APIs, no order submission, no positions, no wall-clock time. See
``docs/ARBITRAGE_METHODOLOGY.md`` and ``docs/DECISIONS.md`` D-012.
"""

from __future__ import annotations

from .engine import (
    ArbitrageEngine,
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
