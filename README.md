# Prediction Market Arbitrage Research

This repository is an evidence-driven, read-only research project for testing
whether prediction-market contracts support deterministic arbitrage or useful
relative-value signals. It does not authorize or perform trading.

## Architecture

Venue adapters normalize public market metadata and books into venue-neutral
domain models. The strict-arbitrage engine evaluates only manually verified
cross-venue pairs and remains separate from the advisory research package.
Research uses authoritative contract metadata to derive CPI nested-threshold
relationships, then runs a pure logical detector, snapshot record/replay,
fee/liquidity scoring, and bounded persistence analysis.

## Research scope and findings

Kalshi and Polymarket public rules, metadata, and selected historical evidence
were audited. Cross-venue sports families examined were rejected where
settlement, expiration, continuation, or forfeit rules diverged. Kalshi MECNET
and weather-basket evidence established collateral/netting behavior without
proving normalized aggregate settlement. Same-contract YES/NO offset was not a
deterministic profit primitive.

The relative-value path remains advisory. A CPI higher-threshold YES bid versus
lower-threshold YES ask detector was validated on recorded Kalshi-shaped
metadata and replayed snapshots. A final public study of KXCPI-26SEP ran 10
observations across 10 adjacent relationships (100 relationship-observations):
zero raw inconsistencies and zero signals after modeled costs. The final result
is WEAK_EDGE_REASSESS, so strategy development is stopped.

## Evidence and reproducibility

Canonical rules audits and observation artifacts are under
docs/evidence/contract-discovery/. The CPI replay snapshot and final
frequency-study JSON can be replayed offline with the research package. Tests
use synthetic or recorded fixtures only; Decimal arithmetic, freshness, skew,
provenance, settlement limitations, modeled fees, and displayed depth remain
explicit in the data.

## Limitations and safety

The evidence does not establish profitable execution. Exceptional settlement,
revisions, fair-value decisions, liquidity, slippage, fees, leg risk, and
market equivalence retain limitations recorded in the evidence and assumptions.
Research costs are labeled MODELED/ASSUMED; they are not venue fee claims.

Authentication, account access, orders, cancels, execution, registry approval,
risk-control changes, Demo-cap changes, and LIVE_TRADING are outside this
project state. No real-money action is performed or enabled by this repository.

See docs/ROADMAP.md, docs/ARCHITECTURE.md, docs/API_SOURCES.md,
docs/ASSUMPTIONS.md, docs/DECISIONS.md, docs/RISK_CONTROLS.md,
docs/TEST_PLAN.md, and docs/PROJECT_JOURNAL.md for implementation detail
and source status.
