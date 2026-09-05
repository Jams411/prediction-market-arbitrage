# Assumptions Register

Every unverified project assumption must be recorded here before implementation depends on it.

## Status values

- UNVERIFIED
- VERIFIED
- REJECTED
- SUPERSEDED

## Rules

- An assumption cannot silently become a fact.
- Any assumption affecting market equivalence, pricing, fees, execution, risk, or live behavior must be resolved before real-money use.
- If evidence conflicts with an assumption, update this file and the related decision or implementation.

## Current assumptions

| ID | Assumption | Status | Blocks live use? |
|---|---|---|---|
| A-001 | Exact cross-venue contract equivalence can be established through explicit resolution-term review. | UNVERIFIED | Yes |
| A-002 | Venue data can be normalized into a shared internal order-book representation without losing required execution information. | UNVERIFIED | Yes |
| A-003 | Paper execution can approximate enough fill, latency, and leg-risk behavior to support a go/no-go decision for limited live testing. | UNVERIFIED | Yes |
