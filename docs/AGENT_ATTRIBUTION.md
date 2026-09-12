# Agent Attribution and Quality Ledger

This file records which AI coding agent performed implementation work so agent quality can be compared over time without changing the project's engineering standards.

## Purpose

Agent attribution is metadata, not evidence of correctness. Code from every agent must satisfy the same repository rules, deterministic tests, local quality gate, PR review, and GitHub CI before merge.

## Attribution fields

For each completed milestone, record:

- **Implementer:** `Claude Code`, `Codex`, `Other`, or `Human`.
- **Model:** exact model when known; otherwise `unknown`.
- **Reviewer:** who independently reviewed the result, when applicable.
- **Scope:** concise description of the work performed.
- **Validation:** tests/quality gates/CI used.
- **Outcome:** merged, rejected, superseded, blocked, or observation-only.
- **Rework:** material defects or follow-up corrections attributable to the implementation, if any.
- **Evidence:** PR/commit/decision/journal references supporting the attribution and outcome.

Do not infer an agent from Git author metadata. If historical attribution cannot be established from session/project records, write `unknown` rather than guessing.

## Prospective convention

Every coding-agent milestone should add an `Agent:` field to its `docs/PROJECT_JOURNAL.md` entry and PR description. Commit messages may also use an `Agent:` trailer, but the journal and this ledger are the durable project records.

Recommended journal metadata:

```text
Agent: Codex
Model: <model if known>
Reviewer: ChatGPT
Validation: ruff, mypy, pytest, pre-commit, GitHub CI
```

## Quality comparison

Do not compare agents by raw lines of code or number of commits. Compare them on the same dimensions:

1. first-pass acceptance after review;
2. deterministic test/CI pass rate;
3. number and severity of implementation defects found during review or later use;
4. rework required before merge;
5. scope discipline / unnecessary changes;
6. safety-boundary violations or near misses;
7. unsupported claims or evidence-status mistakes;
8. task completion time and paid-model usage when available.

A milestone blocked by venue behavior or missing external evidence is not an agent-quality failure unless the agent caused or misdiagnosed the blocker.

## Historical baseline — Claude Code

The project's implementation workflow through 2026-09-10 used Claude Code as the primary repository coding agent for the milestones documented below. ChatGPT supplied/reviewed bounded milestone instructions and independently reviewed the reported results before GitHub PR/CI/merge steps. This attribution is based on the project/session workflow record; it is not inferred from Git commit authorship.

### Early project build — 2026-09-05 onward

**Implementer:** Claude Code  
**Model:** historical model not consistently recorded  
**Scope:** initial repository implementation milestones, including venue-neutral domain models, Kalshi REST market-data work, subsequent market-data/live-book development, tests, documentation, evidence handling, and safety-gate work recorded in `PROJECT_JOURNAL.md`.  
**Validation:** repository quality gates and GitHub CI as recorded per milestone.  
**Outcome:** established the implementation baseline used by later live-book and execution-safety work.  
**Evidence:** `docs/PROJECT_JOURNAL.md` and merged repository history.  
**Caveat:** individual early commits are not retroactively assigned to Claude here unless a stronger historical record is available. This entry records the known project-level workflow, not unverifiable commit-level attribution.

### Kalshi stale/reconnect runtime evidence — PR #34

**Implementer:** Claude Code  
**Scope:** bounded production read-only stale/reconnect observation harness, sanitized evidence, deterministic tests, and supported documentation.  
**Outcome:** merged; gate #7 remained unchecked because natural staleness was not observed; gate #8 remained unchecked because the disconnect was controlled and live backoff/retry remained unobserved.  
**Quality note:** conservative evidence classification was preserved rather than manufacturing gate completion.

### Real-money safety-gate hardening — PR #35

**Implementer:** Claude Code  
**Scope:** deterministic evidence for duplicate-order prevention, kill switch, position limits, daily-loss limits, credential isolation, and accidental-live-mode prevention.  
**Outcome:** merged; gates remained unchecked where end-to-end execution evidence was absent.  
**Quality note:** strengthened regression coverage without changing production runtime code merely to satisfy gate wording.

### Paper execution pipeline evidence — PR #36

**Implementer:** Claude Code  
**Scope:** deterministic paper execution pipeline integration evidence and journal updates for gates #3, #4, #5, #6, and #10.  
**Outcome:** merged; real-money gates remained unchecked where venue/end-to-end evidence was still missing.

### Kalshi Demo execution orchestrator — PR #37

**Implementer:** Claude Code  
**Model:** Sonnet 5 observed during this phase  
**Scope:** DEMO-only execution orchestration boundary, production-host rejection, risk/duplicate/reconciliation fail-closed behavior, deterministic tests, and documentation.  
**Outcome:** merged. Production execution remained disabled and no concrete networked Demo transport was included in this milestone.

### Kalshi Demo REST transport and bounded observation harness — PR #38

**Implementer:** Claude Code  
**Model:** Sonnet 5 observed during this phase  
**Scope:** concrete Demo REST transport, env-guarded one-order observation harness, pre-submit Demo position check, read-only candidate diagnostic, tests, and documentation.  
**Validation:** local quality gate reported green with 759 tests; GitHub CI passed before merge.  
**Outcome:** merged. Read-only diagnostic observed 0 two-sided YES books among the first 100 open Demo markets, so no Demo order was placed.  
**Quality note:** the harness failed closed rather than weakening the price/risk limits to manufacture an execution.

## Codex comparison period

The Codex comparison period begins after PR #38 / 2026-09-10. New Codex milestones should be appended here using the same fields and engineering gates as Claude Code. Do not lower or raise acceptance standards based on the agent used.

### Paginated Kalshi Demo candidate observation — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** reused the existing read-only Demo diagnostic to verify cursor
pagination and inspect 10 pages / 1,000 open markets at the unchanged
`--max-price 0.60`; recorded a compact evidence summary.
**Validation:** targeted diagnostic tests; live public Demo market-data
observation; no authenticated or execution endpoints.
**Outcome:** three markets passed the existing picker rule; recommended target
`KXMLBHR-26SEP101305HOUPHI-PHILARRAEZ1-1` had YES best bid `0.0600`, best ask
`0.0800`, and `27083.29` available at the best ask in the initial observed
snapshot. A fresh targeted read-only revalidation observed the target still
`active` and eligible at the same bid/ask, with 4 bid / 3 ask levels and
`64583.23` then available at the best ask. The subsequent authorized bounded
execution attempt failed closed before submission: the target remained eligible,
but the supported observer has no ticker argument and its non-paginated picker
could not select it from the first 100 open markets. No account call occurred.
**Evidence:** `docs/PROJECT_JOURNAL.md` and
`docs/evidence/kalshi-demo/execution/candidate-scan-2026-09-10.json` plus
`docs/evidence/kalshi-demo/execution/candidate-revalidation-2026-09-10.json` plus
`docs/evidence/kalshi-demo/execution/bounded-execution-blocked-2026-09-10.json`.
**Quality note:** no code or risk-limit change was needed; no order was placed.

### Explicit target selection for bounded Kalshi Demo execution — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** required an explicit operator-supplied ticker for `--observe`, added
exact Demo retrieval and fail-closed status/identity/eligibility validation, and
kept the existing execution safeguards and discovery diagnostic unchanged.
**Validation:** focused 39-test observer suite plus the complete local Ruff,
mypy, pytest, and pre-commit quality gate.
**Outcome:** the bounded harness can evaluate the exact authorized market without
depending on discovery ordering; missing, ambiguous, unavailable, inactive, or
ineligible targets stop before credentials or submission. No order was run.
**Evidence:** D-033; `docs/PROJECT_JOURNAL.md`;
`scripts/observe_kalshi_demo_execution.py`;
`tests/test_observe_kalshi_demo_execution.py`.
**Quality note:** narrow script/test/docs change only; no execution architecture,
risk limits, production gates, dependencies, or historical attribution changed.

### First explicit-target bounded Kalshi Demo attempt — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** verified and squash-merged reviewed PR #40, then ran exactly one
explicit-target, 1-contract, `--max-price 0.60` attempt through the merged Demo
orchestrator and preserved its sanitized evidence.
**Validation:** merged-head/CI/review verification; Demo preflight and exact
target validation; focused observer tests and evidence-format checks.
**Outcome:** pre-submit position was 0 and risk was allowed, but the single create
request was venue-rejected with no order ID, accepted quantity, fill,
cancellation, or retry. No real-money gate advanced.
**Evidence:** `docs/PROJECT_JOURNAL.md` and
`docs/evidence/kalshi-demo/execution/SUMMARY.json`.
**Quality note:** outcome is classified as an OBSERVED Demo rejection, not a
successful execution; no production or real-money action occurred.

### Kalshi Demo create-rejection diagnosis and safe observability — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** compared the failed Demo create path with current official request,
signing, error, sharding, API-key scope, and location-attestation documentation;
added a narrow rejection-metadata allowlist for future bounded observations.
**Validation:** targeted offline broker, REST transport, and observation-harness
tests plus the complete local quality gate.
**Outcome:** no request/API mismatch or exact past rejection cause was proven.
Future failures can preserve HTTP status, a stable internal category, and a safe
venue error code without arbitrary venue text or secrets. No execution was run.
**Evidence:** D-034; K-TR-22/23; `docs/PROJECT_JOURNAL.md`;
`src/prediction_market_arbitrage/demo_execution/broker.py`;
`scripts/observe_kalshi_demo_execution.py`.
**Quality note:** no order/cancel/authenticated request, production action,
safety-limit change, credential change, or historical attribution rewrite.

### PR #41 merge and finalized-target fail-closed observation — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** verified and squash-merged reviewed PR #41, then performed one exact
target public Kalshi Demo market/book check under the unchanged eligibility
rules.
**Validation:** PR head/CI/review state, merge commit, clean synced main, and
JSON evidence-format validation.
**Outcome:** the authorized target was finalized on exchange index 3 with an
empty YES book and was ineligible. The bounded execution command was not run;
there was no authenticated venue call, position/duplicate/risk check, create,
cancel, fill, or replacement selection.
**Evidence:** `docs/PROJECT_JOURNAL.md` and
`docs/evidence/kalshi-demo/execution/target-finalized-2026-09-10.json`.
**Quality note:** fail-closed read-only evidence only; no production or
real-money action and no historical attribution change.

### Paginated Kalshi Demo replacement-candidate observation — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** preserved the existing finalized-target evidence and ran the shipped
public, credential-free 10-page Demo diagnostic at the unchanged `0.60` cap and
two-level-per-side rule.
**Validation:** command exited successfully; 1,000 diagnostic rows were parsed
locally; evidence JSON and documentation diffs validated.
**Outcome:** 123 non-empty YES books, 27 two-sided books, and one eligible
candidate: `KXUCLSPREAD-26SEP10BMUBOG-BMU5` at `0.0500` / `0.0700`, depth 4/3,
size `11896.81` at ask. A pre-existing advisory-count wording discrepancy was
recorded without changing code.
**Evidence:** `docs/PROJECT_JOURNAL.md` and
`docs/evidence/kalshi-demo/execution/candidate-scan-2026-09-10T2051Z.json`.
**Quality note:** OBSERVED public data only; no credentials, authentication,
execution, production action, risk-limit change, or historical attribution
rewrite.

### Kalshi Demo diagnostic advisory-count correction — 2026-09-10

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** corrected `recommend_max_price` wording/count semantics without
changing candidate assessment, execution selection, depth rules, or the active
price cap.
**Validation:** focused observer tests plus the complete local Ruff, mypy,
pytest, and pre-commit gate.
**Outcome:** only under-cap candidates are now called picker-eligible; additional
two-sided/depth-qualified candidates are explicitly labeled above-cap and
ineligible under the current rule. Historical scan evidence remains unchanged.
**Evidence:** `scripts/observe_kalshi_demo_execution.py`,
`tests/test_observe_kalshi_demo_execution.py`, and `docs/PROJECT_JOURNAL.md`.
**Quality note:** straightforward diagnostic correction; no architectural
decision entry, venue request, safety-control change, or historical attribution
rewrite.

### Deterministic synthetic paper-arbitrage lifecycle — 2026-09-10

**Implementer:** Codex
**Model:** unknown
**Reviewer:** ChatGPT
**Scope:** added the narrow offline glue and additive recorder linkage required
to exercise registry → two-book evaluation → risk → two-leg paper fills →
positions/P&L → replay using clearly synthetic identifiers.
**Validation:** focused lifecycle/recorder/replay tests plus the complete local
quality gate. Exact expected economics, fills, positions, risk-before-submit,
depth bound, persistent associations, and replay reconciliation are asserted.
**Outcome:** deterministic synthetic end-to-end lifecycle is TESTED; real pair,
real-market, Demo/live execution, and production-readiness evidence remain open.
**Evidence:** D-035; `tests/test_offline_paper_arbitrage_lifecycle.py`.
**Quality note:** no live/authenticated/order/production action and no historical
Claude attribution rewrite.

### Read-only contract-equivalence discovery triage — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** added a small deterministic semantic-profile/comparison module and a
bounded public-metadata CLI that ranks plausible Kalshi / Polymarket US pairs
for human review without writing to the canonical registry.
**Validation:** focused discovery and registry tests plus the complete local
Ruff, mypy, pytest, and pre-commit gate. A single bounded public observation
inspected 100 markets per venue and returned zero candidates above the
conservative generation threshold.
**Outcome:** candidate triage is TESTED; the live observation is OBSERVED only.
Every result remains explicitly UNVERIFIED, missing fields remain UNKNOWN, and
only the existing human-authored VERIFIED registry boundary can admit a pair to
strategy code.
**Quality note:** no credentials, account or order-book calls, authentication,
registry approval, strategy execution, order/cancel, production execution,
real-money action, safety-limit change, or historical attribution rewrite.

### Broader bounded contract-discovery observation — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** squash-merged reviewed PR #44, then ran its unchanged public metadata
CLI at the supported maximum of 10 pages × 100 records per venue with `--top 20`.
**Validation:** 1,000 Kalshi and 1,000 Polymarket US records inspected; 16
UNVERIFIED rows surfaced, all priority 2 and all with zero semantic MATCH fields.
The sanitized evidence summary was validated as JSON.
**Outcome:** the surfaced rows were shared-team-token false positives involving
Kalshi cross-category combo markets. UNKNOWN fields were dominant, while the
output format could not reveal same-event pairs below the lexical gate. This is
OBSERVED triage evidence, not equivalence, arbitrage, or readiness evidence.
**Quality note:** no code/config change, credential, authentication, book/account
call, strategy execution, registry approval/write, order/cancel, production
execution, real-money action, or historical attribution rewrite.

### Candidate-generation rejection diagnostics — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** added bounded streaming diagnostics around the unchanged lexical
candidate gate: reconciled considered/passed/rejected counts plus top-N rejected
examples with exact token keys, coarse signals, missing fields, and reasons.
**Validation:** focused discovery/registry tests cover below-threshold same-event
signals, unrelated/generic collisions, deterministic ordering and bounds,
missing metadata, count reconciliation, UNVERIFIED status, and registry
isolation. One maximum-bounds public observation reconciled 1,000,000 rows.
**Outcome:** diagnostics are TESTED; the observation is OBSERVED. It found 34
passes and 999,966 rejections, with no coarse match among the highest-priority
near misses. The current bottleneck is mixed universe coverage and normalization,
not shown to be the unchanged threshold.
**Quality note:** no approval semantics, registry/ranking/threshold change,
credential, authentication, book/account call, strategy execution, order/cancel,
production execution, real-money action, or historical attribution rewrite.

### Contract-discovery metadata provenance audit — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** merged reviewed PR #46, then audited the public Kalshi and Polymarket
US metadata provenance available to contract discovery without changing code.
**Validation:** compared current repository ingestion/profile logic with official
Kalshi API references, the official Polymarket US SDK, and bounded unauthenticated
market/event/series detail responses.
**Outcome:** confirmed richer structured metadata is dropped at the current
market-list-only boundary, and confirmed Kalshi MVE plus observed Polymarket US
combo flags are unused. The bottleneck is MIXED ingestion/normalization/combo
noise; universe overlap remains unresolved.
**Evidence:**
`docs/evidence/contract-discovery/metadata-provenance-audit-2026-09-11.md`.
**Quality note:** audit/evidence only; no matching, registry, strategy, risk, or
execution change and no authenticated/order/production/real-money action.

### Authoritative parent-event discovery enrichment — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** added bounded parent-event metadata ingestion, deterministic in-run
indexes/reuse accounting, richer semantic provenance, structured Kalshi MVE
exclusion, and conservative Polymarket US combo handling.
**Validation:** focused client/discovery/registry tests plus the complete local
quality gate. The final maximum-bounds public observation inspected 1,000
markets per venue and reconciled 1,000,000 comparisons.
**Outcome:** authoritative enrichment is TESTED and the public result OBSERVED.
Threshold passes fell from 34 to 26 after Kalshi MVE exclusion; no retained row
matched on authoritative event or date, so all candidates remain UNVERIFIED.
**Evidence:** D-036; metadata provenance audit; enriched observation artifact.
**Quality note:** no threshold bypass, registry approval/write, credential,
authentication, book/account call, strategy/paper execution, order/cancel,
production execution, real-money action, or historical attribution rewrite.

### Venue-universe overlap audit — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** squash-merged reviewed PR #47, then aggregated one bounded public
metadata snapshot by authoritative category, league, event identity/date, and
participant/entity without changing matcher or verification logic.
**Validation:** reconciled 1,000 market rows per venue to 100 Kalshi and 77 used
Polymarket US parent events; derived category distributions, shared-league date
sets, politics/race coverage, and conservative event-overlap keys.
**Outcome:** zero strong and zero possible event overlaps were found in the
observed slice. Final classification is COVERAGE_INSUFFICIENT because the two
bounded samples have materially different category, ordering, time-horizon, and
child-market weighting biases.
**Evidence:**
`docs/evidence/contract-discovery/venue-universe-overlap-audit-2026-09-11.json`.
**Quality note:** OBSERVED public metadata plus deterministic DERIVED analysis;
no equivalence verification, credential, authentication, order book, registry
write, strategy execution, order/cancel, production execution, real-money
action, or historical attribution rewrite.

### Stratified venue-universe overlap audit — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** squash-merged reviewed PR #48, then replaced generic first-page
sampling with bounded public metadata strata for MLB, NFL, 2026 elections, and
six company/IPO subjects without changing discovery or verification code.
**Validation:** reconciled parent-event and child-market counts, exact scheduled
dates and structured team identities, 73 strong sports event relationships,
and 68 possible politics/company relationships; JSON parsing, count assertions,
and documentation diff checks passed.
**Outcome:** coverage is adequate for the priority strata and observed current
MLB/NFL game overlap is healthy. All relationships remain UNVERIFIED; one
representative sports event should receive primary-source contract-equivalence
review next.
**Evidence:**
`docs/evidence/contract-discovery/stratified-venue-universe-overlap-audit-2026-09-11T180951Z.json`.
**Quality note:** public metadata and deterministic derived analysis only; no
credential, authentication, order book, account call, registry write,
strategy/paper/live execution, order/cancel, production execution, real-money
action, or historical attribution rewrite.

### Arizona–Chargers contract-equivalence verification — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** squash-merged reviewed PR #49, then compared the target-specific
public Kalshi and Polymarket US child-contract metadata and official sports-rule
guidance without fetching books or entering the verified registry.
**Validation:** reconciled exact event, child-market, and outcome-side IDs;
classified every requested settlement dimension as `MATCH`, `MISMATCH`,
`UNKNOWN`, or `NOT_APPLICABLE`; parsed the evidence JSON and checked its
classification and identifier invariants.
**Outcome:** `REJECTED` because postponement/rescheduling triggers, expiration
windows, and resulting exceptional-state fair-market treatment differ
materially. Direct normal-outcome mappings were established, but several other
material edge cases remain `UNKNOWN`; none were promoted to `MATCH`.
**Evidence:**
`docs/evidence/contract-discovery/contract-equivalence-kxnflgame-arilac-2026-09-11T214556Z.json`.
**Quality note:** OBSERVED public metadata plus DERIVED comparison only; no
credential, authentication, order book, account call, registry write,
strategy/paper/live execution, order/cancel, production execution, real-money
action, or historical attribution rewrite.

### NFL/MLB game-winner family equivalence audit — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** squash-merged reviewed PR #50, then audited the Kalshi professional
football/baseball game-winner and Polymarket US NFL/MLB moneyline families from
official rules and three matching public contracts per league.
**Validation:** parsed the evidence JSON; reconciled two 16-field matrices, six
event relationships, 12 Kalshi child tickers, six Polymarket moneyline IDs, and
family/sample classifications; documentation diff checks passed.
**Outcome:** both families are `SYSTEMATICALLY_INCOMPATIBLE` under strict
all-material-states complementarity. The 48-hour Kalshi continuation window,
Polymarket expiration/two-week behavior, different fallback hierarchies, and
different fair-market triggers can produce divergent exceptional-state payouts.
**Evidence:**
`docs/evidence/contract-discovery/sports-contract-family-equivalence-audit-2026-09-11T220824Z.json`.
**Quality note:** OBSERVED public rules/metadata plus DERIVED family comparison;
no credential, authentication, order book, account call, registry write,
strategy/paper/live execution, order/cancel, production execution, real-money
action, or historical attribution rewrite.

### Polymarket US combo-classification correction — 2026-09-11

**Implementer:** Codex
**Model:** GPT-5
**Reviewer:** ChatGPT
**Scope:** corrected discovery's upstream interpretation of Polymarket US
`comboEnabled` without changing candidate thresholds, semantic ranking,
registry, strategy, or execution behavior.
**Validation:** deterministic tests cover ordinary NFL/MLB moneylines and a
spread, confirmed structured combos, ambiguous/missing metadata, parent
enrichment, Kalshi MVE behavior, and registry isolation; full local quality
gate passed.
**Outcome:** ordinary base contracts remain discoverable even when combo-capable;
only valid `caoc-...` 2--10-leg instruments are filtered, while ambiguity is
retained as `UNKNOWN`.
**Evidence:** D-037 and
`docs/evidence/contract-discovery/polymarket-us-combo-classification-2026-09-11T231501Z.json`.
**Quality note:** public metadata observation plus deterministic tests only; no
credential, authentication, order book, account call, registry write,
strategy/paper/live execution, order/cancel, production execution, real-money
action, or historical attribution rewrite.
