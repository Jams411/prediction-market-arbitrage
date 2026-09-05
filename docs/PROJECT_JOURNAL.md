# Project Journal

Use this file as the concise chronological record of milestone progress, evidence, blockers, and decisions that matter to future work.

## 2026-09-05 — Project initialization

- Created `Jams411/prediction-market-arbitrage`.
- Changed repository visibility to private during development.
- Established GitHub repository documentation and tested code as the authoritative source of truth.
- Adopted evidence labels: VERIFIED, OBSERVED, TESTED, ASSUMPTION, UNKNOWN.
- Adopted modular adapter architecture so external venue clients and third-party components can be replaced without rewriting the core.
- Confirmed live trading remains disabled during initial build and paper testing.
- Began Milestone 0.1 documentation baseline.

## 2026-09-05 — M1.1 Domain models

- Implemented normalized, venue-neutral domain models in
  `src/prediction_market_arbitrage/domain/`: Venue, Market, Contract, PriceLevel,
  OrderBook, MarketPair, Opportunity.
- All models are frozen dataclasses that validate their invariants at
  construction: non-empty identifiers, timezone-aware timestamps, probability
  prices in `[0, 1]`, strictly positive quantities/edge, ordered and
  duplicate-free order-book sides, and rejection of truly crossed books.
- Decimal discipline (D-005): models require an explicit `Decimal`; `float`,
  `bool`, and non-finite values are rejected, never coerced. `to_decimal` is
  provided for adapter/parsing boundaries (M1.2+).
- Locked order books (best bid == best ask) are accepted as a valid transient
  state; only crossed books (best bid > best ask) are rejected. See A-005.
- Introduced assumptions A-004..A-007 in `ASSUMPTIONS.md`; to be re-verified
  against real venue data in M1.2 and M1.3.
- No arbitrage arithmetic, execution, transport, or venue-specific code added.
  `Opportunity` is a data container only; edge computation is deferred to M1.5.
- Tests: `tests/test_domain_models.py`, deterministic, covering valid
  construction, boundary/invalid values, Decimal preservation, timezone
  enforcement, best bid/ask behavior, and equality/immutability.
- Marked M0.1 and M1.1 complete in `ROADMAP.md` after ruff, mypy, pytest, and
  pre-commit all passed.

## Journal rules

- Record only material progress, evidence, blockers, and changes in direction.
- Do not use this file as a dump of terminal output.
- Link detailed reasoning to `DECISIONS.md`, assumptions to `ASSUMPTIONS.md`, and validation requirements to `TEST_PLAN.md`.
