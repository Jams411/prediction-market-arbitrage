# Minimal relative-value research pivot — 2026-09-12

Agent: Codex
Model: GPT-6
Reviewer: pending
Status: PROPOSED; architecture recommendation only, no implementation authorization.

Recommendation: add one read-only research result type and one pure CPI quote-
ordering detector alongside the strict engine. Preserve all existing semantics,
registries and execution paths. No plugin framework, new dependency, database
migration, generic strategy runner, fair-value model or automatic market discovery.

## 1. Current → proposed pipeline

Current capabilities, not a claim of one deployed integrated service:

    venue adapters / livebook / recorded-book replay → normalized OrderBook
    strict pair discovery → human VERIFIED registry → ArbitrageEngine
    OpportunityEvaluation → recorder / dashboard / risk
    PaperArbitrageOrchestrator → risk-gated offline paper lifecycle

The same-market complete-set evaluator is a separate path; its result is deliberately
not accepted by the paired opportunity recorder/risk/dashboard interfaces.

Proposed additional path:

    explicit research relationship + normalized book snapshots
      → pure research detector → ResearchSignal + diagnostics
      → local ranked JSON/Markdown research report

No connection from ResearchSignal to any broker, order builder, risk authorization
or registry writer. Later, a presentation-only adapter may label eligible existing
strict results STRICT_ARBITRAGE. The original evaluation remains authoritative.

## 2. Reuse and actual gaps

| Existing component | Recommendation |
|---|---|
| `domain/models.py`: Venue, Market, Contract, PriceLevel, OrderBook; Decimal/aware-time validation | Reuse unchanged. CPI children are distinct Markets; do not collapse their identities. |
| `adapters/kalshi/normalize.py`, public client, livebook state/health | Reuse their normalization/health behavior. No transport in first milestone. |
| `recorder/recorder.py:record_order_book`, `replay/session.py:order_books` | Reuse book storage/read APIs later. Replay lacks original sequence/market state; never infer synchronized live eligibility from replay. |
| `registry/*`, strict `arbitrage/engine.py`, risk, paper/live brokers and orchestrator | Preserve unchanged, outside research path. |
| `pair_discovery/models.py:SemanticContract` and profiles | Reuse provenance concepts/available profiles; add only a typed local threshold relationship input. `CandidatePair` is explicitly cross-venue, not reusable as a same-venue relationship. |
| `arbitrage/fees.py:FeeModel` | Retain interface for future estimates; current Kalshi implementation uses cent rounding and taker-only semantics. Prior offset audit records account/rounding differences. Do not claim exact research net edge from it unchanged. |
| `arbitrage/engine.py:_walk_asks` | Private and ask-only. First detector needs only top levels; do not extract/refactor it yet. |
| Opportunity recorder, perf report, dashboard | Strictly shaped today. Later add a separate research export/view; do not insert findings into opportunity/PnL tables. |

Nothing is genuinely obsolete based on this audit. The premise that every discovery
result must be execution-eligible is unsuitable for the new research branch, not a
reason to remove strict safeguards or historical evidence.

## 3. Small data-model/API addition

Proposed `research/models.py`, frozen dataclasses with existing validation helpers:

- `SignalType`: STRICT_ARBITRAGE, RELATIVE_VALUE, LOGICAL_INCONSISTENCY,
  FAIR_VALUE_DEVIATION. This is a classification vocabulary, not four new engines.
- `ThresholdRelationship`: id/version, two exact YES Contract identities,
  parent event id, ordered Decimal thresholds, shared underlying/window/source
  description, rule/evidence references, ordinary-proof status and exceptional
  settlement caveats. It is a research input, not a MarketPairRecord or approval.
- `ResearchSignal`: detector id/version, kind, relationship id/version, contracts,
  evaluation time and both book times, named Decimal metric/unit, observed inputs
  (prices/quantities), evidence references/statuses, and explicit limitations.
  Confidence is a small categorical assessment with reasons, not a probability.
  All instances are advisory by type; no mutable `execution_eligible` switch.
- `ResearchEvaluation`: optional signal plus stable diagnostic reasons for missing,
  stale, mismatched or nonviolating inputs. An absent signal is distinguishable from
  unavailable data. No mandatory positive `edge` or guaranteed quantity.

Proposed pure API:

    evaluate_threshold_ordering(relationship, lower_yes_book, higher_yes_book,
                                *, evaluation_time, max_age, max_skew)
        -> ResearchEvaluation

Use explicit arguments and one function; no detector protocol/registry needed yet.
Decimal strings and timezone-aware ISO timestamps in the eventual versioned export.
STRICT_ARBITRAGE labels may only wrap an existing appropriately gated evaluation;
research evidence cannot promote itself to that kind. RELATIVE_VALUE denotes a
conditional comparison; LOGICAL_INCONSISTENCY flags contradiction to a stated
relation; FAIR_VALUE_DEVIATION will require an explicit estimate, uncertainty and
model provenance before a later detector exists. No model is implied by the enum.

## 4. First detector: CPI ordinary threshold quote-ordering discrepancy

Use `KXCPI-26SEP-T0.2` and `KXCPI-26SEP-T0.3`, from the
[CPI audit](kalshi-cpi-dominance-audit-local-2026-09-12.md). For shared scalar X,
X>0.3 implies X>0.2. Exceptional settlement ordering is INCONCLUSIVE.
The local relationship must carry the unresolved expiration/rule-precedence caveat.
No real quote data for this pair is asserted to exist locally.

Given lower-threshold YES ask A_low and higher-threshold YES bid B_high:

    gap = B_high - A_low
    top_level_quantity = min(lower ask quantity, higher bid quantity)

Emit LOGICAL_INCONSISTENCY only when gap>0, explicitly scoped to the ordinary-state
relation. These quote intervals cannot accommodate ordered values without moving
at least one boundary. This is a review priority, not proof of market irrationality,
mispricing or riskless return. Fees and exceptional differences may explain it.
Do not infer arbitrage from bid-to-bid or midpoint comparisons. No fair probability
estimate, recommendation to trade, or guaranteed profit field.

Require exact bound identities/sides, same venue and documented relationship,
finite values, valid uncrossed per-contract books, needed levels, aware nonfuture
timestamps, age <= supplied max_age and inter-book skew <= supplied max_skew.
Stale/missing/mismatched inputs produce diagnostics, not ranked signals. Offline
synthetic inputs retain TESTED provenance. Historical replay stays historical.

Rank eligible findings by descending gap, then descending top-level quantity,
then freshest oldest-leg timestamp, then relationship id for stable ties. With
one pair this ranks repeated observations, not an invented candidate universe.
Do not multiply gap by quantity and call it expected profit. No signal implies
only no detected discrepancy under this narrow test, not fair pricing.

## 5. Risk, confidence and strict safeguards

- Settlement risk belongs to relationship evidence and every emitted finding:
  ordinary implication supported; exceptional ordering unresolved. Confidence in
  the observed quote discrepancy is separate from confidence in realizable value.
  First detector reports settlement confidence UNKNOWN; no numerical probability.
- Fees enter after the raw diagnostic as optional cost context, never as zero by
  default. First milestone reports NOT_EVALUATED. Exact maker/taker, account grid,
  rebates and fill accounting need a later fee reconciliation task.
- Liquidity is displayed top-level size only. Age/skew are data eligibility checks;
  non-atomicity, partial fills and trade busts remain execution caveats. Displayed
  size is not a promise of fills. No production RiskManager changes.
- Cross-venue strict evaluation retains VERIFIED checks in both engine entry paths.
  Same-market complete-set caller assumptions and separate result type remain as-is;
  the new label must not silently upgrade them. No research relationship is fed
  into `evaluate`, `evaluate_complete_set` or `to_opportunity`.
- Research may consume conditional evidence without VERIFIED equivalence because
  it cannot authorize trading. It still rejects bad identities/data and exposes
  uncertainty. Existing strict discovery family exclusions are unchanged; this
  explicit CPI input does not revise or disable those policies.

## 6. Phases and next GitHub checkpoint

1. **One focused coding task, later authorization:** add only `research/models.py`,
   `research/thresholds.py`, minimal package exports and focused tests. Synthetic
   identifiers only; inject relationship/book fixtures. Test positive/zero/negative
   gap, wrong side/id, equality semantics, missing depth, stale/future/skew limits,
   deterministic ranking, provenance/caveat preservation and separation from strict
   opportunity types. No CLI, I/O, fee engine, registry edit or database migration.
2. Local artifact layer: serialize injected/replayed inputs and diagnostics to a
   reproducible report; then define the explicit real CPI relationship from the
   retained evidence as a research-only specification. Revalidate temporal validity
   before any later live use; do not silently replace an expired target.
3. Separately authorized read-only observation: existing public adapters, exactly
   named targets, freshness/status checks, no scanner expansion or authentication.
   Reconcile fees before adding net-cost estimates. Persistence/model-based fair
   value and paper simulation are separate decisions, not required to start.

Next GitHub checkpoint should eventually be the first offline detector plus its
tests, this proposed decision and scoped attribution. Demonstrate strict behavior
unchanged; run focused tests during development and the repository's full local
gate once before commit (ruff, mypy, pytest, pre-commit). Scope staged paths
explicitly; existing Demo/evidence work is not implicitly included. Future push/PR
requires authorization; CI/review remains a separate gate. None created now.

Architecture verified against named current source files; local links and
`git diff --check` checked. No implementation, production tests, new scans,
authentication, books/prices, orders, execution, registry, risk, Demo-cap or
LIVE_TRADING changes. Recommendation ends here.
