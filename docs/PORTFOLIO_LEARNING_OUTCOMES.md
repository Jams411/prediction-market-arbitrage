# Prediction-Market Research: Portfolio and Interview Notes

## Problem

The project investigated whether prediction-market contracts support deterministic
arbitrage or useful same-venue relative-value signals. A title or price is not
enough to establish equivalence: settlement source, measurement window, units,
threshold wording, revisions, fallbacks, void rules, fees, and execution depth
can change the payoff. Apparent arbitrage therefore requires contract and
settlement verification before arithmetic.

## What was built

- Venue adapters normalize public Kalshi and Polymarket market metadata and
  order books into venue-neutral Decimal domain models.
- Contract discovery and matching compare event, source, timing, units,
  thresholds, and settlement terms. The strict engine consumes only manually
  verified pairs; rejected or ambiguous equivalence stays out of that path.
- Settlement/equivalence audits cover ordinary rules and documented exceptional
  states. The research record keeps unresolved assumptions explicit.
- A research model supports `STRICT_ARBITRAGE`, `RELATIVE_VALUE`,
  `LOGICAL_INCONSISTENCY`, and `FAIR_VALUE_DEVIATION`. The CPI detector derives
  adjacent nested-threshold relationships from authoritative metadata and flags
  a higher-threshold YES bid above a lower-threshold YES ask.
- Compact snapshots preserve normalized contracts, quotes, timestamps,
  provenance, freshness, and settlement-confidence limits. Replay reuses the
  adapter and detector deterministically; persistence analysis separates
  transient from repeated observations.
- Offline scoring applies configurable, explicitly MODELED/ASSUMED fees,
  minimum usable size/depth, slippage buffer, and net research edge. It ranks
  advisory observations and rejects those that do not clear the constraints.
- Fail-closed registry, feed-health, leg-risk, paper-broker, and risk-manager
  boundaries remain separate from research. No live order path was enabled.
- Synthetic and recorded fixtures exercise adapters, detectors, scoring,
  replay, persistence, safety gates, and the repository quality gate (pytest,
  Ruff, mypy, pre-commit, and CI).

## Research method

The workflow moved from a payoff hypothesis to primary-rule and metadata
verification, then to bounded public observations. Quotes were checked for
freshness and skew, filtered for displayed depth, and evaluated with modeled
costs before persistence was considered. The stopping decision used the
observed evidence rather than a target opportunity count.

## Final empirical result

The final CPI study ran **10 observations** over 10 adjacent relationships,
for **100 relationship-observations**. It found **0 raw inconsistencies** and
**0 signals surviving modeled costs**. The classification was
**WEAK_EDGE_REASSESS**. This is useful evidence: the tested relationship did
not produce an economically supported signal under the stated observation,
freshness, depth, and cost assumptions, so further strategy development was
not justified.

## Learning outcomes

- Prediction-market microstructure: executable prices are bid/ask and depth,
  not displayed midpoints.
- Contract and settlement risk: equivalence is a payoff claim involving source,
  timing, fallback, revision, void, and discretionary rules.
- Arbitrage versus relative value: a logical ordering can motivate research
  without becoming guaranteed arbitrage.
- Cost realism: fees, slippage, minimum size, and available depth determine
  whether a raw discrepancy is usable.
- Quantitative engineering: normalize APIs at the boundary, use exact Decimal
  arithmetic, preserve provenance, and make replay deterministic.
- Safety design: fail-closed validation, verified-pair separation, feed-health
  checks, and explicit risk boundaries prevent research observations from
  becoming execution authority.
- Evidence-driven practice: test hypotheses with bounded samples, record
  limitations, and stop when the data does not support an edge.

## Resume positioning

Possible bullets (choose the wording that matches the role):

- Built a Python, Decimal-based prediction-market research pipeline that
  normalized Kalshi/Polymarket metadata and order books, validated contract
  equivalence, and replayed sanitized observations deterministically.
- Implemented an authoritative-metadata CPI nested-threshold detector with
  freshness, displayed-depth, modeled-cost, and persistence filters; evaluated
  100 relationship-observations across 10 bounded observations.
- Designed fail-closed research and risk boundaries with verified-pair gates,
  feed-health checks, leg-risk modeling, synthetic fixtures, pytest, Ruff,
  mypy, pre-commit, and CI validation.
- Rejected unsupported arbitrage claims after a zero-signal CPI study,
  documenting settlement, liquidity, fee, and execution limitations as part of
  the investment-research decision process.

These bullets describe engineering and research evidence. They do not claim
profitability, realized returns, live trading, production execution, or
guaranteed opportunities.

## Interview guide

**30 seconds.** “I built a read-only prediction-market research system. It
normalized Kalshi and Polymarket data, verified whether contracts really shared
the same payoff, and tested a CPI nested-threshold relationship with replayable
snapshots and modeled cost/depth filters. Ten observations produced 100
relationship checks, no raw inconsistencies, and no cost-surviving signals, so
I stopped strategy development rather than overstate a result.”

**Two minutes.** Start with the equivalence problem: settlement semantics can
invalidate a price comparison. Explain the venue-neutral adapters and the
separation between manually verified strict-arbitrage pairs and advisory
research. Then describe metadata-derived CPI relationships, bid/ask detection,
snapshot/replay, persistence classification, and modeled scoring. Close with
the zero-signal study and the evidence-based stop decision.

Likely questions and answer points:

- **Why not compare prices directly?** Different sources, windows, units, or
  fallback/void rules can produce different payoffs.
- **Why use the bid and ask?** A candidate must be executable at the relevant
  side and size; a midpoint is not an executable price.
- **What makes the CPI relationship logical?** For one parent event with the
  same measure/window/unit and compatible YES semantics, YES at a higher
  threshold implies YES at a lower threshold in the ordinary state; the
  adapter rejects metadata that cannot prove those conditions.
- **Why are costs modeled?** Exact live fee semantics were not asserted where
  evidence was incomplete, so costs remain configurable assumptions.
- **What failed and what did you learn?** The bounded study found no raw or
  cost-surviving inconsistency. That falsified the tested opportunity hypothesis
  under the sample and taught that settlement and execution constraints matter
  more than attractive theoretical ordering.
- **What would you do differently?** Define the evidence schema and stopping
  rule earlier, then sample several pre-registered families only if they add a
  distinct, settlement-verifiable relationship.
- **What would justify reopening?** New primary evidence for a materially
  different relationship, a larger pre-specified sample, and independently
  supported fee/depth assumptions that could change the decision.

Rejecting an unsupported strategy was the intentional research outcome; the
repository does not disguise a failed profitability claim as success.

## Skills demonstrated

| Finance/quant capability | Evidence in the project |
| --- | --- |
| Python and APIs | Venue adapters, normalized domain models, public REST/WS boundaries |
| Quantitative research | Hypothesis, bounded sampling, scoring, persistence, stopping rule |
| Market microstructure | Bid/ask, depth, freshness, skew, slippage, leg risk |
| Derivatives/prediction-market reasoning | Payoff equivalence, thresholds, settlement exceptions |
| Data validation | Metadata provenance, fail-closed rejection, sanitized fixtures |
| Testing and CI | pytest, Ruff, mypy, pre-commit, GitHub CI |
| Risk controls | Verified-pair gate, health vetoes, explicit limits, no live authority |
| Reproducibility | Decimal arithmetic, compact snapshots, deterministic replay |
