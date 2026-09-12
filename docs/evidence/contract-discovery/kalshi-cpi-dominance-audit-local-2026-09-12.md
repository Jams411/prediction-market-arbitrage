# Local CPI nested-threshold audit — 2026-09-12

Agent: Codex
Model: GPT-6
Reviewer: pending
Classification: **INCONCLUSIVE**

Ordinary-state dominance is proved; an all-material-state settlement guarantee
is not established. No deterministic structural-arbitrage candidate is approved.

## Family and exact ordinary semantics

Reuse the OBSERVED inventory in the [existing basket audit](kalshi-non-sports-basket-audit-local-2026-09-12.md):
parent `KXCPI-26SEP`, series `KXCPI`, September 2026;
`mutually_exclusive=false`, `collateral_return_type=DIRECNET`.
No metadata refresh; captured active status is not a current-status assertion.

Each suffix below follows `KXCPI-26SEP-`:

| Suffix | Threshold (%) |
|---|---:|
| T-0.4 | -0.4 |
| T-0.3 | -0.3 |
| T-0.2 | -0.2 |
| T-0.1 | -0.1 |
| T0.0 | 0.0 |
| T0.1 | 0.1 |
| T0.2 | 0.2 |
| T0.3 | 0.3 |
| T0.4 | 0.4 |
| T0.5 | 0.5 |
| T0.6 | 0.6 |

Primary [CPI terms](https://assets.kalshi.com/contract_terms/CPI.pdf), pp. 1–2:
X is BLS's signed one-month, one-decimal seasonally adjusted CPI-U percent change.
For threshold k, YES pays $1 iff X > k; ordinary NO pays $1 iff X <= k.
Equality is NO. Select `KXCPI-26SEP-T0.2` (a=0.2) and
`KXCPI-26SEP-T0.3` (b=0.3). The PDF's default listing range starts at zero
but allows modified levels; negative inventory is retained as observed, not
independently certified by that default range. The selected pair avoids this issue.

The missing-data formula is (latest CPI index / index 12 months earlier)^(1/12)-1.
One common computable result preserves nesting. Unit conversion/rounding must be
consistent; no numerical fallback value is assumed. Post-expiration revisions
are excluded. Contingencies allow Rule 6.3(b) payout determination if no expiration
value can be determined. The prior capture also records shutdown-related delay
and a generic/target expiration discrepancy; precedence is unresolved here.

## Logical proof (ordinary shared scalar)

For a < b, X > b implies X > a by transitivity. Also X <= a implies X <= b.
Thus Y_a >= Y_b and N_a <= N_b, with Y_k=1[X>k], N_k=1-Y_k.

| State | Y_a | Y_b | N_b | Y_a + N_b |
|---|---:|---:|---:|---:|
| X <= a, including X=a | 0 | 0 | 1 | 1 |
| a < X <= b, including X=b | 1 | 0 | 1 | 2 |
| X > b | 1 | 1 | 0 | 1 |

This proof extends to every ordered pair in the inventory, conditional on exact
listed predicates sharing the same scalar. Decimal checks cover all 55 pairs,
24 values including boundaries, intervening points and tails: 1,320 assertions
of ordering and payout lower bound passed. This tests algebra, not exchange behavior.

## Exceptional-state audit

The [CFTC-hosted November 2024 rulebook](https://www.cftc.gov/sites/default/files/filings/orgrules/24/11/rules1114248723.pdf),
Rules 6.3(a)–(b), 7.1 and 7.2, provides ordinary long/short allocation,
contract-level last-trade/fair allocation, discretionary review for unreliable
underlyings, and announced source/timing modifications. Reused primary evidence
from the [MECNET audit](kalshi-mecnet-settlement-audit-local-2026-09-12.md);
it is historical, not verified as today's consolidated rulebook. The prior
current-document 429/404 limitation remains; no repeated download attempts.

| Material state | Ordering conclusion |
|---|---|
| Normal BLS release, common value/cutoff | Proved. |
| Missing monthly release, common computable fallback | Proved conditionally; formula changes the scalar, not predicate nesting. |
| Delayed release/common delayed cutoff | Preserved if all children retain the same scalar and rules. Target/PDF timing precedence remains unresolved. |
| Revision ignored after common expiration | Preserved. Different cutoffs or contract-specific review are not proved equivalent. |
| Invalid/unavailable underlying; fallback inputs also unusable | Rule 6.3(b) allocation/review is the precise proof blocker. No reviewed clause imposes q_a >= q_b across contracts. |
| Source replacement, discretionary fair allocation, cancellation/review | No all-state common-value or ordered-payout guarantee established. No automatic normalized refund assumed. |

The current [Kalshi directional collateral explanation](https://help.kalshi.com/en/articles/13823816-collateral-return)
supports ordinary nested implications and early return of the covered payout.
It does not specify how fair allocations across strikes remain ordered. DIRECNET
metadata therefore does not close this gap. Returned collateral must not be
counted again as final settlement proceeds.

For scalar payouts, even assuming within-child NO=1-YES, the pair pays
1+q_a-q_b. A guarantee requires q_a>=q_b in every material state. Discretion is
not itself proof that a reversed allocation is allowed: no actual reversal or
authoritatively permitted counterexample was established. Hence INCONCLUSIVE,
not DOMINANCE_NOT_GUARANTEED or DOMINANCE_GUARANTEED.

## Pricing implication and next milestone

Only conditionally, if all-state dominance and common settlement timing were
proved, frictionless values would obey pYES(a)>=pYES(b) and pNO(a)<=pNO(b).
An executable all-in purchase of YES(a)+NO(b) below its guaranteed $1 lower bound
would then be a candidate. Today that lower bound is unproved in exceptional
states: a price inversion is not a deterministic arbitrage signal. No books,
prices, fees, liquidity, fill feasibility or profit estimates were obtained.

One next direction: **single-contract YES/NO complement conservation**. Audit
whether one binary contract's two sides retain a combined unit payout or equivalent
close-out credit under fair settlement, voiding and review, using primary exchange
and clearing rules. Deliver one rules-only state matrix; reject if conservation
cannot be proved. This avoids cross-strike ordering but is not preapproved as safe
or profitable. No implementation or market-data collection in this milestone.

## Local verification and scope

Local CPI PDF SHA-256 matches prior evidence:
`2317b1d8e823082b409f6ff3415fb135804d9682681f9f92f640b3681b29a872`.
Public PDF text rechecked; light Decimal checks and `git diff --check` passed.
No full production suite for this documentation-only audit. Prior changes preserved.
No commit/push/PR, venue authentication, books/prices, orders, execution,
registry/policy/risk changes, Demo-cap changes or LIVE_TRADING changes.
