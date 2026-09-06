# Market Pairing

How this project decides that a Kalshi contract and a Polymarket US contract are
"the same bet" — and why that decision is made by a human, recorded in a file,
and enforced by code that fails closed.

Milestone: **M1.4**. Registry code: `src/prediction_market_arbitrage/registry/`.
Curated data: `src/prediction_market_arbitrage/registry/data/market_pairs.toml`
— which **ships with zero pairs**. Worked format examples live only in this
document and in `tests/test_market_pair_registry.py`, and use obviously
synthetic identifiers (`kalshi-test-market`, `polymarket-test-market`) so nobody
mistakes them for a reviewed pair.

---

## 1. Why contract matching is dangerous

A cross-venue arbitrage assumes that two contracts pay out **the same dollars in
the same real-world states of the world**. If that assumption is even slightly
wrong, a position that looks perfectly hedged is actually a **directional bet**
with leverage and fees working against you.

The failure is asymmetric: a correct pair earns a small edge; an incorrect pair
can lose the full notional on one leg. So the bar for calling two contracts
equivalent must be high, and "the titles look alike" is nowhere near it.

Price convergence is **not** evidence either. Two unrelated contracts can trade
at similar prices for unrelated reasons.

## 2. Superficially similar, economically different — worked examples

These are the shapes of mistake the review checklist exists to catch. (They are
illustrative, not claims about specific live markets.)

| Both titled roughly… | The trap |
|---|---|
| "NYC high temperature above 73° today" | Different **observation window** (calendar day vs. rolling 24h), different **station**, different **rounding** (whole degrees vs. tenths), different **data provider** (The Weather Company vs. NWS). "Above" vs. "at or above" flips edge cases. |
| "Will Team X win the championship" | Different **event scope** (league title vs. conference title), different **void rules** if the season is shortened, different handling of a **tie/co-champions**, different **as-of date** for "the roster". |
| "Fed hikes at the next meeting" | Different **meeting** referenced, different **threshold** (>0bps vs. ≥25bps), different treatment of an **inter-meeting** move, different **announcement vs. effective** timing. |
| "BTC above $100k on Dec 31" | Different **price source/index**, different **snapshot time**, different **timezone**, inclusive vs. exclusive of exactly $100,000.00. |
| "Yes" on venue A vs. "No" on venue B | Correct *direction* mapping is easy to get backwards. A `COMPLEMENTARY` pairing that is actually `IDENTICAL` (or vice-versa) turns a hedge into a doubled directional position. |

## 3. The manual verification checklist

A pair may be marked `VERIFIED` only when a human has confirmed **every** item
below against **both venues' primary settlement rules** (not marketing copy, not
the API title) and recorded the pinned source URLs for each leg. The registry
loader refuses a `VERIFIED` record that is missing any item.

| Checklist key | Question the reviewer must answer |
|---|---|
| `same_underlying_event` | Is it literally the same event / proposition, not a near-cousin? |
| `same_cutoff_or_observation_time` | Same last-trade time and same measurement/observation window? |
| `same_timezone` | Are all the times in the rules the same timezone once normalized? |
| `same_settlement_authority` | Same data provider / adjudicating body for the result? |
| `same_measurement_definition` | Same metric, same units, same rounding/precision? |
| `same_threshold_inclusivity` | ">" vs. "≥", "before" vs. "on or before" — identical on both? |
| `same_cancellation_void_rules` | Postponement, cancellation, ties, 50-50 resolution handled the same? |
| `same_outcome_direction` | Does the chosen `relation` (IDENTICAL / COMPLEMENTARY) actually hold? |
| `same_event_scope` | Same geographic / competition / entity scope, not a superset or subset? |
| `wording_differences_reviewed` | Every material wording difference read and judged immaterial? |
| `venue_settlement_asymmetry_reviewed` | Any venue-specific settlement quirk (early expiry, provisional data, fee-on-settlement) assessed? |

Plus: `reviewer`, `verified_at` (timezone-aware), `settlement_notes`, and
`known_differences` — which may be an empty list **only if**
`known_differences_reviewed = true` (a reviewer explicitly affirms there are no
material differences, rather than leaving the field blank).

None of this is automated. The registry stores and enforces the human's answers.

## 4. Why not automate the matching?

| Approach | Why it is rejected (for now) |
|---|---|
| **Title-string matching** | Titles are marketing text, not contract law. Equal titles routinely mean different settlement; different titles routinely mean the same settlement. Zero signal about void rules, timing, or authority. |
| **Fuzzy / embedding similarity** | Optimizes for "reads similarly", which is exactly the failure mode. A high similarity score on two contracts with a 6-hour cutoff difference is worse than useless — it manufactures false confidence. |
| **LLM semantic matching** | Plausible-sounding equivalence judgements with no calibrated error bound, not reproducible, and not auditable at the moment money is at risk (D-004: LLMs are out of the deterministic trading path). Deferred, not banned — it may later *propose* candidates for human review, never *approve* them. |
| **Hardcoded pair logic inside the arbitrage engine** | Buries risk decisions in code diffs, couples strategy to specific markets, and makes review a code review instead of a settlement-rules review. A version-controlled data file with a fail-closed loader keeps the decision visible, diffable, and separate from the math. |

The chosen architecture — a curated file + a strict loader + a `VERIFIED`-only
`eligible()` API — is the smallest thing that makes the risk decision explicit,
human-owned, reviewable in a Git diff, and impossible to bypass by accident.

## 5. How status affects trading eligibility

| Status | Meaning | `eligible()` returns it? |
|---|---|---|
| `DRAFT` | Entered, not reviewed. | No |
| `REVIEW_REQUIRED` | Review in progress, not affirmed. | No |
| `VERIFIED` | Human-affirmed settlement equivalence, full checklist, sources on file. | **Yes** |
| `REJECTED` | Reviewed and found not equivalent. Kept so it is not re-proposed. | No |
| `SUSPENDED` | Was usable; withdrawn pending re-review (e.g. a venue changed its rules). | No |

`load_registry()` **fails closed**: a malformed record, an unknown status, a
duplicate `pair_id`, or a conflicting venue mapping raises `RegistryError` and
**no** registry is returned. There is no "load the good ones and skip the bad
ones".

### `VERIFIED` is not "approved for live trading"

`eligible()` means *"a strategy may compare these two contracts in paper
arbitrage analysis"*. It does **not** mean the pair is cleared for real money.
Live use has additional, still-open blockers:

- **A-013 / A-015 / A-016** — unresolved Polymarket US market/book semantics
  (which side the single book represents; whether slug-only identifiers suffice
  for order routing/reconciliation; whether the normalized `Market.title` is
  correct). See `docs/ASSUMPTIONS.md`.
- **A-001 / A-002 / A-003** — cross-venue equivalence, lossless normalization,
  and paper-execution realism are all still UNVERIFIED.
- The Real-money gate in `docs/ROADMAP.md`.

Therefore, in M1.4, `live_use_eligible` **must be `false` on every record** — the
loader rejects `true` — and every record must carry a non-empty
`blocking_reason`. Pair verification resolves *contract equivalence*; it does not
and cannot override the other live-use blockers.
