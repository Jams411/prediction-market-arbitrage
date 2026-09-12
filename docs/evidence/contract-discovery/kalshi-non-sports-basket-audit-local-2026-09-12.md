# Local Kalshi non-sports basket audit — 2026-09-12

Recorded at: 2026-09-12T15:24:43.662787+00:00
Agent: Codex
Model: unknown
Reviewer: ChatGPT
Status: public metadata/rules OBSERVED; analytical classifications, local review pending.

**Result: no COMPLETE_BASKET_CANDIDATE.** Three parent events, 22 returned
active children, no further event search. The audited position is one YES unit
in every listed child, not YES+NO within each child and not a synthetic portfolio
with altered weights. No basket is approved for pricing or execution.

Selection: one upcoming Fed decision, then one open NYC-temperature event and one
open CPI event (each series query limited to one parent). All are non-sports.
Selection did not use prices, volumes or books. Prior context:
[strategy reassessment](strategy-reassessment-local-2026-09-12.md).

## Exact metadata inventory

### KXFEDDECISION-26SEP — INCOMPLETE

Fed decision in Sep 2026? Series `KXFEDDECISION`. Metadata `mutually_exclusive=true`, `collateral_return_type=MECNET`.

| Exact child ID | Displayed YES outcome |
|---|---|
| `KXFEDDECISION-26SEP-C26` | Cut >25bps |
| `KXFEDDECISION-26SEP-C25` | Cut 25bps |
| `KXFEDDECISION-26SEP-H0` | Fed maintains rate |
| `KXFEDDECISION-26SEP-H25` | Hike 25bps |
| `KXFEDDECISION-26SEP-H26` | Hike >25bps |

All returned children were active. Common metadata expiration: `2026-12-16T18:01:00Z`.

### KXHIGHNY-26SEP12 — AMBIGUOUS

Highest temperature in New York City on Sep 12, 2026? Series `KXHIGHNY`. Metadata `mutually_exclusive=true`, `collateral_return_type=MECNET`.

| Exact child ID | Displayed YES outcome |
|---|---|
| `KXHIGHNY-26SEP12-T75` | 74° or below |
| `KXHIGHNY-26SEP12-B75.5` | 75° to 76° |
| `KXHIGHNY-26SEP12-B77.5` | 77° to 78° |
| `KXHIGHNY-26SEP12-B79.5` | 79° to 80° |
| `KXHIGHNY-26SEP12-B81.5` | 81° to 82° |
| `KXHIGHNY-26SEP12-T82` | 83° or above |

All returned children were active. Common metadata expiration: `2026-09-19T14:00:00Z`.

### KXCPI-26SEP — NOT_MUTUALLY_EXCLUSIVE

CPI in September Series `KXCPI`. Metadata `mutually_exclusive=false`, `collateral_return_type=DIRECNET`.

| Exact child ID | Displayed YES outcome |
|---|---|
| `KXCPI-26SEP-T-0.4` | Above -0.4% |
| `KXCPI-26SEP-T-0.3` | Above -0.3% |
| `KXCPI-26SEP-T-0.2` | Above -0.2% |
| `KXCPI-26SEP-T-0.1` | Above -0.1% |
| `KXCPI-26SEP-T0.0` | Above 0.0% |
| `KXCPI-26SEP-T0.1` | Above 0.1% |
| `KXCPI-26SEP-T0.2` | Above 0.2% |
| `KXCPI-26SEP-T0.3` | Above 0.3% |
| `KXCPI-26SEP-T0.4` | Above 0.4% |
| `KXCPI-26SEP-T0.5` | Above 0.5% |
| `KXCPI-26SEP-T0.6` | Above 0.6% |

All returned children were active. Common metadata expiration: `2027-01-13T13:56:00Z`.

## State-space findings

### Fed decision: INCOMPLETE

Identity: September 16, 2026 FOMC decision; source Federal Reserve. Displayed
signed-change buckets are Δ < −25bp, Δ = −25bp, Δ = 0, Δ = +25bp, Δ > +25bp.
Under those intended labels, they are disjoint but omit −25 < Δ < 0 and
0 < Δ < 25. A +10bp change gives zero YES payouts. FEDDECISION defines actions
without restricting changes to 25bp multiples; ordinary convention is insufficient
to delete these states. There is no “other” child. Thus a complete partition
cannot be established, even before exceptional settlement review.

Additional ambiguity: C26's title says cut >25bp, but `rules_primary` says cut
25bp with extra whitespace; it duplicates C25 semantically. Do not silently
repair it from the ticker. Metadata and secondary rules assert at most one YES,
not at least one. Intended-label exclusivity is supported, but the raw text
conflict prevents a fully authoritative child mapping. INCOMPLETE records the
independent missing-state defect; it does not claim the text conflict is resolved.

Cancellation is explicitly covered: a canceled scheduled meeting not held on its
scheduled date makes H0 YES and the others NO (sum 1). No-change is H0; a sporting
tie is inapplicable. The reviewed terms refer unresolved expiration values to
Rule 6.3(b); no event-wide normalization guarantee was established. Post-expiry
revisions are ignored. Different actions outside the listed buckets, unusual
range changes and unresolved source values remain unproven. No special refund
or multi-winner state restoring completeness was found in the reviewed terms.

### NYC temperature: AMBIGUOUS

Identity: maximum temperature at New York City station CLINYC, September 12,
2026. Target metadata names The Weather Company; linked GLOBALTEMPERATURE terms
instead list weather-service sources. Treat target-source precedence as unresolved,
not an automatic source substitution. The target also permits delaying expiration
for materially erroneous initial non-preliminary data.

If the final value T is an integer Fahrenheit reading, the six predicates
T < 75; 75 ≤ T ≤ 76; 77 ≤ T ≤ 78; 79 ≤ T ≤ 80; 81 ≤ T ≤ 82; T > 82
are disjoint and exhaustive, with exactly one YES. Both tails are present, so an
“other” bucket is unnecessary on that restricted domain. Equal endpoints belong
to their inclusive interval; there is no separate tie or multi-winner outcome.

But the terms specify source precision and inclusive ranges; they do not establish
an integer-only final value for this target. At T = 76.5, 78.5 or 80.5 none of the
literal ranges wins. This is a conditional counterexample, not a claim that such
a reading has actually been published. Source precision must be proved before
turning the conditional integer partition into a complete basket.

Independently, no data by expiration triggers last fair prices determined by the
Exchange. For six YES settlements q1,...,q6, the reviewed sources do not prove
Σqi = 1. No numerical fair prices are assumed. MECNET is collateral metadata,
not by itself evidence of this settlement identity. A data outage is not an
ordinary numeric outcome; no-data, unresolved revisions and possible review
payouts cannot be discarded. A separate cancellation/void/refund rule guaranteeing
the same combined unit payout was not established. Therefore all-state completeness
is UNKNOWN and the basket is rejected from candidate status.

### CPI: NOT_MUTUALLY_EXCLUSIVE

Identity: signed seasonally adjusted CPI-U one-month change for September 2026,
published by BLS, using its one-decimal value. Eleven strict greater-than
thresholds run from −0.4% through +0.6% in 0.1-point increments. Metadata explicitly
sets `mutually_exclusive=false`. At +0.7%, all eleven YES contracts win (sum 11);
at −0.4%, none wins (sum 0). At an exact threshold, that child is NO while lower
thresholds can be YES. Neither mutual exclusivity nor exhaustive coverage holds;
these are nested predicates, not disjoint buckets. No “other” child fixes that.
Multiple winners are ordinary and intentional, not an exceptional tie.

CPI terms specify a missing-data fallback derived from the latest index and its
12-month-prior value. Target rules extend expiry for shutdown-related delay to
the earlier of data release or six months after shutdown ends. Generic terms
and metadata have timing differences; no need to resolve them to demonstrate
overlapping ordinary payoffs. A common scalar fallback would still leave nested
predicates, not a partition. Post-expiry revisions are excluded; review discretion
remains. No cancellation, void or refund guarantee that converts this ladder into
a unit-payout basket was established. No reweighting or related-market strategy
was evaluated.

## Evidence provenance and limits

Public GETs (six metadata requests; only three distinct parent events):

- `https://external-api.kalshi.com/trade-api/v2/events/KXFEDDECISION-26SEP?with_nested_markets=true`
- `https://external-api.kalshi.com/trade-api/v2/events?series_ticker=KXHIGHNY&status=open&limit=1&with_nested_markets=true`
- `https://external-api.kalshi.com/trade-api/v2/events?series_ticker=KXCPI&status=open&limit=1&with_nested_markets=true`
- `https://external-api.kalshi.com/trade-api/v2/series/KXFEDDECISION`
- `https://external-api.kalshi.com/trade-api/v2/series/KXHIGHNY`
- `https://external-api.kalshi.com/trade-api/v2/series/KXCPI`

Only returned metadata is asserted; no raw response dump is committed. Incidental
quote fields in metadata were neither used nor copied into this note. Search was
used only to locate the Fed event; third-party snippets are not settlement evidence.

Official documents obtained from each series' `contract_terms_url`:

- [FEDDECISION](https://assets.kalshi.com/contract_terms/FEDDECISION.pdf): SHA-256 `54d560744b93d7cc2b5724d08ee8dd93f2a7c22d41d0ad3d01ead89cb76ca5f9`.
- [GLOBALTEMPERATURE](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf): SHA-256 `160281687cf9d3cd694c1c419522f3d53a8e1a6d4eddd40a7f5559c3a06211d0`.
- [CPI](https://assets.kalshi.com/contract_terms/CPI.pdf): SHA-256 `2317b1d8e823082b409f6ff3415fb135804d9682681f9f92f640b3681b29a872`.

Locators: FEDDECISION Underlying/action/Payout Criterion/Contingencies;
GLOBALTEMPERATURE Source Agency/comparison operators/Additional clarifications;
CPI Underlying/Payout Criterion/missing-data fallback/Contingencies. PDF text was
extracted locally. General Rulebook clauses were not newly audited; their cited
contingencies remain unknown rather than assumed favorable.

## Dominant blocker and exactly one next research direction

The dominant blocker is proving a complete payout state space, rather than finding
mutually exclusive-looking labels: missing action intervals, precision ambiguity,
and unproven aggregate exceptional payouts. Same venue alone is insufficient.

Next: a bounded public-rulebook research pass on **MECNET event-group settlement
invariants**, using only the already inspected weather event as context. Determine
whether any authoritative rule guarantees aggregate YES settlement of exactly one
under missing-data/review outcomes, and distinguish collateral netting from payout
normalization. Return a supported guarantee or explicit unresolved/negative finding
before browsing additional candidate events or considering prices. This is one
research direction, not authorization to implement a strategy or relax the standard.

## Local validation and safety

Inventory reconciled: 5 Fed + 6 temperature + 11 CPI = 22 distinct active child IDs;
three allowed classifications, zero survivors. Decimal boundary checks reproduce
the Fed gap, conditional integer weather partition/fractional gap, and CPI overlap.
These checks validate the stated algebra, not venue semantics. Local links and
`git diff --check` validated. No full production suite; no engine invocation.
Prior local reassessment and Demo changes preserved; no commit, push or PR.
No venue authentication, account data, books, prices used, orders, registry/policy
changes, strategy/execution, risk-control, Demo-cap or LIVE_TRADING changes.
