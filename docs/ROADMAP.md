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
- [x] Add project-control documentation
- [x] Add Python project scaffold
- [x] Add pytest, ruff, mypy
- [x] Add pre-commit
- [x] Add GitHub Actions CI
- [x] Confirm all checks pass

Gate: pytest, ruff, mypy, and CI must pass before Day 1 implementation.

## Day 1 — Market data and arbitrage mathematics

### M1.1 Domain models
- [x] Venue
- [x] Market
- [x] Contract
- [x] OrderBook
- [x] PriceLevel
- [x] MarketPair
- [x] Opportunity
- [x] Use Decimal for money/prices
- [x] Deterministic validation tests

### M1.2 Kalshi market-data adapter
- [x] Verify official endpoints
- [x] Observe real response
- [x] Normalize into internal models
- [x] Save sanitized fixture
- [x] Add offline tests
- [x] No execution code

### M1.3 Polymarket US market-data adapter
- [x] Verify official endpoints
- [x] Observe real response
- [x] Normalize into internal models
- [x] Save sanitized fixture
- [x] Add offline tests
- [x] No execution code

### M1.4 Manual market-pair registry
- [x] Create verified-pair config
- [x] Record outcome mapping and resolution notes
- [x] Block unverified pairs from paper/live trading

### M1.5 Arbitrage engine
- [x] Same-market complete-set logic
- [x] Cross-venue YES/NO logic
- [x] Fees
- [x] Depth
- [x] Slippage reserve
- [x] Data freshness
- [x] Executable quantity
- [x] Expected profit
- [x] Exact synthetic tests

Day 1 gate: live scanner can consume normalized books and emit evidence-backed paper opportunities.

## Day 2 — WebSockets, recording, replay, paper execution

### M2.1 Live book state
- [x] REST snapshot initialization
- [x] WebSocket updates
- [x] Disconnect detection
- [x] Stale-data handling
- [x] Reconnect/resync
- [x] Trading disabled on unhealthy market data

### M2.2 Recorder
- [x] DuckDB
- [x] Order-book data
- [x] Opportunities
- [x] Orders/fills
- [x] Positions/PnL
- [x] Health events

### M2.3 Replay adapter
- [x] Replay recorded sessions through same strategy interface

### M2.4 Paper broker
- [x] Latency
- [x] Partial fills
- [x] Available depth
- [x] Rejections
- [x] Slippage
- [x] Cancellation
- [x] Leg-risk simulation

### M2.5 Risk manager
- [x] Max position
- [x] Max exposure
- [x] Max daily loss
- [x] Max order size
- [x] Minimum net edge
- [x] Maximum data age
- [x] Maximum unhedged time
- [x] Consecutive-error limit
- [x] Kill switch

Day 2 gate: real market data -> arbitrage detector -> paper broker -> positions/PnL -> persistent evidence.

## Day 3 — Verification and productization

### M3.1 Dashboard
- [x] Venue health
- [x] WebSocket state
- [x] Verified pairs
- [x] Current opportunities
- [x] Paper orders/fills
- [x] Positions/PnL
- [x] Risk state
- [x] Latency/data age

### M3.2 Failure testing
- [x] Venue disconnects
- [x] Stale prices
- [x] Empty/malformed books
- [x] Fee mismatch
- [x] Partial/one-leg fills
- [x] Duplicate messages/orders
- [x] API timeout/rate limit
- [x] Invalid contract mapping
- [x] Database/process restart

### M3.3 Paper performance report
- [x] Opportunities observed/rejected
- [x] Paper trades
- [x] Fill and partial-fill rates
- [x] Mean/median edge
- [x] Opportunity duration
- [x] Depth
- [ ] Leg-risk events — the report has the section but it is always "unavailable": the M2.2 recorder has no leg-risk table, so there is no data to aggregate (`perf_report/build.py`; D-022)
- [x] Paper PnL and drawdown

### M3.4 Live broker interface
- [x] Interface may exist
- [x] LIVE_TRADING remains false by default

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
