# Decision Log

Record architectural and methodological decisions here so they are not reconstructed from AI memory.

This file also serves a learning and portfolio purpose: it should explain not only **what** was changed, but **why**, what trade-offs were considered, and what engineering lesson the decision demonstrates.

## Format

Each decision should include:

- ID
- date
- decision
- rationale
- alternatives considered
- trade-offs / consequences
- learning takeaway
- status
- evidence or references

## Active decisions

### D-001 — Repository is the source of truth

**Decision:** Version-controlled repository documentation and tested code override chat history, Notion notes, and AI memory when conflicts exist.

**Rationale:** Chat history and AI memory are convenient but are not durable, reviewable, or tied to a specific code revision. Keeping decisions beside the code makes them inspectable and versioned.

**Alternatives considered:** Rely on ChatGPT/Claude conversation history, or keep a separate Notion project record.

**Trade-offs / consequences:** Repository documentation requires deliberate maintenance, but avoids contradictory project histories and makes reviews reproducible.

**Learning takeaway:** In production engineering, the durable artifact should be version-controlled and auditable. AI is an assistant, not the authoritative record.

**Status:** ACTIVE

### D-002 — Private-first development

**Decision:** Keep the repository private during development and paper testing. Review secrets, history, licensing, and documentation before any public release.

**Rationale:** This project may eventually contain exchange credentials, operational configuration, execution logic, and account-specific information. Early private development reduces accidental disclosure risk.

**Alternatives considered:** Public development from the first commit.

**Trade-offs / consequences:** Recruiters cannot inspect the project while it is being built, but we gain a safer environment and can publish a cleaned, documented version later.

**Learning takeaway:** Security is easier when designed into the development process than when added after credentials or sensitive configuration have already leaked into Git history.

**Status:** ACTIVE

### D-003 — Modular adapter architecture

**Decision:** Keep venue-specific connectivity behind replaceable interfaces. Core arbitrage, normalization, risk, and analytics logic remain project-owned.

**Rationale:** Exchange APIs, SDKs, and third-party libraries can change or become outdated. A stable internal interface lets us swap connectivity implementations without rewriting strategy and risk logic.

**Alternatives considered:** Fork an existing Polymarket/Kalshi bot and build directly on its internal architecture; call exchange SDKs throughout the codebase.

**Trade-offs / consequences:** Interfaces add a small amount of upfront structure, but dramatically reduce vendor lock-in and make live, paper, and replay implementations interchangeable.

**Learning takeaway:** This demonstrates dependency inversion and the adapter pattern: business logic depends on our abstractions rather than on a specific external provider.

**Status:** ACTIVE

### D-004 — Deterministic core

**Decision:** LLMs do not participate in market-state maintenance, arbitrage arithmetic, risk approval, fill determination, or autonomous order decisions.

**Rationale:** These functions are mathematically defined and require reproducibility, low latency, clear failure behavior, and exact auditability. LLM outputs are probabilistic and therefore unsuitable for the critical trading path.

**Alternatives considered:** Use an AI agent to interpret markets and directly decide when to execute trades.

**Trade-offs / consequences:** We give up some flexibility in the execution loop, but gain deterministic behavior, easier testing, lower latency, and clearer risk controls. AI can still be used above the core for research, diagnostics, and reporting.

**Learning takeaway:** AI is most useful where interpretation is valuable; deterministic software is preferable where correctness can be defined explicitly.

**Status:** ACTIVE

### D-005 — Decimal monetary arithmetic

**Decision:** Monetary values and prices use decimal arithmetic rather than binary floating point unless a verified external interface requires conversion at a boundary.

**Rationale:** Binary floating-point representations can introduce small rounding artifacts into values that represent prices, quantities, fees, and edge calculations.

**Alternatives considered:** Use Python `float` everywhere for convenience and speed.

**Trade-offs / consequences:** `Decimal` is more verbose and generally slower than native floating point, but the expected workload is small enough that correctness is more important than arithmetic throughput.

**Learning takeaway:** Data types are part of financial-system design. Choosing an exact decimal representation at the domain boundary prevents subtle errors from propagating through risk and P&L calculations.

**Status:** ACTIVE

### D-006 — Manual contract pairing first

**Decision:** Initial cross-venue market pairs require explicit human verification of resolution terms. Semantic/LLM matching is deferred.

**Rationale:** Two contracts with similar titles can have different settlement sources, times, thresholds, wording, or resolution rules. A false match can turn an apparent arbitrage into directional risk.

**Alternatives considered:** Automatically pair contracts using titles, embeddings, or LLM semantic matching from the first version.

**Trade-offs / consequences:** Manual pairing limits coverage and scalability initially, but sharply reduces model risk while we validate the trading and execution infrastructure.

**Learning takeaway:** In arbitrage, contract equivalence is part of the risk model. Apparent price convergence is irrelevant if the underlying payoff definitions are not identical.

**Status:** ACTIVE

### D-007 — Adapter HTTP uses the standard library with an injectable transport seam

**Date:** 2026-09-05

**Decision:** Venue market-data adapters perform HTTP with `urllib.request` from the
standard library. Each adapter defines a small `Transport` protocol
(`request(method, url, *, timeout) -> HttpResponse`); the default implementation
is `urllib`-backed and tests substitute a deterministic fake. Every request sets
an explicit timeout.

**Rationale:** Keeps the project's zero runtime-dependency posture (`pyproject`
`dependencies = []`); the protocol seam gives fully offline, deterministic tests
without a mocking framework. No verified need yet for `httpx`/`requests`
(connection pooling, HTTP/2, retries) at market-data volumes.

**Alternatives considered:** add `httpx` (rejected — new dependency, not yet
justified); call `urllib` directly with no seam (rejected — forces network or
monkeypatching in tests).

**Trade-offs / consequences:** `urllib` is more verbose than `httpx` and has no
built-in retry/pooling, so those must be added by hand later if needed; in
exchange the project ships with zero third-party runtime code and the test suite
never touches the network.

**Learning takeaway:** Depend on a narrow interface you own (`Transport`), not on
a concrete HTTP library. The seam is what makes the adapter both swappable and
deterministically testable.

**Status:** ACTIVE — revisit if/when async or connection reuse is required (M2.1).

**Evidence:** `src/prediction_market_arbitrage/adapters/kalshi/transport.py`,
`docs/API_SOURCES.md`.

### D-008 — Kalshi order books are normalized with implied asks from complementary bids

**Date:** 2026-09-05

**Decision:** Kalshi returns bids only (`orderbook_fp.yes_dollars` /
`no_dollars`, ascending, best bid last). The adapter produces a normalized
`OrderBook` per side where `bids` are that side's bids (reversed to strictly
descending) and `asks` are implied from the **opposite** side's bids as
`price = 1 - opposite_bid_price`, size unchanged. Only `market_type == "binary"`
is accepted.

**Rationale:** For a binary market the two contracts settle to $1 total, so a
YES bid at X is a NO ask at `1 - X` (and vice versa). Confirmed by Kalshi docs
and by live data (top-of-book implied asks equal the market's quoted
`yes_ask_dollars` / `no_ask_dollars`). See `docs/API_SOURCES.md` K-07, K-08.

**Alternatives considered:** expose bids only and let the strategy layer imply
asks (rejected — pushes venue-specific arithmetic past the adapter boundary,
violating `docs/ARCHITECTURE.md`); assume the older cents-based
`orderbook.{yes,no}` shape (rejected — not observed in live responses).

**Trade-offs / consequences:** The adapter now encodes one venue-specific
identity (`1 - x`), so it must be re-checked for every new venue and if Kalshi
ever changes its book shape; the benefit is that the rest of the system sees a
uniform two-sided book and never learns that Kalshi is bid-only.

**Learning takeaway:** Normalize at the boundary. Downstream code should not need
to know which venue a book came from or how its asks were derived.

**Status:** ACTIVE for Kalshi. The `1 - x` identity must be re-verified per venue
(M1.3 Polymarket) before reuse.

**Evidence:** `src/prediction_market_arbitrage/adapters/kalshi/normalize.py`,
`tests/test_kalshi_normalize.py`, `docs/API_SOURCES.md`.

### D-009 — Polymarket US normalizes to one long-side OrderBook from the explicit two-sided book

**Date:** 2026-09-05

**Decision:** A Polymarket US market maps to one `Market`, two `Contract`s
(`:LONG` from the `long: true` marketSide, `:SHORT` from `long: false`), and
**one** `OrderBook` on the `:LONG` contract, built directly from the book's
explicit `bids` and `offers`. The book's `transactTime` is the `OrderBook`
timestamp (caller `observed_at` is the fallback only when the field is absent).
The adapter rejects any market whose `marketSides` is not exactly one long +
one short.

**Rationale:** Observed Polymarket US data is genuinely two-sided — one book per
slug with real `bids` and `offers` — so no ask synthesis is needed or honest.
The `1 - x` complement trick from D-008 is Kalshi-specific and is deliberately
**not** reused here (D-008 required per-venue re-verification). `transactTime` is
a real server timestamp, unlike Kalshi's book, so it is trusted over a local
clock reading.

**Alternatives considered:** synthesize a `:SHORT` book via `1 - price` like
Kalshi (rejected — invents data the API does not return, violates "do not
distort external data"); collapse both sides into a single anonymous `Contract`
(rejected — loses the long/short distinction the venue models explicitly);
always stamp with `observed_at` (rejected — discards a usable server timestamp).

**Trade-offs / consequences:** Downstream code gets only the long-side book from
Polymarket; a short-side view must be derived later if a strategy needs it. The
"exactly one long + one short" guard will reject any future multi-outcome
Polymarket market rather than mis-model it — a deliberate fail-loud choice.

**Learning takeaway:** Normalize to what the venue actually returns. Two venues
that both settle to $1 can still have different book shapes (bid-only vs.
two-sided); the adapter is where that difference is absorbed, and reusing
another venue's shortcut without re-verifying is a bug waiting to happen.

**Status:** ACTIVE for Polymarket US.

**Evidence:** `src/prediction_market_arbitrage/adapters/polymarket_us/normalize.py`,
`tests/test_polymarket_us_normalize.py`, `docs/API_SOURCES.md` (P-05..P-13).

### D-010 — Fetch before asserting anything about Git remote state

**Date:** 2026-09-05

**Decision:** Before any agent (or contributor) makes a claim about branch
existence, merge status, ancestry, or remote history — or acts on such a claim —
it must run `git fetch origin --prune` first. Local refs
(`refs/remotes/origin/*`, `git branch -vv` output) are treated as **stale until
refreshed** and are never authoritative on their own.

**Rationale:** During M1.2 an agent stated "branch `feat/kalshi-market-data` did
not exist" based on stale local refs; the branch existed on the remote and was
already based on a newly merged `main`. The wrong claim nearly led to work being
based on the wrong baseline. A fetch is cheap and removes the ambiguity.

**Alternatives considered:** trust local refs and reconcile later (rejected —
caused the incident); require a full `git fetch --all` + status writeup for
every command (rejected — heavier than needed; `--prune` on `origin` is enough).

**Trade-offs / consequences:** One extra network round-trip at the start of any
branch/merge reasoning. In exchange, ancestry claims are verifiable and
reproducible.

**Learning takeaway:** Distributed VCS has no single clock. "I don't see it"
means "my mirror hasn't been refreshed", not "it isn't there". Refresh, then
reason.

**Status:** ACTIVE.

**Evidence:** M2 branch-correction incident recorded in `docs/PROJECT_JOURNAL.md`.

### D-011 — Market pairs live in a curated file behind a fail-closed loader, not in the domain model or the engine

**Date:** 2026-09-06

**Decision:** Cross-venue contract equivalence (M1.4) is expressed as
human-reviewed records in a version-controlled TOML file
(`src/prediction_market_arbitrage/registry/data/market_pairs.toml`), loaded and
validated by `prediction_market_arbitrage.registry`. Each record carries a
`pair_id`, both venue legs (`venue` + `market_id` + `outcome` + primary-source
URLs), a normalized `proposition`, an explicit `relation`
(`IDENTICAL` / `COMPLEMENTARY`), an 11-item review `checklist`, `reviewer`,
`verified_at`, `settlement_notes`, `known_differences` (+ a
`known_differences_reviewed` affirmation), `status`
(`DRAFT` / `REVIEW_REQUIRED` / `VERIFIED` / `REJECTED` / `SUSPENDED`), and
`live_use_eligible` + `blocking_reason`.

The loader **fails closed**: any malformed record, unknown status, duplicate
`pair_id`, or conflicting venue mapping raises `RegistryError` and no registry is
returned. `MarketPairRegistry.eligible()` returns **only** `VERIFIED` records; a
`VERIFIED` record additionally requires a reviewer, a timezone-aware timestamp,
non-empty settlement notes, source URLs for **both** legs, every checklist item
`true`, and either a non-empty `known_differences` list or
`known_differences_reviewed = true`. `live_use_eligible = true` is rejected
outright in M1.4.

The existing domain `MarketPair` (id + two `Contract`s + free-text `note`) was
**left unchanged**. It is a sufficient *domain value*; it is not the place for
review-workflow metadata.

**Rationale:**
- *Not title-string matching* — titles are marketing text; equal titles routinely
  settle differently and different titles routinely settle identically. Zero
  signal about timing, authority, or void rules.
- *Not fuzzy / embedding similarity* — it optimizes for "reads similarly", which
  is the exact failure mode; a high score manufactures false confidence.
- *Not LLM semantic matching* — no calibrated error bound, not reproducible, not
  auditable at the moment money is at risk (D-004). Deferred: an LLM may later
  *propose* candidates for human review, never *approve* them.
- *Not hardcoded pair logic in the arbitrage engine* — that buries risk decisions
  in code diffs and couples strategy to specific markets; a curated data file
  keeps the decision visible, diffable, and reviewable as a *settlement-rules*
  review rather than a code review.
- *Not expanding `MarketPair`* — adding `reviewer` / `status` / `sources` to a
  frozen domain value would couple the deterministic core to a human workflow
  and put governance metadata onto `Opportunity.pair`.
- TOML over YAML/JSON: stdlib `tomllib` reads it (no new dependency; YAML would
  need `pyyaml`), it supports the comments a manually-curated risk file needs,
  and array-of-tables diffs cleanly in Git.

**Alternatives considered:** JSON registry (rejected — no comments, and a
review file benefits from inline rationale); YAML registry (rejected — new
runtime dependency for one milestone); a Python module of pair objects (rejected
— makes review a code review and invites logic creep); extending `MarketPair`
(rejected — see above).

**Trade-offs / consequences:** Coverage is limited to what a human has verified,
and each pair costs real review time. In exchange, an unverified or rejected pair
cannot reach strategy code by accident, and every equivalence claim is a
reviewable artifact with its evidence attached. The canonical registry ships
with **zero pairs** — no real venue identifiers appear in the file. Worked
format examples live only in `docs/MARKET_PAIRING.md` and the tests, using
obviously synthetic identifiers.

**Learning takeaway:** In arbitrage, "these are the same contract" is a risk
model input, not a string-similarity problem. Make that decision explicit,
human-owned, and enforced by code that fails closed — and keep it out of both the
domain model and the math engine.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/registry/`,
`tests/test_market_pair_registry.py`, `docs/MARKET_PAIRING.md`.

### D-012 — The arbitrage engine is a pure function, isolated from adapters, pairing, execution, and fee-source verification

**Date:** 2026-09-06

**Decision:** M1.5's arbitrage math lives in its own package
(`prediction_market_arbitrage.arbitrage`) as a pure calculator:
`ArbitrageEngine.evaluate(record, kalshi_book, polymarket_us_book, *,
evaluation_time, requested_quantity)` returns an `OpportunityEvaluation` and has
no I/O, no wall-clock time, no venue knowledge, and no position/order concepts.

- **Registry gate, not bypassable.** The engine evaluates a `MarketPairRecord`
  only if its status is `VERIFIED`. `evaluate_from_registry(registry, pair_id,
  ...)` additionally requires the record to be in `registry.eligible()`. Any
  other status raises `ArbitrageError`.
- **Books are inputs.** The engine consumes already-normalized `OrderBook`s from
  the adapters (M1.2/M1.3); it never fetches them.
- **Fees are injected.** A `FeeModel` protocol is supplied by the caller;
  shipped models are `ZeroFeeModel` and a synthetic `FixedPerUnitFeeModel`. No
  real venue schedule is hardcoded (A-022).
- **Execution buffer is an explicit `Decimal` input.** No statistical slippage
  estimate.
- **Only `COMPLEMENTARY` is evaluated** (the buy/buy model). `IDENTICAL` records
  return no opportunity with a reason — not because identical contracts cannot be
  arbitraged, but because capturing that edge means selling/shorting the richer
  side, which needs execution semantics outside this engine. Deferred, not ruled
  out.
- **Exact `Decimal` throughout**, no internal rounding; the only divisions are
  the derived `*_per_unit` fields, and the opportunity test uses exact totals.

**Rationale:** A strategy that is a pure function of (verified record, two books,
config, evaluation time) is deterministic, replayable against recorded books
(M2.3), and testable with exact known-answer `Decimal` cases. Entangling it with
network I/O, human review, or execution would destroy all three properties and
let a change to the math quietly loosen a risk decision.

Separation, and why each boundary matters:

| Separated from | Why |
|---|---|
| Venue adapters | Engine correctness must not depend on network/auth/venue uptime; adapter bugs stay in the adapter layer. |
| Market-pair verification (M1.4) | Equivalence is a human risk judgement; keeping it out of the engine means editing the math can never change which pairs count as "the same bet". |
| Execution / broker logic (M2.4) | Leg risk, one-sided fills, latency, partial fills, minimum sizes belong where they can be *simulated*, not asserted. |
| Fee-source verification (A-022) | Fee formulas are evidence gathered separately; injecting the `FeeModel` keeps the engine correct whether or not a venue's schedule is known. |

**Alternatives considered:** compute inside the arbitrage engine which pairs are
equivalent (rejected — see M1.4 / D-006, D-011); hardcode current venue fee
formulas (rejected — unverified; A-022); have the engine fetch books itself
(rejected — couples math to I/O, kills replay/determinism); extend the domain
`Opportunity` with the full cost/edge breakdown (rejected — `Opportunity` is a
minimal venue-neutral container reused by future strategy output; the audit
detail lives in the strategy-layer `OpportunityEvaluation`, and
`OpportunityEvaluation.to_opportunity()` builds the minimal container when an
opportunity exists — mirrors D-011's boundary).

**Trade-offs / consequences:** The engine cannot, by construction, tell you
whether a positive edge will be *realized* — that needs the paper broker. It
also does not implement same-market complete-set arbitrage (a ROADMAP M1.5
bullet): `MarketPairRecord` is cross-venue by construction (fixed `kalshi` +
`polymarket_us` legs), so a same-venue pairing has no registry representation
today. Flagged for a future registry extension or a separate mechanism.

**Learning takeaway:** Keep the deterministic core deterministic. Every
dependency you refuse to bake in — the network, the human equivalence call, the
fee schedule, the execution model — is a dependency you can test, replay, and
reason about in isolation later.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/arbitrage/`,
`tests/test_arbitrage_engine.py`, `docs/ARBITRAGE_METHODOLOGY.md`.

### D-013 — Venue fee models are evidence-backed, venue-specific, taker-only, and still injected

**Date:** 2026-09-06

**Decision:** M1.6 adds two real fee models next to the M1.5 baseline
(`ZeroFeeModel`, `FixedPerUnitFeeModel`), plus a router:

- `KalshiTradingFeeModel` — `fee = round_up_to_next_cent(M · 0.07 · C · P · (1−P))`,
  the Kalshi published general trading (taker) fee, "Fee Schedule for July 2026
  — 7.7.26 Update". `M` is the per-contract multiplier (`multiplier=` arg,
  default `Decimal("1")`); a caller passes an evidence-backed `M` for a series
  in Kalshi's "non-standard fees" table. No settlement fee. The pre-July-2026
  standalone `0.035` S&P 500 / Nasdaq-100 coefficient was removed — that table
  is now part of the per-series `M` system.
- `PolymarketUsTradingFeeModel` — `fee = bankers_round_cent(0.06 · C · p · (1−p))`,
  the Polymarket US published exchange-wide taker fee (`docs.polymarket.us/fees`,
  effective July 1, 2026; re-verified 2026-09-06). Kept at `0.06`; a prompt's
  `0.05` claim was not adopted — it is contradicted by the live official
  schedule (A-025).
- `VenueFeeModel` — a `Mapping[venue, FeeModel]` router; each leg's fills go to
  its own venue's model. Unknown venue → `ArbitrageError` (fail closed).
  `VenueFeeModel.real_taker()` bundles the two real models.

Scope boundaries:

- **Taker only.** The buy/buy engine always lifts resting asks. Kalshi maker
  (`0.0175`) and Polymarket US maker **rebate** (`−0.0125`) and the Polymarket
  US volume-tier taker rebate are recorded in docstrings / `docs/` but not
  computed — a rebate is a negative fee the `FeeModel` contract forbids, and the
  engine has no maker leg.
- **Per-fill-slice rounding** (A-026): each `(price, qty)` slice is rounded and
  the rounded slices summed. Multi-level-sweep rounding is undocumented on both
  venues.
- **No series detection.** `KalshiTradingFeeModel` cannot tell which Kalshi
  series a book belongs to; the caller passes the per-contract multiplier `M`
  (default `1`) from Kalshi's current "non-standard fees" table.
- **Still injected.** The engine keeps its `FeeModel` protocol and its
  fee-value validation (finite, non-negative Decimal); it gains no venue
  knowledge. `EngineConfig.fee_model` still defaults to `ZeroFeeModel`.
- **Primary sources retained** under `docs/evidence/` (the Kalshi PDF opens in
  a normal browser but blocks plain CLI fetchers; Polymarket's page is
  client-rendered).

**Rationale:** The taker formulas are verified from primary sources and
reproduce every row of each venue's published fee table, so a caller doing paper
analysis should be able to use the real numbers without hand-rolling them — but
the engine must not bake them in (D-012): the numbers change (Kalshi's schedule
moved from a Feb-2026 form to the 7.7.26 multiplier form mid-project), only the
taker path is modelled, Kalshi's per-series `M` is caller-supplied from its
current table, and Polymarket US has open questions (a prompt-asserted `0.05`
contradicted by the live schedule; a reported CFTC-filing basis-points form)
(A-024 / A-025). Keeping the models as separate injected objects means a fee
change is a one-line caller edit and a new evidence extract, not an engine
change.

**Alternatives considered:** hardcode the formulas in the engine (rejected —
D-012; also hides the taker-only / unresolved-conflict caveats); model maker and
rebate terms now (rejected — out of scope for a buy/buy engine and needs a
signed-fee interface); a single combined model with an internal venue `if`
(rejected — `VenueFeeModel` routing keeps each venue's schedule in its own
class with its own venue guard).

**Trade-offs / consequences:** A positive `net_edge` computed with
`VenueFeeModel.real_taker()` is still not a live-trading signal — no formula has
been OBSERVED against a real fill, and fee reconciliation stays a real-money-gate
item. Callers evaluating a Kalshi series with a non-standard multiplier must
supply the evidence-backed `M` themselves.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/arbitrage/fees.py`,
`tests/test_arbitrage_fees.py`, `docs/evidence/kalshi-fee-schedule-2026-07-07.txt`,
`docs/evidence/polymarket-us-fee-schedule.txt`, `docs/ASSUMPTIONS.md`
A-024 / A-025 / A-026.

## Documentation rule going forward

For every material architectural, trading, risk, testing, or data-model decision, record the decision here before or alongside implementation. The entry should be understandable to someone reviewing the repository months later without access to the original ChatGPT or Claude conversation.

When a decision changes, do not silently rewrite history. Mark the old decision as superseded and add a new decision explaining why the project changed direction.
