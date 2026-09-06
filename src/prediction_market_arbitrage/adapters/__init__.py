"""Replaceable venue adapters.

Adapters translate venue-specific wire formats into the venue-neutral domain
models in :mod:`prediction_market_arbitrage.domain`. The domain layer must never
import from this package (see ``docs/ARCHITECTURE.md`` boundary rule).
"""
