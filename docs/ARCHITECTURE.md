# Architecture

## Principle

Own the core trading logic. Keep external systems behind replaceable adapters.

## Target shape

```text
Polymarket US ---- adapter ---\
                              -> normalized market state -> arbitrage engine -> risk -> broker
Kalshi ----------- adapter ---/

Replay data ------ adapter -------------------------------/

Paper broker and live brokers implement the same execution interface.
```

## Core components we own

- normalized market/domain models
- verified contract-pair registry
- arbitrage calculations
- fee/depth/slippage-aware sizing
- risk rules
- trade/evidence ledger
- orchestration
- analytics

## Replaceable components

- venue market-data clients
- WebSocket transport/reconnect implementation
- venue authentication/signing
- order submission adapters
- paper-fill engine where practical
- storage implementation

## Reference-only systems

Third-party repositories may inform design without becoming runtime dependencies. Examples include event-driven trading engines, HFT backtesters, market makers, and prediction-market bots.

## Boundary rule

Strategy and risk code must not call venue-specific APIs directly. Venue-specific behavior stays inside adapters.

## AI boundary

LLMs are not part of the deterministic trading loop. AI may support research, review, diagnostics, reporting, and later a constrained MCP control/observability layer.
