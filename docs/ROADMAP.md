# Roadmap

This file is the authoritative execution roadmap for the project.

## Operating model

ChatGPT: research, architecture, verification, review, milestone definition.

Claude Code: repository inspection, implementation, tests, local commands, refactoring, fixes.

Neither model is a source of truth. Completion requires evidence.

## Evidence hierarchy

1. Actual exchange response
2. Official exchange documentation
3. Official SDK source code
4. Deterministic tests
5. Reputable third-party implementation
6. AI reasoning

## Evidence labels

- VERIFIED — confirmed by official source
- OBSERVED — directly seen in a real response/runtime
- TESTED — deterministic test proves expected behavior
- ASSUMPTION — reasonable but unverified
- UNKNOWN — insufficient evidence

## Day 0 — Foundation

### M0.1 Repository and controls

- [x] Create private GitHub repository
- [x] Establish repository as source of truth
- [ ] Add project-control documentation
- [ ] Add Python project scaffold
- [ ] Add pytest, ruff, mypy
- [ ] Add pre-commit
- [ ] Add GitHub Actions CI
- [ ] Confirm all checks pass

Gate: pytest, ruff, mypy, and CI must pass before Day 1 implementation.

## Day 1 — Market data and arbitrage mathematics

### M1.1 Domain models
- [ ] Venue
- [ ] Market
- [ ] Contract
- [ ] OrderBook
- [ ] PriceLevel
- [ ] MarketPair
- [ ] Opportunity
- [ ] Use Decimal for money/prices
- [ ] Deterministic validation tests

### M1.2 Kalshi market-data adapter
- [ ] Verify official endpoints
- [ ] Observe real response
- [ ] Normalize into internal models
- [ ] Save sanitized fixture
- [ ] Add offline tests
- [ ] No execution code

### M1.3 Polymarket US market-data adapter
- [ ] Verify official endpoints
- [ ] Observe real response
- [ ] Normalize into internal models
- [ ] Save sanitized fixture
- [ ] Add offline tests
- [ ] No execution code

### M1.4 Manual market-pair registry
- [ ] Create verified-pair config
- [ ] Record outcome mapping and resolution notes
- [ ] Block unverified pairs from paper/live trading

### M1.5 Arbitrage engine
- [ ] Same-market complete-set logic
- [ ] Cross-venue YES/NO logic
- [ ] Fees
- [ ] Depth
- [ ] Slippage reserve
- [ ] Data freshness
- [ ] Executable quantity
- [ ] Expected profit
- [ ] Exact synthetic tests

Day 1 gate: live scanner can consume normalized books and emit evidence-backed paper opportunities.

## Day 2 — WebSockets, recording, replay, paper execution

### M2.1 Live book state
- [ ] REST snapshot initialization
- [ ] WebSocket updates
- [ ] Disconnect detection
- [ ] Stale-data handling
- [ ] Reconnect/resync
- [ ] Trading disabled on unhealthy market data

### M2.2 Recorder
- [ ] DuckDB
- [ ] Order-book data
- [ ] Opportunities
- [ ] Orders/fills
- [ ] Positions/PnL
- [ ] Health events

### M2.3 Replay adapter
- [ ] Replay recorded sessions through same strategy interface

### M2.4 Paper broker
- [ ] Latency
- [ ] Partial fills
- [ ] Available depth
- [ ] Rejections
- [ ] Slippage
- [ ] Cancellation
- [ ] Leg-risk simulation

### M2.5 Risk manager
- [ ] Max position
- [ ] Max exposure
- [ ] Max daily loss
- [ ] Max order size
- [ ] Minimum net edge
- [ ] Maximum data age
- [ ] Maximum unhedged time
- [ ] Consecutive-error limit
- [ ] Kill switch

Day 2 gate: real market data -> arbitrage detector -> paper broker -> positions/PnL -> persistent evidence.

## Day 3 — Verification and productization

### M3.1 Dashboard
- [ ] Venue health
- [ ] WebSocket state
- [ ] Verified pairs
- [ ] Current opportunities
- [ ] Paper orders/fills
- [ ] Positions/PnL
- [ ] Risk state
- [ ] Latency/data age

### M3.2 Failure testing
- [ ] Venue disconnects
- [ ] Stale prices
- [ ] Empty/malformed books
- [ ] Fee mismatch
- [ ] Partial/one-leg fills
- [ ] Duplicate messages/orders
- [ ] API timeout/rate limit
- [ ] Invalid contract mapping
- [ ] Database/process restart

### M3.3 Paper performance report
- [ ] Opportunities observed/rejected
- [ ] Paper trades
- [ ] Fill and partial-fill rates
- [ ] Mean/median edge
- [ ] Opportunity duration
- [ ] Depth
- [ ] Leg-risk events
- [ ] Paper PnL and drawdown

### M3.4 Live broker interface
- [ ] Interface may exist
- [ ] LIVE_TRADING remains false by default

## Real-money gate

Real money remains locked until all are verified:

- [ ] Official API behavior
- [ ] Stable live market data
- [ ] Successful paper execution
- [ ] Fee reconciliation
- [ ] Contract equivalence
- [ ] Partial-fill behavior
- [ ] Stale-data handling
- [ ] Disconnect/reconnect behavior
- [ ] Duplicate-order prevention
- [ ] Position/order reconciliation
- [ ] Kill switch
- [ ] Position limits
- [ ] Daily loss limits
- [ ] Credential isolation
- [ ] Live mode cannot activate accidentally

## Milestone workflow

For every milestone:

1. Research and verify requirement.
2. Give Claude Code one bounded implementation task.
3. Claude inspects repository before changing anything.
4. Claude implements only the agreed scope.
5. Claude runs required checks.
6. Review evidence independently.
7. Fix conflicts or failures.
8. Commit only when gate passes.
9. Advance to next milestone.

No giant prompts. No silent architectural redesign. No feature without a verified need.
