# Risk Controls

Live trading is disabled during the initial build and paper-testing phases.

## Required controls before live use

- maximum position per market
- maximum total exposure
- maximum order size
- maximum daily loss
- minimum net edge
- maximum market-data age
- maximum unhedged time
- maximum consecutive data/API errors
- duplicate-order prevention
- position/order reconciliation
- explicit kill switch
- explicit live-trading enablement

## Safety invariants

1. Risk approval occurs before any broker receives an order request.
2. Unhealthy or stale market data disables new trading decisions.
3. Unverified contract pairs cannot enter paper/live execution.
4. Live mode is off by default and cannot activate merely because credentials are present.
5. Secrets are never committed to the repository.
6. A failed hedge leg must be surfaced as an explicit risk event rather than hidden in aggregate P&L.

## Real-money gate

Passing unit tests alone is insufficient. Required evidence is tracked in `ROADMAP.md` and `TEST_PLAN.md`.
