# Local strategy reassessment — 2026-09-12

Agent: Codex
Model: unknown
Reviewer: ChatGPT
Recorded at: 2026-09-12T07:51:49.342626+00:00
Status: research recommendation; local review pending, no architecture change adopted.

PR #57 was unchanged at `c09db2d8f379712cb7186be1f3cda58a15dfdc7e`, with
successful quality CI (run 34681298049) and no recorded review/inline blockers.
Squash merge and synced main: `0aa171b24fb3aa48a3ab85ef7a52b2a4dfdb9255`.

**Recommendation: PIVOT_TO_SAME_VENUE_STRUCTURAL_ARBITRAGE.** This redirects
research toward proving one Kalshi event basket. It does not establish a valid
basket, profitable opportunity, execution readiness or permission to trade.

## Evidence and scope

Repository-first review: [prior reassessment](sports-family-policy-v2-reassessment-2026-09-12T031524Z.json)
showed three active NFL parent-event overlaps, with 90 spread and 90 total
candidate relationships, plus 69 MLB spread relationships across three closed
events. Child-pair counts are not independent opportunities. Three reviewed
winner/MLB-total families are systematically incompatible. The
[NFL spread target audit](nfl-spread-ari-lac-equivalence-2026-09-12T073031Z.json)
then rejected one strong-overlap target with LIKELY_FAMILY_WIDE concern; that is
not a fourth completed family audit. Unexamined sports and non-sports families
remain unclassified.

Current adapters are Kalshi and Polymarket US. [API sources](../../API_SOURCES.md)
explicitly separate US from international Polymarket evidence. No alternative
venue pair with established access, API integration, event overlap and compatible
rules was found in the bounded repository review. Kalshi ↔ international
Polymarket is therefore only a possible research lead, not an evidence-supported
replacement. This note does not manufacture a shortlist of supported venues or
conduct a new venue survey.

Two official documentation pages were refreshed publicly on 2026-09-12:
[Kalshi event API](https://docs.kalshi.com/api-reference/events/get-event) and
[binary-side representation](https://docs.kalshi.com/getting_started/orderbook_responses).
No venue API calls, market prices or books were requested for this reassessment.
Documentation examples were not used as market observations.

## Comparison

Judgments below are engineering/research estimates, not empirical return or
frequency estimates. Opportunity frequency is UNKNOWN for all directions without
eligible-set discovery and later separately authorized executable-data work.
Structural availability and past metadata overlap are distinguished from edge.

| Direction | Contract-equivalence burden | Venue/rule compatibility | Opportunity frequency / structural evidence | Data/API availability | Execution complexity |
|---|---|---|---|---|---|
| Current Kalshi ↔ Polymarket US | High: each proposition and exceptional state must align | Three family rejections; spread target also rejected; others UNKNOWN | UNKNOWN; real NFL overlap demonstrated, not eligible arbitrage | Both metadata adapters exist; Polymarket side interpretation remains A-013 | Two venues, identifiers, funding and recovery paths |
| Other cross-venue combination | High; restart venue and pair proof | UNKNOWN; no replacement established | UNKNOWN; no alternate-pair overlap evidence located | New venue API/access/terms validation and adapter needed | At least two venues plus new operational boundary |
| Same-venue exhaustive basket | Prove complete partition and constant combined payout across every material state | One rule authority removes cross-venue divergence, not target-rule differences | UNKNOWN; event/child schema available, no approved basket yet | Kalshi event metadata and binary child adapter exist | Multiple child legs; coordination still required, no atomicity assumed |
| Related-market consistency | Prove implication or payout inequality, not mere correlation | Same venue helps; thresholds, periods, sources and voids can break relation | UNKNOWN; prior observations contain threshold ladders, not proven inequalities | Existing metadata can seed same-venue research; no relation-proof model | Usually two or more legs; may require shorts/collateral handling |
| Multi-outcome structural | Prove complete state space and payoff matrix including residual/tie states | Same-venue special case may align; multi-market rules still need proof | UNKNOWN; synthetic categorical tests do not establish venue supply | N-way arithmetic exists; live categorical normalization/grouping incomplete | N-leg sizing, execution, partial-fill recovery; greatest coordination burden |

| Direction | Leg risk | Capital requirements | Deterministic testability | Existing architecture fit | Likely engineering effort |
|---|---|---|---|---|---|
| Current Kalshi ↔ Polymarket US | Two independent fills and outages; settlement basis risk until equivalent | Prefund two venues; separate reserves and settlement locks; amount UNKNOWN | Math/replay tests reusable; tests cannot prove rules | Best current two-leg/registry fit; semantic eligibility bottleneck | Low incremental code, high recurring research and operational burden |
| Other cross-venue combination | Same risks plus new venue failure modes | Split funding/collateral and transfer constraints UNKNOWN | Good once adapter and rules are specified | Replaceable adapter boundary helps, no shortcut through registry | High: new integration, semantics, fees and operations |
| Same-venue exhaustive basket | Sequential fills and stranded inventory across children | One venue; sum of leg acquisition costs plus fees/reserves; no netting credit assumed | Strong finite-state and missing-child tests; live inputs still require provenance | Reuse Decimal/domain concepts; event group cannot use same-market evaluator unchanged | Medium research-first; group model and lifecycle work if proof passes |
| Related-market consistency | Hedge relation may fail in exceptional states; execution still non-atomic | Fully funded legs or separately established short collateral; no assumed offsets | Strong for proven finite inequalities; weak if based on statistical association | Requires relation proof and new eligibility/evaluation path | Medium–high; semantic model and payoff constraints |
| Multi-outcome structural | More legs increase partial completion and recovery states | All-leg inventory/fees; size determined by weakest leg; holding period UNKNOWN | Strong state enumeration and N-leg invariants | N-way result exists; categorical result cannot become current two-leg Opportunity | High for general solution; narrower basket subset should precede it |

The last two structural directions overlap: exhaustive baskets are the narrow
constant-payout subset of general multi-outcome structures. They are compared
separately to avoid treating existing arithmetic as a ready general strategy.

## Architectural constraints and decision rationale

[D-025 / A-039](../../DECISIONS.md) and
[methodology](../../ARBITRAGE_METHODOLOGY.md) describe complete-set arithmetic.
[The engine](../../../src/prediction_market_arbitrage/arbitrage/engine.py)
checks one venue, one market and distinct contracts; it trusts the caller's
exhaustiveness premise. [Existing tests](../../../tests/test_arbitrage_complete_set.py)
cover synthetic binary/categorical arithmetic, depth, fees and freshness. They
were inspected, not rerun, and do not verify any real event basket.

[Kalshi normalization](../../../src/prediction_market_arbitrage/adapters/kalshi/normalize.py)
assigns each child ticker its own Market ID. Sibling YES contracts under one
parent event are therefore **not** already an admissible same-market complete
set. Never rewrite their IDs to evade this check. Polymarket US normalization
currently requires exactly one long and one short side (D-009), with A-013 still
unresolved. The existing paper orchestration is a verified two-leg lifecycle;
an N-leg basket would need separate design review, not silent reuse.

The public event schema exposes `mutually_exclusive`, child markets and rule
fields. Mutual exclusivity alone does not establish exhaustiveness or a fixed
combined settlement value. Missing/unlisted outcomes, provisional children,
residual ranges, tied winners, voids, fair-value settlement, source corrections
and differing expiration times need explicit proof. Reconsider A-039's applicability
to event-level groups; do not promote its same-market design assumption to evidence.

Kalshi documents reciprocal YES/NO sides. Algebraically, on a coherent uncrossed
binary book, buying both sides has no gross discount to the unit payoff; stale
or crossed snapshots must not be counted as independent structural opportunities.
Thus the research target is a genuine event partition across distinct children,
not another scan for an ordinary binary pair. No prices were used in this inference.

Same-venue basket research wins on removing a demonstrated failure source while
reusing known venue metadata and deterministic math. Its commercial viability is
UNKNOWN. Current cross-venue work is preserved, not deleted; no discovery policy
or eligibility gate changes. Alternative venues lack sufficient project evidence;
related-market and general multi-outcome work add more semantic and execution
complexity before proving the simpler partition case. This is a research-priority
choice, not a conclusion that arbitrage has no edge or that a pivot will earn one.

## Exactly one next milestone

**Bounded Kalshi event-basket validity and representation audit (research only).**
Inspect up to three active non-sports parent events with apparent mutually
exclusive child outcomes using public metadata/rules only; select at most one
complete event partition for detailed payoff-state proof. Confirm all children,
exhaustiveness, common source/horizon and exceptional-state combined payout.
Record why the actual child IDs do or do not fit existing models. Return either
one evidence-backed proposed group contract for architecture review or an explicit
no-valid-basket finding. If no qualifying event exists within the bound, stop;
do not broaden to another strategy. No books, prices, registry entries, engine
invocation, new strategy code or execution. No implementation is authorized by
this recommendation. Stay local for ChatGPT review.

## Validation and safety

Five options assessed on all ten requested dimensions. Relative evidence/code
links and prior JSON classifications/counts checked; `git diff --check` passed.
Docs-only: no production suite repeated. No policy/registry/code changes, venue
authentication, account data, books, prices used, orders, strategy evaluation,
execution, real money, risk-control/Demo-cap/LIVE_TRADING changes. Five unrelated
Demo changes preserved. No post-reassessment push, new PR or local commit.
