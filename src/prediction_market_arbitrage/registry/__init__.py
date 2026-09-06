"""Manual verified market-pair registry (Milestone M1.4).

A version-controlled, human-curated declaration of which venue contracts may be
compared by later arbitrage code. No matching logic lives here — the registry
stores and enforces human review decisions (``docs/MARKET_PAIRING.md``,
``docs/DECISIONS.md`` D-006/D-011). No arbitrage, pricing, execution, or
persistence code.
"""

from __future__ import annotations

from .loader import (
    DEFAULT_REGISTRY_PATH,
    MarketPairRegistry,
    load_registry,
    load_registry_text,
)
from .models import (
    ELIGIBLE_STATUSES,
    REQUIRED_CHECKLIST_KEYS,
    MarketPairRecord,
    OutcomeRelation,
    PairStatus,
    RegistryError,
    VenueLeg,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "ELIGIBLE_STATUSES",
    "REQUIRED_CHECKLIST_KEYS",
    "MarketPairRecord",
    "MarketPairRegistry",
    "OutcomeRelation",
    "PairStatus",
    "RegistryError",
    "VenueLeg",
    "load_registry",
    "load_registry_text",
]
