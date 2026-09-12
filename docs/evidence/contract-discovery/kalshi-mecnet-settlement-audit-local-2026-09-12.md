# Local MECNET settlement audit — 2026-09-12

Agent: Codex
Model: GPT-6
Reviewer: pending
Classification: **COLLATERAL_NETTING_ONLY**

MECNET does not establish an event-wide unit-payout guarantee. This classification
describes the supported role of the metadata, not proof that Kalshi will choose
unnormalized settlements. Exceptional aggregate payout remains INCONCLUSIVE.
No complete basket candidate is approved.

## Primary evidence and limits

1. [Kalshi Collateral Return](https://help.kalshi.com/en/articles/13823816-collateral-return),
   mutually exclusive collateral return section, accessed 2026-09-12.
   It describes early return of collateral for hedged positions, normally on NO
   sides. Its example explicitly permits every listed market to resolve NO.
   Accordingly, mutually exclusive groups need not be exhaustive. Early collateral
   return reduces subsequent settlement receipts; it does not create an additional
   payoff. Gross contractual payout and remaining cash due must be distinguished.
2. [Official OpenAPI schema](https://docs.kalshi.com/openapi.yaml), EventData
   `collateral_return_type` and `mutually_exclusive`, local lines 8790–8795.
   The former describes collateral return; the latter says only one market can
   resolve YES. The schema does not define the literal MECNET acronym or require
   at least one YES. Operational interpretation: mutually exclusive contract
   netting / collateral return. This expansion is descriptive, not a verified
   verbatim official expansion of the code. Schema SHA-256:
   `cac311c870e469ddfbceedfd363fe9e9b54e1996e4d00eeeb327fdbff84af915`.
3. [GLOBALTEMPERATURE terms](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf),
   pp. 1–3, especially Additional clarifications and Contingencies.
   Missing data at expiration sends every strike to an Exchange-determined last
   fair price. Full source precision governs; the first official non-preliminary
   report is used, and post-expiration revisions are excluded. The terms refer
   unresolved values to Rule 7.1. They contain no sum-to-one instruction.
   Downloaded bytes match the prior evidence SHA-256:
   `160281687cf9d3cd694c1c419522f3d53a8e1a6d4eddd40a7f5559c3a06211d0`.
4. [Kalshi rulebook filing, November 14, 2024](https://www.cftc.gov/sites/default/files/filings/orgrules/24/11/rules1114248723.pdf),
   v1.14, Rules 6.3, 7.1, 7.2 (clean copy PDF pp. 43–45; tracked copy pp. 106–108).
   Rule 6.3 supplies ordinary long/short settlement and discretionary allocation
   when the criterion cannot be determined, including unmeasurable data. The
   committee selects fair allocation if a last trade is unavailable or unsuitable.
   Rule 7.1 permits review for underlying reliability/transparency problems;
   Rule 7.2 permits announced source/underlying changes and expiration delays.
   These clauses operate at contract level and supply no event normalization.
   **Historical primary evidence, not verified as the latest consolidated rules.**
5. [Kalshi March 2, 2026 amendment](https://kalshi-public-docs.s3.amazonaws.com/regulatory/notices/rules03022640155.pdf),
   Appendix A, p. 3: states March 17 effective date and leaves 6.3(a)–(d)
   unchanged; retains discretionary review under 7.1. Its added death provision
   is not a weather fallback. This is corroboration, not a complete amendment audit.

Current consolidated rulebook retrieval was unsuccessful: Kalshi `/docs/kalshi-rulebook.pdf`
returned HTTP 429; the indexed v1.24 S3 URL returned 404. Search snippets were not
treated as a full rulebook audit. No assertion that every current clearing rule or
amendment was reviewed. This limits exceptional-state certainty; it does not
erase the current help/schema evidence that exclusivity is not exhaustiveness.

## Settlement conclusions

| Question | Supported answer |
|---|---|
| Must a MECNET family be exhaustive? | No; official collateral example permits all NO. |
| Multiple ordinary YES winners? | Inconsistent with the documented mutually-exclusive flag. |
| Multiple nonzero YES payouts? | Fair-price settlement is not the same as resolving YES. The weather fallback does not exclude multiple fractional payouts; actual allocations and group constraints are unverified. |
| All YES payouts zero? | Explicitly possible for a non-exhaustive mutually-exclusive group. Not established as an actual weather outage settlement. |
| Missing or invalid data? | Missing weather data has a discretionary fallback; unreliable data can invoke review/source or timing changes under the cited historical rules. No automatic normalized refund established. |
| Does a complete ordinary partition settle to one in every material state? | Not proved. Ordinary exhaustiveness alone does not constrain discretionary allocations across contracts. |
| Explicit aggregate normalization? | None found in the reviewed primary sources; MECNET is insufficient evidence. |

Mathematically, at-most-one ordinary winner gives sum(q_i) <= 1 for binary
settlements; exhaustiveness is separately needed for equality. Under scalar
settlement, knowing each q_i is a contract payout does not prove sum(q_i) = 1.
Even complementary YES/NO allocation inside each child would not prove an identity
across the six YES legs. No hypothetical fair-price vector is asserted as permitted
by an exhaustive audit of current rules, or as an observed settlement.

## Effect on KXHIGHNY-26SEP12

Reuse the six-child inventory and OBSERVED metadata in the
[existing basket audit](kalshi-non-sports-basket-audit-local-2026-09-12.md);
no event/API refresh was performed. Its active status is historical to that capture.
The event remains **AMBIGUOUS**, not COMPLETE_BASKET_CANDIDATE.
On an integer Fahrenheit domain its displayed buckets form a partition. The prior
fractional-gap counterexamples remain conditional, and the source precedence
conflict remains unresolved. Neither is repaired by MECNET. Even resolving both
would leave exceptional payout normalization unproved.

## Exactly one next milestone

Audit **same-venue nested-threshold dominance**, using the existing KXCPI-26SEP
evidence only: one lower threshold a and higher threshold b, identical underlying,
source and observation window. In ordinary scalar states, YES(T>a) plus NO(T>b)
pays at least one unit, with two inside the interval. This is a lower-bound
relationship, not a complete basket. Prove or reject whether fallback/review
preserves the ordering q_a >= q_b; otherwise reject the relationship too.
Deliver a rules-only state matrix and representation-gap note. No prices, books,
new candidate search, implementation, or execution authorized by this recommendation.

## Local verification

Weather PDF hash matched prior evidence; schema fields and rule locators inspected.
No code/configuration changes or production tests needed. `git diff --check` passed.
Existing feature branch retained; no commit, push or PR. Prior dirty files preserved.
No books, market prices, venue authentication, orders, strategy execution,
registry changes, or safety-control changes. Source prose about fair prices was
reviewed; no trading-price data was requested or used.
