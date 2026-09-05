# Test Plan

Testing is evidence, not ceremony. Each milestone defines what must be proven before advancement.

## Test layers

### Unit tests

Use deterministic synthetic inputs for domain models, arithmetic, validation, strategy rules, and risk rules.

### Fixture tests

Use sanitized real API responses captured from verified integrations. Tests must run offline and deterministically.

### Integration tests

Exercise real external services only when needed and clearly separate them from offline tests.

### Replay tests

Feed recorded market sessions through the same internal interfaces used by live market data.

### Failure tests

Deliberately trigger disconnects, stale data, malformed books, timeouts, partial fills, duplicate messages/orders, and restart scenarios.

## Day 0 gate

- pytest passes
- ruff passes
- mypy passes
- GitHub Actions passes

## Day 1 gate

- domain models validated
- venue fixtures normalized correctly
- exact arbitrage arithmetic proven with known synthetic cases
- unverified market pairs blocked

## Day 2 gate

- disconnect causes unhealthy state
- reconnect/resync restores valid state before trading resumes
- paper broker handles partial fills and rejections
- risk controls gate order flow
- recorded data replays deterministically

## Day 3 gate

- key operational failure cases pass
- paper performance report is generated from persisted evidence
- live execution remains disabled by default

## Completion rule

A feature is not considered complete because code exists. It is complete only when its stated evidence gate passes and the relevant documentation is updated.
