# Contract-equivalence discovery

`scripts/discover_contract_pairs.py` is a bounded, deterministic triage tool for
finding plausible Kalshi / Polymarket US contract pairs. It reads only public
market and parent-event metadata through the repository's GET-only clients.
It does not request credentials, fetch account data, inspect prices, or execute
orders.

Run a one-page observation with:

```bash
.venv/bin/python scripts/discover_contract_pairs.py \
  --kalshi-pages 1 --polymarket-pages 1 --page-size 100 --top 20
```

Page counts are capped at 10 and page size at 100. Output is compact JSON. Raw
API responses are not emitted or persisted.

Polymarket US `comboEnabled` is a capability flag on ordinary base contracts;
it does not mean that the contract is itself a combo. Discovery retains those
contracts. A confirmed combo is excluded only when it has the official
`caoc-` instrument identifier and a valid structured list of 2--10 legs.
Partial or malformed combo structure is reported as `UNKNOWN` and retained for
conservative review. The CLI separately reports ordinary contracts retained,
confirmed combos filtered, and unknown combo status.

Kalshi discovery uses `GET /events?with_nested_markets=true`, which supplies one
authoritative parent record for its child markets and excludes multivariate
events at the venue boundary. Polymarket US retains the bounded `GET /markets`
scan and joins each child to bounded `GET /events` pages. Both paths build an
in-run parent index and report event records fetched, parents used, cache reuse,
missing/ambiguous parents, and structured combo handling. No persistent cache is
created. A missing or ambiguous parent remains unknown rather than being
guessed.

To explain the existing lexical gate without changing it:

```bash
.venv/bin/python scripts/discover_contract_pairs.py \
  --kalshi-pages 10 --polymarket-pages 10 --page-size 100 --top 20 \
  --diagnose --near-misses 20
```

Diagnostic mode keeps `comparisons_considered` as the entire bounded enriched
profile cross-product. The accounting now separates family policy exclusions:

- `family_incompatible_excluded + lexical_evaluated = comparisons_considered`;
- `passed_threshold + rejected_below_threshold = lexical_evaluated`;
- `semantically_evaluated = passed_threshold` in diagnostic mode, which already
  deferred full semantic comparison until after the lexical gate.

Thus excluded rows are neither threshold passes nor threshold rejections. Normal
discovery also applies the policy before comparison; direct `compare_contracts`
remains available for explicit review. Diagnostics report the policy entries,
reason, evidence reference, and NFL/MLB aggregate counts, without excluded rows.
It retains only the requested top
candidate and near-miss examples, so a 1,000 × 1,000 run does not store a
million-row matrix. Each below-threshold example includes the exact lexical
signal and rejection reason, sorted matching tokens, shared and venue-unique
tokens, coarse event/participant/category/date/threshold agreement, and missing
metadata fields. Coarse agreement is diagnostic evidence only.

## Narrow sports-family policy

`sports-family-equivalence-v1` applies after combo filtering and parent
enrichment, before ordinary pair comparison. It contains exactly two
`SYSTEMATICALLY_INCOMPATIBLE` relationships under
`STRICT_RISKLESS_CROSS_VENUE_EQUIVALENCE`, based on the PR #51 family audit
(evidence version 1, effective 2026-09-11):

| Kalshi parent `series_ticker` | Parent Polymarket league | Child `sportsMarketType` |
| --- | --- | --- |
| `KXNFLGAME` | `nfl` | `football_team_full_game_winner` |
| `KXMLBGAME` | `mlb` | `baseball_team_full_game_winner` |

Both require child `marketType=moneyline` and
`sportsMarketTypeV2=SPORTS_MARKET_TYPE_MONEYLINE`. Parent top-level
`tags[].league.name` and `.slug` must agree case-insensitively on exactly one
league. Any supplied `marketSides[].team.league` must agree. Nested navigation
subtags, titles, slug prefixes, and `series_or_league` heuristics do not identify
the family. Missing/ambiguous parents or incomplete/conflicting family fields
retain candidates. The policy inputs are separate from semantic field meanings.

Spreads, totals, props, partial games, futures, championships, awards, other
sports and non-sports retain their existing discovery behavior. These exclusions
are internal triage decisions, never registry verification or strategy changes.

Reproduce the fixed-game metadata observation with:

```bash
.venv/bin/python scripts/observe_sports_family_policy.py
```

It makes 16 public GETs for six previously audited game pairs and four spread/
total control events. It bounds selected children and emitted samples, fails if
either league has zero exclusions, and reports statuses. It intentionally has
no active-only restriction; historical closed games can exercise metadata
classification but cannot establish current trading eligibility. Control
retention establishes discoverability only, not threshold/period equivalence.

## What the ranking means

`verification_priority` is deterministic review triage, not an equivalence
probability or approval score. Candidate generation uses normalized lexical
overlap as its unchanged initial signal, now including authoritative parent
event titles when available. The minimum remains exactly `0.20`; participant or
category agreement does not bypass it. Priority then rewards exact matches and
strongly penalizes material mismatches across:

- underlying event/entity and proposition;
- participant/outcome and YES/NO mapping;
- threshold, inclusivity, and measurement unit;
- event window, close conditions, and settlement backstop;
- resolution source;
- cancellation/postponement, multiple-winner, and void/refund/fair-market
  treatment.

Each field is reported as `MATCH`, `MISMATCH`, `UNKNOWN`, or
`NOT_APPLICABLE`. Missing evidence remains `UNKNOWN`; it is never promoted to a
match. Exact `Decimal` values are used for thresholds.

## Hard boundary

Every result states:

> UNVERIFIED — human/primary-source verification required

Discovery results are a separate model, are not registry records, and are not
written to `registry/data/market_pairs.toml`. Only a human-authored registry
record that satisfies the full checklist in `docs/MARKET_PAIRING.md` can become
strategy-eligible. Discovery output must never be passed to arbitrage or
execution code as a substitute for that gate.
