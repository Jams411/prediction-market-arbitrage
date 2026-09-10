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
whether a positive edge will be *realized* — that needs the paper broker. The
cross-venue `evaluate` path does not implement same-market complete-set
arbitrage: `MarketPairRecord` is cross-venue by construction (fixed `kalshi` +
`polymarket_us` legs), so a same-venue pairing has no registry representation.
**Superseded in part by D-025**, which adds `evaluate_complete_set` as a
separate, registry-free method rather than extending `MarketPairRecord`.

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

### D-014 — Live book state is a pure state machine over decoded WS messages, with fail-closed health; the socket is a separate boundary

**Date:** 2026-09-06

**Decision:** M2.1 ships `prediction_market_arbitrage.livebook`:

- `updates.py` — venue-neutral `BookSnapshot` (full book for one contract) and
  `BookDelta` (signed change to the aggregated quantity at one `(side, price)`),
  both exact `Decimal`, timestamps tz-aware, optional `sequence`.
- `state.py` — `LiveBook` (a contract's `price → quantity` index; additive delta
  application, zero-level removal) and `LiveBookFeed` (connection state +
  per-subscription sequencing + staleness against an **injected** `now` +
  `FeedHealth`). Health is **fail-closed**: `trading_enabled` is `True` only for
  `HealthStatus.HEALTHY`; `UNINITIALIZED`, `STALE`, `DISCONNECTED`, `RESYNCING`,
  `DESYNCED`, `MARKET_NOT_OPEN` all disable it and `current_order_book(now)`
  returns `None`. Domain invariants (ordering, not-crossed) are enforced by
  building a real `OrderBook`; a crossed result → `DESYNCED`.
- `kalshi_ws.py` / `polymarket_us_ws.py` — **pure** decoders from each venue's
  documented WebSocket frames (`API_SOURCES.md` K-WS-*, P-WS-*). Kalshi
  `orderbook_snapshot` / `orderbook_delta` → a YES/NO pair of updates (the K-08
  `1 - opposite_bid` implied-ask coupling); Polymarket `MARKET_DATA` → one
  `:LONG` full snapshot.

Boundaries:

- **No socket, no credentials, no wall-clock** (D-012 style). Both venues'
  market-data WebSockets need API-key auth in the handshake, so a real transport
  (handshake, keep-alive Pong, reconnect/backoff) is deferred; `LiveBookFeed`
  exposes `mark_disconnected()` / `begin_resync()` for it to call (A-027).
- **Sequencing is per-venue.** Kalshi `seq` gap → `DESYNCED` until a resync
  snapshot; duplicate/stale `seq` ignored. Polymarket has no sequence — every
  frame is a full snapshot; a `transactTime`-older frame is dropped
  (at-least-once, P-WS-04). `require_sequence` selects the behaviour.
- **Delta application is additive** (A-028) — documented-consistent but not
  OBSERVED against a live Kalshi feed.
- **Market-state gating** applies only to feeds that report it (Polymarket
  `MARKET_STATE_OPEN` = tradeable, all else not). Kalshi's orderbook channel
  carries no state; halt detection there needs a separate channel (A-029).

**Rationale:** Same payoff as the M1.5 engine — a book state that is a pure
function of (decoded messages, injected clock) is deterministic, replayable
(M2.3), and exhaustively testable with exact `Decimal` cases. Keeping the socket
out means auth, flakiness, and backoff live where they can be faked, and the
fail-closed health verdict is the single thing a future strategy/risk layer
gates on.

**Alternatives considered:** decode straight to a domain `OrderBook` and diff
(rejected — loses the sequence/health machinery and the additive-delta record);
one combined feed object per venue pair (rejected — one `LiveBookFeed` per
contract keeps Kalshi's YES/NO coupling explicit at the decoder, not the core);
ship a real `asyncio` WebSocket client now (rejected — needs credentials and is
not deterministically testable; A-027).

**Trade-offs / consequences:** M2.1 cannot prove a real feed behaves as the docs
say — no frames were captured (auth-gated), so there is no WS fixture and A-028
stays UNVERIFIED. A Kalshi feed can read `HEALTHY` through a halt this layer
cannot see (A-029). Real-money trading stays disabled.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/livebook/`,
`tests/test_livebook_state.py`, `tests/test_livebook_kalshi_ws.py`,
`tests/test_livebook_polymarket_us_ws.py`, `docs/API_SOURCES.md` (K-WS-*, P-WS-*),
`docs/ASSUMPTIONS.md` A-027 / A-028 / A-029.

### D-015 — The authenticated WebSocket transport is an injected boundary: docs-verified auth builders, a deterministic reconnect/resync manager, and a thin `websockets` transport (signer stays injected)

**Date:** 2026-09-06

**Decision:** M2.1's transport work (`livebook.credentials`, `livebook.ws_auth`,
`livebook.transport`) stops at the last deterministically testable layer:

- `credentials.py` — `KalshiCredentials` / `PolymarketUsCredentials`, frozen,
  **redacted** `repr`/`str`, built by the caller from config
  (`*_credentials_from_env` read explicit env var names). No secret is
  hard-coded, logged, or written to disk.
- `ws_auth.py` — pure builders, each **verified from official docs**
  (`API_SOURCES.md` K-WS-AUTH-*, P-WS-AUTH-*): the exact sign string
  (`timestamp + "GET" + path`), the three auth headers, the URL constants, and
  the subscribe command. The RSA-PSS (Kalshi) / Ed25519 (Polymarket US)
  signature is produced by an **injected `Signer`** — the framework imports no
  `cryptography`.
- `transport.py` — `WebSocketTransport` / `SnapshotSource` **protocols** (the
  socket + REST-resync seams), a pure `BackoffPolicy`, frame decoders
  (raw frame → M2.1 updates; control frames → `[]`), and `LiveBookConnection`:
  `connect_and_subscribe` → `pump_one` (route each decoded update to its feed by
  `contract_id`) → on `TransportClosed`: `handle_disconnect` (every feed →
  `DISCONNECTED`) → `reconnect(sleep)` (backoff, optional `max_attempts`) →
  `resync()` (per feed: `begin_resync` → `SnapshotSource.fetch` →
  `apply_snapshot` → `HEALTHY`). `run_forever(sleep, should_continue)` is the
  only loop; every effect (socket, REST, clock, sleep) is injected.

**Concrete transport (added same day):** `ws_transport.py` —
`WebsocketsTransport`, a `WebSocketTransport` over the `websockets` library
(`websockets>=13`, the project's **sole runtime dependency**; the client both
venue docs use; pure Python, no transitive deps). It is the only `livebook`
module that does real network I/O or imports a third-party package.
`connect(handshake)` opens `websockets.sync.client.connect(url,
additional_headers=headers)` (held as a context manager); `send` / `receive` /
`close` wrap `send` / `recv(timeout)` / CM-exit; `ConnectionClosed` and a
recv-timeout both surface as `TransportClosed`; the library answers server
Ping/Pong. It plugs into the unchanged `LiveBookConnection`.

**Still NOT built:** a `Signer` implementation. The RSA-PSS / Ed25519 step stays
the caller's, so the framework takes **no `cryptography` dependency**. And no
real authenticated connection has been made — `WebsocketsTransport` is tested
against a local `websockets` loopback server (real socket, accepts any headers),
which is **not** evidence a real venue accepts the handshake. That gap and the
missing live OBSERVED frame are **A-030**.

**Rationale:** Same discipline as D-012 / D-014 — keep the part that can be a
pure function pure. The auth sign-strings and reconnect/resync sequencing are
exactly the bug-prone logic; making them injectable-effect functions means they
are unit-tested against the docs today and a real socket is a thin adapter
later. A wrong sign string or a botched resync order would silently disable or
mis-feed the book; those are now pinned by tests.

**Alternatives considered:** hand-roll RFC 6455 over `ssl`+`socket` (rejected —
large unreviewable surface for a boundary; `websockets` is smaller and is what
the docs use); add `cryptography` for the signature (rejected — kept behind the
injected `Signer` so the tree stays crypto-free); `websocket-client` instead of
`websockets` (rejected — `websockets` matches the docs' `additional_headers`
handshake mechanism exactly and has a first-class sync API and no transitive
deps).

**Trade-offs / consequences:** `websockets` is now a runtime dependency (was
zero). A real connection still needs the caller to supply a `Signer` and live
credentials; the first such connection must capture an `orderbook_delta` /
`MARKET_DATA` frame and confirm the handshake — that observation resolves A-028
and A-030 together and is a prerequisite for any live path. Real-money trading
stays disabled.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/livebook/credentials.py`,
`.../ws_auth.py`, `.../transport.py`, `.../ws_transport.py`,
`tests/test_livebook_credentials.py`, `tests/test_livebook_ws_auth.py`,
`tests/test_livebook_transport.py`, `tests/test_livebook_ws_transport.py`,
`pyproject.toml` (`websockets>=13`), `docs/API_SOURCES.md`
(WS-A-S1..S6, K-WS-AUTH-*, P-WS-AUTH-*), `docs/ASSUMPTIONS.md` A-027 / A-030.

### D-016 — The recorder is a write-only, append-only DuckDB sink, decoupled from strategy/execution, with string-Decimal / naive-UTC fidelity

**Date:** 2026-09-06

**Decision:** M2.2 ships `prediction_market_arbitrage.recorder`, backed by one
embedded DuckDB database (file or `:memory:`; `duckdb>=1.0` is the second
runtime dependency).

- **Write-only.** `Recorder` exposes `record_order_book`, `record_opportunity`,
  `record_order_event`, `record_fill`, `record_position`, `record_pnl`,
  `record_health_event` — and nothing that updates or deletes. An entity that
  changes over time (order status, position, PnL, feed health) is a **sequence
  of appended rows** ordered by a monotonic per-table `id` (a DuckDB
  `SEQUENCE`) plus injected event / record timestamps.
- **Deterministic.** No wall-clock read, no random id: given the same call
  sequence with the same inputs against a fresh database, the rows are
  byte-identical. Row ids come from sequences (monotonic under single-threaded
  ordered inserts); `session_id` and every timestamp are caller-supplied.
- **Decoupled.** The recorder imports the *types* it stores (`OrderBook`,
  `OpportunityEvaluation`, `FeedHealth`) but none of their behaviour, and no
  strategy / engine / transport code imports the recorder. Orders / fills /
  positions / PnL have no domain model yet (M2.4 / M2.5), so the recorder owns
  their row schema in `recorder.models` (`OrderEventRow`, `FillRow`,
  `PositionRow`, `PnlRow`).
- **Fidelity.** Monetary / price / quantity columns are `VARCHAR` holding exact
  `str(Decimal)` text — a `Decimal(text)` round-trip is exact at any scale, and
  a fixed-scale `DECIMAL(38, n)` column is deliberately *not* used. Timestamps
  must be timezone-aware on the way in; they are normalized to UTC and stored as
  a naive-UTC `TIMESTAMP` (microsecond precision, matching what the domain
  already carries — see A-031). Naive datetimes and non-`Decimal` money values
  raise `RecorderError`.
- **Schema.** `schema.initialize` is idempotent (`CREATE ... IF NOT EXISTS`) and
  refuses a database written by a different `SCHEMA_VERSION` (no migrations in
  M2.2). Tables: `recording_sessions`, `order_book_snapshots` +
  `order_book_levels`, `opportunities`, `order_events`, `fills`, `positions`,
  `pnl`, `health_events`, `schema_meta`.

**Rationale:** A recorder that never mutates is trivially auditable and safe to
run alongside a live loop — a bug can add junk rows but cannot corrupt history.
String-Decimal storage removes the one place a financial value could silently
lose precision on the way to disk. DuckDB gives SQL + columnar analytics and
zero-copy Arrow/pandas export for the replay adapter (M2.3) with no server.

**Alternatives considered:** SQLite (rejected — DuckDB's `DECIMAL`/`TIMESTAMP`
handling and analytical queries fit replay/analysis better, and the ROADMAP
names DuckDB); store `DECIMAL(38, 18)` columns (rejected — caps scale and
precision; the recorder does no math so text is strictly safer); an ORM
(rejected — a dependency and indirection for ~9 flat append tables); `UPDATE`
mutable rows for orders/positions (rejected — kills the append-only audit
guarantee; state-over-time is a row sequence).

**Trade-offs / consequences:** `duckdb` is now a runtime dependency. Timestamps
are stored naive-UTC, so a reader must re-attach UTC (the M2.3 replay adapter
will); the original `tzinfo` object is not preserved, only the UTC instant at
microsecond precision (A-031). No replay/query API ships here — M2.3.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/recorder/`,
`tests/test_recorder_schema.py`, `tests/test_recorder.py`,
`pyproject.toml` (`duckdb>=1.0`), `docs/ASSUMPTIONS.md` A-031.

### D-017 — Replay is a read-only, deterministic reconstruction of a recording, timed by an injected sleep, feeding the live-book path

**Date:** 2026-09-07

**Decision:** M2.3 ships `prediction_market_arbitrage.replay`, a **read-only**
consumer of an M2.2 recorder database. No new runtime dependency (`duckdb` is
already present).

- `ReplaySession(connection | .open(path, read_only=True), *, session_id)` —
  validates `schema_meta.schema_version` and that the session exists, then
  exposes one iterator per recorded stream (`order_books`, `opportunities`,
  `order_events`, `fills`, `positions`, `pnl`, `health_events`), each
  `SELECT ... ORDER BY id` (the recorder's monotonic append key). No `record_*`
  / write / update / delete method exists on the class.
- **Reconstruction fidelity.** Stored `VARCHAR` text → exact `Decimal(text)`;
  stored naive-`TIMESTAMP` → UTC reattached explicitly with
  `.replace(tzinfo=UTC)` (`replay._read.to_utc`, per A-031). Domain `OrderBook`,
  `livebook.FeedHealth`, `registry.OutcomeRelation` are rebuilt from the rows.
  `Venue.name` / `Market.title` are synthesized from the ids (A-032) — the
  recorder stored identifiers only; every field strategy code joins on is exact.
  A `health_events` row whose stored `trading_enabled` disagrees with the
  reconstructed status raises `ReplayError` (a corruption check).
- **Deterministic order.** `timeline()` merges the streams and sorts on
  `(recorded_at, kind_rank, row_id)` — a fixed total order. Two byte-identical
  recordings replay to equal `timeline()`s.
- **Injected timing.** `play(sleep=no_sleep, speed=1.0)` yields `timeline()`
  events, calling `sleep(gap / speed)` for the recorded wall-gap before each
  event after the first. `no_sleep` (the default) makes replay a plain
  deterministic iterator for tests; `realtime(speed)` returns a `time.sleep`
  wrapper for real-time playback. The engine never reads a wall clock itself.
- **Strategy-interface compatibility.** `as_book_snapshots()` yields
  `livebook.BookSnapshot` objects (`sequence` / `market_state` = `None`), and
  `feed_book_snapshots({contract_id: LiveBookFeed})` applies them through the
  unchanged `LiveBookFeed.apply_snapshot`, paced like `play`. That is the
  "replay through the same strategy-facing interface" surface — where current
  abstractions allow it. Re-running the M1.5 engine needs the verified pair
  record, which the recorder does not store (only the *result*), so that path
  is left to the caller with the reconstructed `OrderBook`s + `RecordedOpportunity`.

**Rationale:** A recording is an audit artifact; a replay that can only read it,
reconstructs it deterministically, and hands books to the same `LiveBookFeed`
the live path uses lets M2.4/M2.5 be exercised against captured reality with no
network and no non-determinism. Keeping timing injected (default no-sleep) means
every replay test is fast and exact; `realtime` is one small wrapper for the
rare real-time need.

**Alternatives considered:** replay through a `WebSocketTransport` fake that
re-emits recorded frames (rejected — the recorder stores normalized
`OrderBook`s, not raw venue frames; reconstructing frames would be lossy and
venue-specific); a single SQL `UNION ALL` for `timeline()` (rejected — a Python
merge of already-ordered streams is clearer and the sort key is explicit); make
`play` sleep by default with real `time.sleep` (rejected — determinism-first,
matching the rest of the codebase; opt in via `realtime`).

**Trade-offs / consequences:** `Venue.name` / `Market.title` are not
round-tripped (A-032). The engine cannot be auto-re-run from a recording alone
(no stored pair record). Replay of a `:memory:` database requires handing in the
live connection; file databases open `read_only=True`.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/replay/`,
`tests/test_replay.py`, `tests/replay_support.py`,
`docs/ASSUMPTIONS.md` A-031 / A-032.

### D-018 — The paper broker is a pure, injected-effect simulator of taker execution against real book depth

**Date:** 2026-09-07

**Decision:** M2.4 ships `prediction_market_arbitrage.paper_broker`. No new
runtime dependency.

- `PaperBroker` keeps mutable order/position state internally and hands out
  frozen `Order` / `Fill` / `LegRiskSnapshot` snapshots. The caller advances
  simulated time: `submit(request, *, at)`, `cancel(order_id, *, at)`,
  `advance(*, at, books)` where `books` is `{contract_id: OrderBook}` live at
  `at`. Time is monotonic non-decreasing (enforced); every timestamp is
  injected; there is no wall-clock read and no RNG.
- **Matching.** A buy walks `book.asks`, a sell `book.bids`, best price first,
  stopping at a limit price. Eligible only when
  `effective_at <= at` **and** `book.timestamp >= effective_at` (latency: an
  order reaches the engine at `submit + submit_latency`, and a book captured
  before that cannot fill it). Partial fills leave the order working unless it
  is IOC. One `Fill` per book level, `liquidity = "taker"`, fee from the
  injected `FeeModel` (reuses `arbitrage.FeeModel` — `ZeroFeeModel` default),
  execution price from the injected `SlippageModel` clamped to
  `[0.0001, 0.9999]` (A-033).
- **Lifecycle.** `SUBMITTED → PARTIALLY_FILLED → FILLED`, or `REJECTED`
  (malformed request, below `min_order_size`, IOC/market with no eligible
  liquidity on its first eligible book), `CANCELED` (cancel effective at
  `cancel_time + cancel_latency` — a fill that lands first wins; IOC remainder),
  `EXPIRED` (market-order remainder past `market_order_ttl`). Each transition is
  an appended `StatusTransition`; `OrderStatus` values match
  `recorder.ORDER_STATUSES`.
- **Leg risk.** `leg_risk(a, b, *, as_of, books)` returns the deterministic
  measurement of one-legged exposure — `unhedged_quantity = a.filled −
  b.filled`, each leg's average price, the mid of `b`'s current book as the
  price to complete the missing leg, and `abs(unhedged) × that mid`. It does not
  judge whether the exposure is acceptable — that is the M2.5 risk manager.
- **Recorder integration, no redesign.** `Order.event_rows()` →
  `list[recorder.OrderEventRow]`; `Fill.to_row()` → `recorder.FillRow`;
  `PaperBroker.position(contract_id, *, as_of)` → `recorder.PositionRow`. The
  broker imports those four row types and nothing else from the recorder; it
  does not import `Recorder`. The recorder / replay packages do not import the
  broker.

**Rationale:** Same discipline as the M1.5 engine and M2.1/M2.3 — a simulator
that is a pure function of (requests, injected books, injected times, config) is
deterministic, replayable against M2.3 output, and exhaustively testable with
exact `Decimal` known-answer cases. Reusing `arbitrage.FeeModel` means the fee
schedule the strategy priced with (M1.6) is the one the paper fills pay.

**Alternatives considered:** an event-loop broker with its own scheduler
(rejected — a stepped `advance(to)` is simpler and its ordering is explicit);
model resting/maker fills now (rejected — needs queue-position and order-flow
assumptions with no evidence; deferred); a random slippage draw (rejected —
kills determinism; `SlippageModel` is a pure function); give the broker its own
Order/Fill row types (rejected — the recorder already owns those since M2.2;
reuse them).

**Trade-offs / consequences:** Taker-only (A-033) — no maker-fill, queue, or
hidden-liquidity modelling. The `[0.0001, 0.9999]` clamp is a chosen epsilon,
not a verified venue tick. Positive simulated fills are **not** realized fills;
real latency, partial-fill microstructure, and venue rejection semantics stay
unproven until a live path exists (which the real-money gate still blocks).

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/paper_broker/`,
`tests/test_paper_broker.py`, `tests/paper_broker_support.py`,
`docs/ASSUMPTIONS.md` A-033.

### D-019 — The risk manager is a deterministic, fail-closed veto over existing objects — no strategy, no new inputs

**Date:** 2026-09-07

**Decision:** M2.5 ships `prediction_market_arbitrage.risk`. No new runtime
dependency.

- `RiskLimits` (frozen, config-injected, Decimal / timedelta; `None` disables a
  check): `max_position`, `max_exposure`, `max_order_size`,
  `min_net_edge_per_unit`, `max_data_age`, `max_unhedged_time`,
  `max_consecutive_errors`, `max_daily_loss`, plus the always-on kill switch.
- `RiskManager.evaluate_order(request, *, now, positions?, marks?, opportunity?,
  health?, leg?, leg_pair_key?)` returns `RiskDecision(allowed, reasons,
  checks_run, as_of)` — it runs **every configured check** and collects **all**
  failing reasons (not just the first). `evaluate_opportunity(opportunity, *,
  now, health?)` is the session-wide + edge subset for gating before an order is
  sized.
- **Inputs are the earlier milestones' own objects, unchanged:** M1.5
  `OpportunityEvaluation` (`net_edge_per_unit`, `has_opportunity`), M2.1
  `FeedHealth` (`trading_enabled`, `as_of` / `last_update`), M2.4 `OrderRequest`
  / `LegRiskSnapshot`, `recorder.PositionRow`. The `risk` package imports those
  types and nothing else; no strategy / execution / broker code imports `risk`.
- **Fail closed (A-034).** A limit that is set but whose required input is
  missing (`positions`, `opportunity`, `health`, `leg`) → reject. A provided
  `FeedHealth` with `trading_enabled == False`, or a future-dated health
  timestamp → reject. `max_exposure` that cannot value a held contract (no
  `marks`, `avg_price == 0`, no limit price) → reject.
- **State (`RiskState`).** The kill switch, the consecutive-error counter, a
  per-UTC-day realized-PnL ledger (`record_realized_pnl(amount, *, at)`), and a
  per-pair "unhedged since" map. `evaluate_order` / `observe_leg_risk` update
  the unhedged timer as a deliberate side effect — the manager must remember
  when a pair first went unhedged to measure its age. Every mutation takes an
  injected `at` / `now`; no wall-clock, no RNG.
- **Semantics.** `max_position` compares the **projected signed** quantity
  (`current + (qty | -qty)`); `max_exposure` sums `|projected_qty_c| * mark_c`
  across all contracts (`mark_c` = explicit `marks`, else `avg_price`, else the
  order's limit price for its own contract); `max_daily_loss` is the realized
  loss magnitude for `now`'s UTC day; `max_unhedged_time` measures `now − since`
  for a non-terminal, non-zero `unhedged_quantity`.

**Rationale:** A risk layer that is a pure function of (limits, injected clock,
supplied inputs, `RiskState`) is deterministic, testable with exact
known-answer cases, and replayable against M2.3 output. Making it consume the
existing objects — rather than defining its own position / health / opportunity
types — keeps the seam thin and means a limit change is a one-line
`RiskLimits(...)` edit. Returning every failing reason (not the first) makes a
rejection actionable.

**Alternatives considered:** raise on rejection instead of returning a decision
(rejected — a decision object composes; `RiskDecision.raise_if_rejected()` is
there for callers that want the throw); let the manager hold its own position
book (rejected — the paper broker already owns positions; the manager takes a
`PositionRow` mapping); mark exposure at live book mid by default (rejected — no
book is guaranteed at decision time; cost-basis `avg_price` is a deterministic
fallback approximation and explicit current `marks` is the preferred override).

**Trade-offs / consequences:** `evaluate_order` is not side-effect free (it
advances the unhedged timer) — documented (A-034). Cost-basis exposure is a
fallback approximation, not a conservative bound: it can understate risk after
an adverse move, so `max_exposure` is not safely enforced from cost-basis /
stale valuation alone — a live caller must pass current `marks`. The
manager vetoes but does not act — nothing here submits, cancels, or sizes an
order. Real-money trading stays disabled (D-002).

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/risk/`,
`tests/test_risk_manager.py`, `tests/risk_support.py`,
`docs/ASSUMPTIONS.md` A-034.

### D-020 — The operational dashboard is a pure, read-only projection of in-memory pipeline objects — no persistence reads, no side effects

**Date:** 2026-09-07

**Decision:** M3.1 ships `prediction_market_arbitrage.dashboard`. No new runtime
dependency.

- `build_dashboard(*, now, feeds?, registry?, opportunities?, orders?,
  positions?, marks?, pnl?, leg_risk?, risk?, last_risk_decision?,
  max_data_age?)` returns an immutable `DashboardView` (frozen dataclasses):
  `feeds`, `pairs`, `opportunities`, `orders`, `fills`, `positions`, `pnl`,
  `leg_risk`, `risk`, `alerts`, `worst_data_age`, and a `healthy` property.
  `render_text(view)` renders a deterministic sectioned plain-text report.
- **Inputs are the earlier milestones' own objects, unchanged:** M1.4
  `MarketPairRegistry` (`.all()`), M1.5 `OpportunityEvaluation`, M2.1
  `LiveBookFeed` / `FeedHealth`, M2.4 `Order` / `Fill` / `PositionRow` /
  `LegRiskSnapshot`, M2.2 `PnlRow`, M2.5 `RiskManager` / `RiskDecision`. The
  `dashboard` package imports those types and nothing else; nothing imports
  `dashboard`.
- **Read-only + deterministic.** Every input is inspected, never mutated; `now`
  is injected (naive → `DashboardError`); no wall-clock, no DuckDB / recorder
  read, no socket, no order submission. `fills` are flattened from `Order.fills`
  (not a separate input). `risk` state is read via `RiskManager.snapshot(now=)`,
  which is itself pure.
- **WebSocket state** is derived from `FeedHealth.status` — the livebook layer
  (M2.1) exposes no separate socket-state accessor (`LiveBookConnection` only
  offers `feed_health()` / `all_healthy()`). Mapping: `DISCONNECTED` →
  `disconnected`, `RESYNCING` → `resyncing`, `UNINITIALIZED` → `offline`,
  everything else → `connected`.
- **Alert severity policy (A-035).** `ALERT` = kill switch engaged, any feed not
  `trading_enabled` for a hard reason, any stale feed. `WARN` = `resyncing` /
  `market_not_open` feed, consecutive errors > 0, a realized daily loss, an
  unhedged pair / leg, a rejected paper order, a stale opportunity / position
  (age > `max_data_age`), a rejected last `RiskDecision`. `alerts` is ranked
  `ALERT` before `WARN` (stable within a band); `view.healthy` is `False` iff any
  `ALERT` is present.
- **Exposure valuation** reuses the A-034 mark fallback: explicit `marks` →
  `PositionRow.avg_price` (labelled `mark_is_cost_basis`) → `None` (no exposure
  shown). Cost-basis exposure on the dashboard is a display approximation, not a
  risk bound.

**Rationale:** A dashboard that is a pure function of (injected `now`, supplied
objects) is deterministic and trivially testable, matches the rest of the
codebase (no wall-clock, injected effects), and stays a strict observer — it
cannot perturb the pipeline it reports on. Reusing the existing value objects
keeps the seam thin: a new field to show is a one-line projection edit.

**Alternatives considered:** read the recorder DuckDB directly (rejected — the
recorder is write-only by D-016; replay/M2.3 already owns read-back, and the
dashboard would then couple to persistence and need I/O); a live-updating TUI /
web server (rejected — out of M3.1 scope and would add a dependency and a loop);
a dedicated socket-state enum in livebook (rejected — no evidence a real socket
layer exists yet; `FeedHealth.status` already carries disconnect / resync).

**Trade-offs / consequences:** the caller must gather and pass the current
objects each render — there is no polling or subscription. Display-only: no
alert is escalated anywhere, nothing is emailed / paged. Cost-basis exposure can
understate risk (A-034 / A-035). Real-money trading stays disabled (D-002).

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/dashboard/`,
`tests/test_dashboard.py`, `tests/dashboard_support.py`,
`docs/ASSUMPTIONS.md` A-035.

### D-021 — Failure testing is a modelled-scenario suite over existing seams; real defects are recorded separately

**Date:** 2026-09-07

**Decision:** M3.2 ships `tests/test_failure_scenarios.py` and no production
code. It is one section per `docs/ROADMAP.md` M3.2 failure category (venue
disconnects, stale prices, empty/malformed books, fee mismatch, partial/one-leg
fills, duplicate messages/orders, API timeout/rate limit, invalid contract
mapping, database/process restart). Each scenario:

- drives an **existing** seam or fake (`livebook` `LiveBookFeed` /
  `LiveBookConnection` + `FakeWebSocketTransport` / `FakeSnapshotSource`, the
  arbitrage engine, `PaperBroker`, `RiskManager`, `Recorder` / `ReplaySession`,
  the adapter `FakeTransport`s, the M3.1 dashboard) — no new production feature,
  no new dependency;
- injects one modelled failure (no network, no wall-clock, deterministic);
- asserts the **fail-closed contract** (trading disabled / rejection / raised
  error / no partial output) and the **designed recovery** where one exists
  (`begin_resync` → snapshot → HEALTHY; `LiveBookConnection.reconnect` backoff
  then `resync`; a fresh snapshot clearing STALE; a hedged observation clearing
  the unhedged timer).

**Anti-hallucination rule:** a modelled scenario that passes is *not* evidence
that the real venue behaves this way — it is evidence that our code fails closed
against the modelled input. Any **real defect** found while writing these tests
is recorded in `docs/PROJECT_JOURNAL.md` + `docs/ASSUMPTIONS.md` as a defect,
separately from the scenario, and not hidden inside a green test.

**Rationale:** the individual modules already have unit tests; M3.2's value is a
single auditable checklist that exercises each failure category end-to-end
across module boundaries (e.g. disconnect → feed health → risk veto → dashboard
alert) and pins the fail-closed guarantees so a future refactor cannot quietly
weaken them.

**Alternatives considered:** fault-injection wrappers / a chaos harness in
production code (rejected — adds surface area and a dependency for a
verification milestone; the injected-effect seams already allow every failure to
be scripted from a test); editing the existing per-module test files (rejected —
a dedicated file is the reviewable M3.2 deliverable and keeps the cross-cutting
scenarios in one place).

**Trade-offs / consequences:** some assertions overlap existing unit tests by
construction (the checklist must cover every category even where one module
already tests it). The suite proves fail-closed behaviour against *modelled*
inputs only; live venue semantics (A-001 family, A-012/A-013/A-015/A-016,
A-028/A-030) remain unverified and still block real-money use.

**Status:** ACTIVE.

**Evidence:** `tests/test_failure_scenarios.py`; result of this session — no
real defect discovered; `docs/ASSUMPTIONS.md` "M3.2 notes".

### D-022 — The paper-performance report is a pure read-only projection of one recording; missing metrics are `None`, never `0`

**Date:** 2026-09-07

**Decision:** M3.3 ships `prediction_market_arbitrage.perf_report`. No new
runtime dependency.

- `build_report(session, *, pnl_scope="portfolio", pnl_scope_id=None)` takes an
  M2.3 `ReplaySession` (the only read-back path for an M2.2 recording — the
  recorder is write-only, D-016) and returns an immutable `PerfReport`.
  `render_text(report)` renders a deterministic sectioned summary.
- Metrics: opportunities observed / positive-edge / rejected + rejection-reason
  histogram; mean/median/min/max **net edge** (total and per unit) over
  positive-edge rows; executable-quantity stats + depth-capped fraction;
  derived opportunity duration; paper-trade counts with fill / partial-fill
  rates and filled-quantity ratio; fill count / liquidity / fees; available
  depth from recorded order books (best and total size per side); paper PnL and
  **max drawdown** (largest peak-to-trough decline of the `realized + unrealized
  − fees` series for one scope).
- **`Stats`** carries `count` plus `mean/median/minimum/maximum` that are
  `None` when `count == 0`. A metric the recording cannot support is `None` and
  named in `PerfReport.unavailable`; a real `0` count / value stays `0`. The
  renderer prints `n/a` (with the reason) vs the number accordingly.
- **Opportunity duration is derived, not recorded.** The recorder stores
  discrete `OpportunityEvaluation` rows, not spans. An *episode* is a maximal
  run of consecutive positive-edge evaluations for one `pair_id` ordered by
  evaluation time; its duration is `last_eval_time − first_eval_time`. A
  single-observation episode carries no duration information and is counted
  separately (`single_observation_episodes`), never as duration `0`.
- **Leg-risk events are not persisted.** *(Superseded 2026-09-09 by D-027 — the
  recorder now has a `leg_risk_events` table and the report aggregates it.)* As
  originally shipped: the M2.2 schema had no leg-risk table (`LegRiskSnapshot`
  is an in-memory M2.4/M2.5 object), so `LegRiskStats.recorded` was always
  `False` and the report listed it under `unavailable`.
- Pure: no wall-clock, no persistence write, no order submission; imports the
  replay / recorder types only; nothing imports `perf_report`. `pnl_scope` is
  validated against `recorder.PNL_SCOPES` (bad scope → `PerfReportError`).

**Rationale:** a report that is a pure function of one `ReplaySession` is
deterministic and known-answer testable, reuses the existing read-back path
instead of touching DuckDB, and stays a strict observer. Making "missing" a
first-class `None` (not `0`) keeps an empty or partial recording from silently
reading as "0% fill rate, 0 drawdown".

**Alternatives considered:** read the DuckDB directly (rejected — duplicates
M2.3 and couples the report to persistence); add a leg-risk recorder table now
(rejected — out of M3.3 scope and needs an M2.4 producer that records it;
reported as unavailable instead); treat a single opportunity observation as a
zero-length episode (rejected — conflates "no duration data" with "instant
opportunity").

**Trade-offs / consequences:** opportunity duration is only as good as the
evaluation cadence in the recording, and an episode that never goes negative
before the recording ends is measured only up to its last positive eval.
Drawdown is computed on recorded PnL samples, not a continuous equity curve.
The report describes *paper* results only — positive paper PnL is not proof of
realised profit (ARBITRAGE_METHODOLOGY). Real-money trading stays disabled
(D-002).

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/perf_report/`,
`tests/test_perf_report.py`, `tests/perf_report_support.py`,
`docs/ASSUMPTIONS.md` "M3.3 notes".

### D-023 — The live-broker interface is a boundary + safety wrapper only; no venue operation is implemented (no primary evidence)

**Date:** 2026-09-07

**Decision:** M3.4 ships `prediction_market_arbitrage.live_broker` — the *shape*
of a live path plus its non-bypassable safety machinery, and **nothing that can
place a real order**. No new runtime dependency.

- **Venue-agnostic interface.** `LiveBroker` (ABC) defines `submit_order`,
  `cancel_order`, `get_order`, `get_positions` over venue-neutral value objects
  (`LiveOrderRequest` / `CancelRequest` / `LiveOrderAck` / `LiveOrderStatus` /
  `LivePosition` / `LiveOrderState`), deliberately close to the M2.4
  paper-broker types so a future live path is a drop-in behind the same
  strategy code. Every public method runs, in order: (1) input validation +
  `now` tz-check + venue-match; (2) `LiveTradingGate.assert_live_allowed`;
  (3) for `submit_order`, `IdempotencyGuard.register(client_order_id)`; then it
  delegates to a subclass `_do_*` hook. A subclass cannot skip the gate or the
  dedupe check.
- **The gate is off by default and cannot be armed by accident.**
  `LiveTradingGate` is a frozen dataclass; the default is disabled; the module
  constant `LIVE_TRADING_ENABLED` is `False`. Arming requires
  `LiveTradingGate(enabled=True, confirmation_phrase="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS")`
  — any other phrase (including `""`, `"1"`, `"true"`) raises
  `LiveTradingDisabledError` in `__post_init__`. `LiveTradingGate.from_env`
  arms **only** when `PMA_LIVE_TRADING` equals that exact string. There is no
  setter and no runtime toggle.
- **Idempotency safeguard at the boundary.** `IdempotencyGuard` is an
  in-memory, per-process record of submitted `client_order_id`s; a repeat raises
  `DuplicateOrderError` *before* any `_do_submit`. This is the **local** half of
  duplicate-order prevention only — whether a venue honours a client order key
  is unverified (no order-endpoint evidence), so a real deployment still needs
  venue-side dedupe.
- **Credentials are isolated + redacted.** `KalshiTradingCredentials` /
  `PolymarketUsTradingCredentials` are separate types with their **own** env
  vars (`KALSHI_TRADING_*` / `POLYMARKET_US_TRADING_*`), distinct from the M2.1
  market-data credentials; `repr` / `str` redact the secret.
- **Both venue adapters are explicitly unsupported.** `docs/API_SOURCES.md` has
  primary evidence for market data only (K-* / P-* are `/markets*` GETs + the
  market-data WebSocket). There is **no** captured or documented
  request/response shape for order placement, cancellation, order status, or
  positions on either venue. So `KalshiLiveBroker` / `PolymarketUsLiveBroker`
  raise `UnsupportedLiveOperationError` (naming the evidence gap and
  A-037/D-023) for every operation — even with an armed gate and credentials
  present. Nothing signs or sends.

**Rationale:** the ROADMAP M3.4 items are "Interface may exist" and
"LIVE_TRADING remains false by default". Both are now literally true, and the
grounding rule ("leave an operation explicitly unsupported/blocking rather than
inventing behavior") is honoured — the interface is ready to receive a
real implementation the day a venue's trading API is captured, without any
guessed paths, bodies, or field names in the repo now.

**Alternatives considered:** implement the venue REST calls from third-party
write-ups / SDK source (rejected — not primary evidence; violates the
anti-hallucination rule); a boolean `LIVE_TRADING` env flag (rejected — a bare
`=1` is exactly the "accidental activation" the milestone forbids; the awkward
phrase + frozen gate makes it deliberate); fold the gate into the M2.5 risk
manager (rejected — "no new risk logic"; the gate is an authorization boundary,
not a risk check, and the risk manager stays untouched).

**Trade-offs / consequences:** the package is non-functional by design — it
adds surface area for a capability that cannot yet be used. The idempotency
guard is process-local and does not survive a restart. Real-money trading stays
disabled (D-002); the Real-money gate items ("Live mode cannot activate
accidentally", "Duplicate-order prevention", "Credential isolation") are
*supported* by this boundary but not *verified* — verification needs a captured
trading API and a live reconciliation run.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/live_broker/`,
`tests/test_live_broker.py`, `tests/live_broker_support.py`,
`docs/API_SOURCES.md` (absence of any order-endpoint entry),
`docs/ASSUMPTIONS.md` A-037.

### D-024 — Observation fixtures are sanitised structure-first (allowlist), not key-name denylist

**Context:** the first cut of `scripts/observe_kalshi_demo.py` sanitised
captured responses with a **denylist**: it redacted a scalar only when its
*key name* was in a hard-coded set (`member_id`, `email`, …) or matched a
monetary-key heuristic. Everything else — numeric strings, portfolio values,
timestamps, tickers, client-order ids, and any field name not thought of in
advance — was written to `docs/evidence/kalshi-demo/*.json` verbatim. The demo
account was empty so nothing leaked, but a later non-empty account response
would have persisted account-sensitive scalars.

**Decision:** sanitisation is **structure-first / fail-safe**. `sanitise_body`
keeps object/array structure, every field *name*, the request path, HTTP
status and the whitelisted headers, and replaces **every** body scalar leaf
with a type token (`<number>` / `<redacted>`) unless its exact value is on a
short explicit allowlist of fixed non-account API constants
(`_ALLOWED_BODY_SCALARS`: the empty-string cursor plus fixed `error.code` /
`error.message` strings — `authentication_error`, `invalid_UUID`,
`deprecated_v1_order_endpoint`, `user_not_found`, … — but never
`error.details`, which can carry request-specific context).
`None` and booleans are treated as structural and kept. Unknown / future
fields are redacted by default. The committed Kalshi demo fixtures were
re-reduced by hand to this rule (no new network calls; no raw capture
retained). The allowlist is appended to as new fixed error constants are
actually OBSERVED (e.g. the 2026-09-08 order-lifecycle attempt added the two
create-endpoint error codes/messages).

**Alternatives considered:** extend the denylist (rejected — still fails open
on any unanticipated field, which is the exact defect); drop bodies entirely
and keep only key lists (rejected — loses the envelope/error-shape evidence the
K-TR-OBS rows depend on); allowlist by key *name* within known objects
(rejected — re-introduces name-based trust; a renamed or wrapper field slips
through).

**Trade-offs / consequences:** fixtures no longer show per-scalar types
(int vs string); the response-shape types stay recorded in the K-TR-OBS-10
prose row, observed at capture time. Any genuinely useful constant in a future
response must be added to the allowlist deliberately. Evidence classifications
are unchanged (K-TR-OBS rows stay OBSERVED).

**Status:** ACTIVE.

**Evidence:** `scripts/observe_kalshi_demo.py` (`_ALLOWED_BODY_SCALARS`,
`_redact_scalar`, `sanitise_body`),
`tests/test_observe_kalshi_demo_sanitiser.py`,
`docs/evidence/kalshi-demo/*.json`,
`scripts/observe_kalshi_demo_order_lifecycle.py` +
`docs/evidence/kalshi-demo/lifecycle/*.json` (reuses `sanitise_body`).

### D-025 — Same-market complete-set arbitrage is a registry-free method on the engine

**Date:** 2026-09-09

**Context:** the ROADMAP M1.5 bullet "Same-market complete-set logic" was the
last unchecked M1.5 item. Complete-set arbitrage buys one unit of **every**
mutually exclusive outcome of a *single* market on a *single* venue; exactly one
outcome settles to 1, so a matched set pays exactly 1 per unit and a set costing
< 1 (after fees + the execution buffer) is a locked-in edge. The existing
`evaluate` path is cross-venue: it requires a VERIFIED `MarketPairRecord`, whose
`kalshi` + `polymarket_us` legs are fixed and cross-venue by construction
(D-011). D-012 flagged complete-set as needing "a future registry extension or a
separate mechanism".

**Decision:** add `ArbitrageEngine.evaluate_complete_set(books, *,
evaluation_time, requested_quantity=None)` returning a new
`CompleteSetEvaluation`. It takes the outcome `OrderBook`s **directly** and uses
**no registry**:

- There is no equivalence question — the outcomes belong to one market, so
  "these N outcomes are the complete, mutually exclusive set" is a property of
  that market, not a cross-market mapping a human must verify. The caller
  asserts it by which books it supplies (A-039); the engine verifies only that
  the books share one venue+market and name distinct contracts, and that there
  are ≥ 2.
- Everything else reuses the `evaluate` conventions unchanged: exact `Decimal`
  (no internal rounding), `_walk_asks` depth-walking, `executable_quantity =
  min(ask depth over every outcome, `max_quantity`, `requested_quantity`)`,
  injected `FeeModel` summed per outcome, the same optional freshness guards
  (`max_book_age`, `max_cross_book_skew` — the latter as `max − min` timestamp
  across all books), `require_full_fill`, and `execution_buffer_per_unit`.
  Exact break-even is not an opportunity.
- `CompleteSetEvaluation.to_opportunity()` is defined only for a **binary**
  set (exactly 2 outcomes → a domain `MarketPair`); a categorical (> 2) set
  raises rather than distorting `MarketPair`.

**Alternatives considered:** extend `MarketPairRecord` / the registry to hold a
same-venue outcome group (rejected — invents review-workflow infra for a case
with no equivalence question; the registry's whole purpose is the human
cross-venue equivalence gate, D-006/D-011); overload `evaluate` with an
optional "complete set" mode (rejected — the 2-leg `OpportunityEvaluation`
result type and the `record` parameter do not fit N outcomes); a standalone
function outside `ArbitrageEngine` (rejected — it needs the same
`EngineConfig`).

**Trade-offs / consequences:** the engine now has two entry points with two
result types. `evaluate_complete_set` cannot verify outcome-set exhaustiveness
from `OrderBook`s alone — a caller that passes a non-exhaustive subset gets a
wrong "guaranteed 1 at settlement" premise (A-039). This does **not** touch the
cross-venue path, the registry, live execution, or the recorder. It does not
implement a slippage reserve (still a separate open item); it reuses the
existing `execution_buffer_per_unit` knob only.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/arbitrage/engine.py`
(`evaluate_complete_set`, `CompleteSetEvaluation`, `_complete_set_freshness`,
`_leg_shell_from_book`), `tests/test_arbitrage_complete_set.py`,
`docs/ARBITRAGE_METHODOLOGY.md` §"Same-market complete-set", `docs/ASSUMPTIONS.md`
A-039.

### D-026 — Slippage reserve is a separate engine knob, not folded into the execution buffer

**Date:** 2026-09-09

**Context:** the last unchecked ROADMAP M1.5 item was "Slippage reserve". The
engine already had `EngineConfig.execution_buffer_per_unit`, a per-matched-set
Decimal subtracted from the edge, but `docs/ARBITRAGE_METHODOLOGY.md` and the
2026-09-09 roadmap reconciliation deliberately treated "execution buffer"
(a general safety margin) and "slippage reserve" (the assumed adverse price
move between the depth-walked decision price and the real fill) as **different**
concepts, so the item stayed open.

**Decision:** add `EngineConfig.slippage_reserve_per_unit: Decimal = _ZERO`
(validated finite `>= 0`, same as the execution buffer) as a **peer** knob, not
a rename or a fold-in. Both `evaluate` and `evaluate_complete_set` compute
`slippage_reserve = slippage_reserve_per_unit * executable_quantity` and add it
to `net_total_cost` alongside fees and the execution buffer;
`net_edge = size - net_total_cost`; opportunity iff `net_edge > 0` (exact
break-even still not an opportunity). Both `OpportunityEvaluation` and
`CompleteSetEvaluation` gain a `slippage_reserve` field so the audit trail shows
which friction consumed the edge. `0` (the default) reproduces the pre-reserve
result byte-for-byte.

**Alternatives considered:** rename `execution_buffer_per_unit` to
`slippage_reserve_per_unit` (rejected — loses the distinct "general margin"
concept and silently changes the meaning of a shipped, recorded field); fold
slippage into the reported `execution_buffer` value (rejected — the audit trail
should separate the two frictions, matching how fees are already their own
field); make the reserve a fraction of acquisition cost rather than per-unit
(rejected — the per-unit shape mirrors `execution_buffer_per_unit` exactly, is
the smallest change, and keeps every test's arithmetic trivially exact).

**Trade-offs / consequences:** the `recorder` `opportunities` table has an
`execution_buffer` column but no `slippage_reserve` column — a recorded row's
`net_total_cost` / `net_edge` include the reserve, but the reserve component
alone is not separately columned (the same limitation as per-leg fees). Adding
a column is a versioned recorder-schema change, out of scope here and not
required by any existing interface (`record_opportunity` reads a fixed field
list). The reserve is a caller-chosen parameter with no venue-microstructure
backing (**A-040**); it does not change `LIVE_TRADING`, adapters, the paper
broker, or any execution behaviour.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/arbitrage/engine.py`
(`EngineConfig.slippage_reserve_per_unit`, `slippage_reserve` on both result
types, both `evaluate*` methods), `tests/test_arbitrage_engine.py` +
`tests/test_arbitrage_complete_set.py` (slippage-reserve sections),
`docs/ARBITRAGE_METHODOLOGY.md` §2.

### D-027 — Leg-risk events are recorder-backed via an additive table (no schema-version bump)

**Date:** 2026-09-09

**Context:** the last unchecked ROADMAP M3.3 item was "Leg-risk events". D-022
deferred it because the M2.2 recorder had no table for one-legged exposure, so
`build_report` reported it as permanently unavailable (D-022 / A-036). The
paper broker already *produces* the measurement: `PaperBroker.leg_risk(a, b, …)`
returns a `LegRiskSnapshot` with `unhedged_quantity = a_filled − b_filled`; when
that is non-zero the pair is one-legged (temporary if a leg is still working,
unresolved if both orders are terminal).

**Decision:**

1. **Recorder** — a new append-only `leg_risk_events` table + `seq_leg_risk_events`
   sequence, a `LegRiskEventRow` value-object, and
   `Recorder.record_leg_risk_event(row, *, recorded_at)`. `LegRiskEventRow`
   **fails closed**: `unhedged_quantity == 0` raises — a balanced measurement is
   not an event, so the metric can never be padded with synthetic zeros.
   `LegRiskSnapshot.to_leg_risk_event_row()` (guarded by
   `LegRiskSnapshot.is_leg_risk_event`) is the producer bridge; the recorder
   imports no paper-broker code (dependency stays paper_broker → recorder).
   `record_leg_risk_event` is **idempotent per transition**: the new table has
   `UNIQUE (session_id, order_a_id, order_b_id, as_of)` and the insert is
   `ON CONFLICT DO NOTHING`, so a paper-run loop that samples the same
   `leg_risk(a, b, as_of=…)` snapshot twice records one row and gets the stored
   id back — a re-observation cannot inflate the report's event counts. (A
   later `as_of` for the same pair is a genuinely new observation and a new
   row.) This is the only recorder stream with a natural-key constraint,
   because it is the only one that is *counted as discrete events* by a
   downstream report and whose producer (`leg_risk`) is a re-callable query,
   not a per-object emit like fills / order events.

   **No automatic orchestration.** As with every other M2.4 → M2.2 artifact
   (order events, fills, positions — D-016 / D-018), nothing in `src/` wires a
   `PaperBroker` to a `Recorder`; `PaperBroker` holds no recorder and emits no
   rows. The integration is the standard pair of a conversion helper on the
   producer object (`Fill.to_row()`, `Order.event_rows()`, and now
   `LegRiskSnapshot.to_leg_risk_event_row()`) plus a `record_*` method the
   caller's run loop invokes. Adding an auto-recording runtime for leg risk
   alone would be inconsistent and a new runtime component — out of M3.3 scope;
   M3.3 "Leg-risk events" is satisfied on the same basis as the checked
   "Paper trades" / "Paper PnL" items: the report deterministically aggregates
   the recorded stream when it is present.
2. **`SCHEMA_VERSION` stays `1`.** Every table is `CREATE TABLE IF NOT EXISTS`,
   so re-opening an older recording with the new build additively creates the
   missing table; the version number tracks the *column shape of existing
   tables*, which is unchanged. A read-only consumer (`ReplaySession`) that
   opens a recording written before the table existed detects its absence
   (`has_leg_risk_stream()` → `False`) and yields an empty `leg_risk_events()`
   stream; `build_report` then lists leg-risk under `unavailable` (unchanged
   "missing ≠ zero" behaviour). A modern recording with the table but no rows
   reports `recorded=True, events=0` — a **real** zero.
3. **Replay / report** — `ReplaySession.leg_risk_events()` +
   `RecordedLegRiskEvent` + a `leg_risk` timeline kind; `perf_report`'s
   `LegRiskStats` gains `events` / `temporary_events` / `unresolved_events` /
   `order_pairs_affected` / `max_abs_unhedged_quantity` / `unhedged_notional`
   (a `Stats` over the priced events), all exact `Decimal`.

**Alternatives considered:** bump `SCHEMA_VERSION` to 2 (rejected — the recorder
has *no* migration path, so every existing v1 recording would be refused by both
`Recorder` and `ReplaySession`; the task requires preserving existing-data
compatibility, and `IF NOT EXISTS` already *is* the project's additive-change
mechanism); write leg-risk events into an existing table such as `health_events`
(rejected — different entity, wrong columns); have `build_report` recompute leg
risk from recorded fills/orders (rejected — the broker's `leg_risk` pairing is
caller-driven and not recoverable from fills alone; that would invent events).

**Trade-offs / consequences:** the recorder is **not** redesigned — one new
table, one new writer, following every existing convention (append-only,
`str(Decimal)` VARCHAR, naive-UTC `TIMESTAMP`, per-table sequence id,
`isinstance` guard). A recording is only as complete as the caller's decision
to *call* `leg_risk` and record the result; the recorder does not sample
exposure on its own. D-022's "leg-risk unavailable" and A-036's "not persisted"
are superseded for a recording made by this build; a pre-D-027 recording is
still read correctly (unavailable, not an error).

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/recorder/` (`schema.py`
`leg_risk_events`, `models.LegRiskEventRow`, `recorder.record_leg_risk_event`),
`paper_broker/models.py` (`LegRiskSnapshot.is_leg_risk_event` /
`to_leg_risk_event_row`), `replay/` (`RecordedLegRiskEvent`,
`ReplaySession.leg_risk_events` / `has_leg_risk_stream`), `perf_report/`
(`LegRiskStats`, `_leg_risk_stats`), `tests/test_leg_risk_events.py`,
`tests/test_recorder.py`, `tests/test_paper_broker.py`, `tests/test_perf_report.py`.

### D-028 — `WebsocketsTransport` releases its connection handle when a connection surfaces as `TransportClosed`, so the runtime's reconnect path works against a real socket

**Date:** 2026-09-09

**Context — the exact defect:** the first production run of the live-book
runtime (`scripts/observe_kalshi_livebook_runtime.py`, driving the shipped
`LiveBookConnection` + `LiveBookFeed` + `WebsocketsTransport`) crashed in
`LiveBookConnection.reconnect()`. Sequence:

1. The socket dropped; the next `LiveBookConnection.pump_one()` →
   `WebsocketsTransport.receive()` → `websockets` `recv()` raised
   `ConnectionClosed`, which `receive()` re-raised as `TransportClosed`.
2. `receive()` did **not** clear `self._conn` / `self._cm` on that path — only
   `close()` cleared them, and the manager's recovery loop
   (`handle_disconnect()` → `reconnect()`) never calls `close()`.
3. `reconnect()` → `connect_and_subscribe()` → `WebsocketsTransport.connect()`,
   whose first line is `if self._conn is not None: raise LiveBookError(
   "WebsocketsTransport.connect called while already connected")`. → crash.

The `reconnect()` path over the concrete transport had never been exercised —
the M2.1 loopback test stopped at `handle_disconnect()`.

**Decision (smallest fix — transport only):**

1. Add a private `WebsocketsTransport._release()` that clears `_conn` / `_cm`
   (best-effort `cm.__exit__`, swallowing `ConnectionClosed` / `OSError` /
   `TimeoutError` — the abrupt-drop cleanup was observed to raise
   `TimeoutError: timed out while closing connection`). `close()` now delegates
   to it (behaviour unchanged).
2. `receive()` calls `_release()` on the two paths that already raised
   `TransportClosed` — `ConnectionClosed` (the observed defect) and
   `TimeoutError` (the class docstring already says a recv timeout means "the
   connection is then unusable and the manager reconnects", i.e. the same
   defect, second trigger). `send()` calls `_release()` on its `ConnectionClosed`
   path for the same reason (`connect_and_subscribe` calls `send` right after
   `connect`, inside the reconnect retry loop). `TimeoutError` is caught before
   `ConnectionClosed` and keeps its distinct `recv_timeout` message.
3. **Not** broadened: `receive()` / `send()` do **not** catch bare `OSError`.
   An earlier draft did; a deterministic test that kills the raw socket under a
   real loopback connection
   (`test_abrupt_underlying_socket_drop_surfaces_as_transport_closed_and_releases`)
   confirms `websockets` `recv()` surfaces the drop as `ConnectionClosed` (the
   socket I/O is on its background reader thread), so `OSError` was dead code
   beyond the observed defect and was removed.
4. `LiveBookConnection` is **unchanged** — once a connection has surfaced as
   `TransportClosed` the socket is unusable, so the handle must be dropped and a
   later `connect()` allowed to open a fresh one. This is the transport half of
   the connect → subscribe → pump → `mark_disconnected` → reconnect → REST
   resync flow the manager already implements. No credential, execution, order,
   balance, or fund-moving behaviour is touched.

**Status:** ACTIVE.

**Evidence:** `src/prediction_market_arbitrage/livebook/ws_transport.py`
(`_release`, `_release()` calls on `ConnectionClosed` / `TimeoutError`);
`tests/test_livebook_ws_transport.py`
(`test_closed_connection_is_released_so_reconnect_works` — pins the pre-fix
"already connected" failure is gone;
`test_abrupt_underlying_socket_drop_surfaces_as_transport_closed_and_releases` —
the raw-socket-kill path the harness uses;
`test_live_book_connection_reconnects_and_resyncs_over_real_transport` — the full
drop → `DISCONNECTED` → reconnect → resync → `HEALTHY` lifecycle over a real
socket, healthy only after resync); production run
`docs/evidence/kalshi-live/livebook-runtime/SUMMARY.json`
(`E_recover/reconnected`, `reconnect_attempts: 0`); `docs/API_SOURCES.md`
K-LB-OBS-12.

### D-029 — A `pump_one()`-based consumer cannot observe the `STALE` verdict on a quiet market; recorded as a known gate-#7 gap, not fixed

**Date:** 2026-09-09

**Context.** Real-money gate #7 ("Stale-data handling") calls for observing a
**natural** `HEALTHY → STALE → HEALTHY` lifecycle on a live feed — a real quiet
spell longer than `LiveBookFeed.max_staleness` (30 s) followed by a genuine new
`orderbook_delta` — while the consumer keeps running and downstream health
gating rejects the stale book. A bounded read-only production pass
(`scripts/observe_kalshi_livebook_runtime.py --observe-stale`, which **never**
pauses consumption) could not capture it. Two independent reasons
(`docs/API_SOURCES.md` K-LB-OBS-16 / K-LB-OBS-17):

1. **Runtime shape.** `LiveBookConnection.pump_one()` calls
   `WebsocketsTransport.receive()`, which **blocks** until the next data frame.
   On a quiet market there is no intervening traffic, so a continuously
   consuming caller cannot sample `LiveBookFeed.health()` *during* the gap — it
   regains control only when the next delta arrives, which immediately restores
   `HEALTHY`. The transitional `STALE` verdict is real and computed correctly
   (deterministic tests; K-LB-OBS-07 on the live feed) but is invisible to this
   consumer. Separately, `WebsocketsTransport.recv_timeout` turns a
   quiet-but-alive socket into `TransportClosed` + a full reconnect, conflating
   "quiet market" with "dead connection".
2. **Market availability.** Kalshi's public `GET /markets?status=open` (no
   series filter) is dominated by empty-book `KXMVECROSSCATEGORY-SHARD1-*`
   markets; the only reliably two-sided live markets found are the crypto
   hourly series, which update many times per second and never approach a 30 s
   gap (observed: `max_pump_gap_s = 6.685` over ~90 s, 400 deltas,
   `empty_pumps = 0`).

**Decision.** Do **not** change the runtime for this. Adding a non-fatal
idle/poll path to the transport, or a concurrent health-sampling thread, is a
runtime feature beyond an observation milestone and is not required by any
shipped consumer today (M2.1's `run_forever` reconnects on `TransportClosed`,
which is acceptable for a venue that pings every ~10 s — a true >`recv_timeout`
silence *is* a dead connection for the crypto markets in use). Gate #7 stays
**unchecked**. The observation harness keeps the `--observe-stale` mode
(continuous consumption, fail-closed-accessor sampling, `SUMMARY_STALE.json`
blocker artifact) so the lifecycle can be captured later given either a curated
quiet-market ticker with 30–150 s inter-delta gaps, or a future transport
idle/poll capability.

**What is NOT claimed.** This is not a statement that stale handling is broken —
`LiveBookFeed` fails closed on staleness correctly. It is a statement that the
**natural end-to-end lifecycle** has not been OBSERVED in production, so the
gate cannot be checked on evidence.

**Status:** ACTIVE (accepted gap).

**Evidence:** `scripts/observe_kalshi_livebook_runtime.py`
(`watch_staleness_lifecycle`, `run_stale_observation`);
`tests/test_observe_kalshi_livebook_runtime.py`
(`test_watch_staleness_lifecycle_sees_natural_stale_then_recovery`,
`test_watch_staleness_lifecycle_reports_inconclusive_on_transport_close`);
`docs/evidence/kalshi-live/livebook-runtime/SUMMARY_STALE.json`;
`docs/API_SOURCES.md` K-LB-OBS-16 / K-LB-OBS-17.

### D-030 — A Kalshi **DEMO-only** execution orchestrator (`demo_execution`), host-pinned; production trading stays disabled

**Date:** 2026-09-10

**Context.** The remaining real-money-gate evidence (#3 real paper execution end
to end, #4 fee reconciliation against a real fee line, #6 real partial fills,
#10 authenticated order/position/fill reconciliation) all need a *real venue
round-trip* that the shipped `live_broker` package deliberately cannot do
(D-023 / A-037 — no **production** order endpoint has primary evidence). The
Kalshi **demo** order endpoints, by contrast, *are* evidence-backed
(K-TR-04..10) and now OBSERVED end to end on demo shard 1 (K-TR-OBS-26..33). So
the safe next step is a demo-only path that composes the existing components.

**Decision.** Add `prediction_market_arbitrage.demo_execution` — a *composition*
layer, not a redesign:

- **`KalshiDemoLiveBroker(live_broker.LiveBroker)`** — the first concrete
  `LiveBroker` with implemented `_do_*` hooks. It maps the K-TR-05 create body /
  K-TR-06 + K-TR-08 responses to the existing venue-neutral value objects over
  an injected **`DemoTransport`** seam (no networked implementation ships — same
  posture as `livebook`'s socket, D-015). It calls
  **`transport.assert_demo_host`** at construction: any production Kalshi host
  marker, any non-`demo.kalshi.co` host, or a non-`https` URL is a hard
  `DemoHostError`. It still runs *through* the unchanged `LiveTradingGate` +
  `IdempotencyGuard` wrapper (`interface.LiveBroker`), so an unarmed gate fails
  closed and a reused `client_order_id` never re-submits; a venue-side `409`
  (K-TR-07) is surfaced as `DuplicateOrderError`.
- **`DemoExecutionOrchestrator`** — accepts an already-approved
  `LiveOrderRequest`, records it (`OrderEventRow` status `new`), runs the
  **unchanged** `RiskManager.evaluate_order` (kill switch, position, order-size,
  exposure, daily-loss, data-freshness/health, minimum edge — every configured
  check, fail-closed), and **only on approval** submits through the demo broker;
  a rejection records `rejected` with the reasons and never touches the venue.
  `cancel` and `reconcile` are explicit follow-up steps. `reconcile` reads venue
  order status + positions and records the resulting local state, failing closed
  (`DemoCapabilityError`) on any missing / ambiguous field. Everything is
  deterministic except the injected `DemoTransport` calls and `clock`.

**Why not extend `KalshiLiveBroker`:** that class is, by D-023, a boundary with
*no* implemented operation because no **production** endpoint has evidence.
Keeping the demo implementation in a separate, host-pinned package preserves
that invariant exactly — `KalshiLiveBroker` still raises
`UnsupportedLiveOperationError` for everything.

**Why not a recorder schema change:** the order lifecycle (intent → submit →
cancel → reconcile) maps onto the existing `OrderEventRow` statuses + `reason`
field and `record_position`; the full `RiskDecision` and raw venue body live in
the orchestrator's returned `ExecutionOutcome` / `to_evidence_dict()`, not in
the typed recorder. No new table, no schema-version bump.

**Safety boundary.** DEMO host only (hard-fail otherwise); no production
credential path (the demo credential/signing is a script concern, unchanged
`observe_kalshi_demo*`); the production read-only WS credential path
(`livebook` / `scripts/kalshi_signer` prod) is untouched; `LIVE_TRADING` is
never read or set; no Polymarket US execution; no fund movement. **No network
call is made by this milestone** — the concrete `DemoTransport` and the first
actual demo order are a separate, explicitly-gated observation step.

**Status:** ACTIVE. Does **not** by itself complete any real-money gate —
offline tests prove the orchestration contract; the gate evidence needs the
demo observation run.

**Evidence:** `src/prediction_market_arbitrage/demo_execution/`;
`tests/test_demo_execution.py`; `tests/demo_execution_support.py`;
`docs/API_SOURCES.md` K-TR-04..10 / K-TR-OBS-26..33; `docs/ASSUMPTIONS.md`
A-037 (unchanged — it governs the *production* boundary).

### D-031 — Concrete Kalshi DEMO REST transport (stdlib `urllib` + injected signer + injected HTTP seam) and an unrun observation harness

**Date:** 2026-09-10

**Context.** D-030 shipped the demo orchestrator with `DemoTransport` as a bare
seam. To produce the #3/#4/#6/#10 evidence a real demo round-trip is needed —
but without a new runtime dependency, without a networked call in the test
suite, and without touching the production credential path.

**Decision.** Add `demo_execution.rest_transport`:

- **`KalshiDemoRestTransport(DemoTransport)`** — standard library `urllib` only.
  It builds the K-TR-03 signed string `timestamp_ms + METHOD + "/trade-api/v2" +
  path` (path **without** query) and the three K-TR-02 auth headers; the RSA-PSS
  signature comes from an **injected `livebook.Signer`** (the concrete openssl
  signer stays in `scripts/kalshi_signer` — this package still imports no
  crypto). The HTTP call itself is behind an **injected `HttpSender`** seam
  (`urllib_sender` is the default), so every test runs offline.
- Host-pinned: `assert_demo_host(base_url)` at construction — a production host
  is a hard `DemoHostError` before any request is built.
- **Fail-closed parsing:** a non-JSON / non-object body becomes `{}` (the broker
  then refuses a 2xx create with no `order_id`); a transport/timeout error is a
  `DemoTransportError` carrying only method + path + exception *class* — never
  the URL host, headers, key id, signature, or the underlying message. Non-2xx
  HTTP statuses (401/409/429/5xx) flow through as a `DemoResponse` for the
  broker's existing mapping (409 → `DuplicateOrderError`).

- **`scripts/observe_kalshi_demo_execution.py`** — a bounded observation harness
  (env-guarded `PMA_KALSHI_DEMO_EXECUTE=1` + `--observe`; `--check` default
  makes **no** network call). It selects one liquid demo market (read-only
  `KalshiMarketDataAdapter` on the demo base), submits **one 1-contract** limit
  bid at the best ask (max notional ≈ `--max-price`, default $0.60) through the
  orchestrator, observes / reconciles / cancels any remainder, fetches
  fills/positions, compares venue vs local recorded state, and writes sanitised
  evidence (`observe_kalshi_demo.sanitise_body`, D-024). **It is not run in this
  milestone.**

**Status:** ACTIVE. Still completes no real-money gate — the harness must be run
once against Kalshi demo to produce the evidence.

**Evidence:** `src/prediction_market_arbitrage/demo_execution/rest_transport.py`;
`tests/test_demo_rest_transport.py`; `scripts/observe_kalshi_demo_execution.py`;
`docs/API_SOURCES.md` K-TR-01..14.

### D-032 — The demo market-selection diagnostic is read-only and never recommends *raising* `--max-price`

**Date:** 2026-09-10

**Context.** The first bounded demo `--observe` (D-031 harness) exited safely
with "no open demo market with a two-sided book and best ask <= 0.60". Before
retrying, an operator needs to know *why* the picker
(`pick_liquid_demo_market`) found nothing and whether a different `--max-price`
would help — without loosening any bound or touching the order path.

**Decision.** Add a `--diagnose` mode to
`scripts/observe_kalshi_demo_execution.py`:

- **Read-only, credential-free.** Public `GET /markets*` on the demo host only
  (`KalshiClient` + `KalshiMarketDataAdapter`, the same code the picker uses).
  No preflight, no signer, no order, no cancel, no evidence file, no production
  host, `LIVE_TRADING` never referenced.
- **Reports exactly the picker's inputs** per open demo market: ticker, venue
  `status`, YES best bid / best ask, two-sided?, level count per side, size at
  best ask, and pass/fail against the picker rule at the supplied
  `--max-price`. `MIN_BOOK_DEPTH = 2` is now a shared constant so the picker
  and the diagnostic cannot drift.
- **`recommend_max_price` is advisory only and asymmetric.** It may report the
  *tightest already-satisfiable* bound (the cheapest two-sided best ask that is
  `<= current --max-price`, exact, no rounding). When the cheapest two-sided
  best ask is *above* the current bound it returns `None` and only cites that
  number in the reason string — a `--max-price` **increase is never surfaced as
  a recommendation**, because widening the risk bound is an operator decision,
  and the script never applies the value regardless. When no market has a
  two-sided book it returns `None` ("raising `--max-price` cannot help").

**Status:** ACTIVE. Completes no real-money gate; changes no picker behaviour.

**Evidence:** `scripts/observe_kalshi_demo_execution.py` (`run_diagnostic`,
`assess_candidate`, `recommend_max_price`);
`tests/test_observe_kalshi_demo_execution.py`; PROJECT_JOURNAL 2026-09-10
entry with the first OBSERVED demo scan.

### D-033 — Bounded Demo execution requires an explicit operator-authorized ticker

**Date:** 2026-09-10

**Context.** A paginated read-only diagnostic found an eligible Demo market
outside the first discovery page. The first authorized bounded attempt then
failed closed because `--observe` had no target argument and always used the
non-paginated discovery picker. Changing discovery order or silently choosing a
different market would not preserve the operator's authorization.

**Decision.** Require exactly one `--ticker KX...` argument for `--observe`.
The execution harness retrieves that exact ticker from the Demo market endpoint,
requires the response ticker to match and status to be `active`, obtains its
current YES book, and applies the existing `assess_candidate` criteria before
loading execution credentials or constructing an authenticated client. Explicit
selection authorizes evaluation only; it does not bypass the unchanged
`--max-price 0.60` default, two-sided-book and two-level depth requirements,
one-contract limit, position/risk/duplicate checks, Demo host guard, or
cancellation/reconciliation behavior. Missing, repeated, blank, unavailable,
mismatched, inactive, or ineligible targets fail closed before submission.

The existing discovery picker and read-only paginated diagnostic remain
unchanged and available for candidate discovery. This milestone makes no
network call and submits no order.

**Status:** ACTIVE. Completes no real-money gate; the explicit-target Demo
execution still requires a separately authorized observation.

**Evidence:** `scripts/observe_kalshi_demo_execution.py`;
`tests/test_observe_kalshi_demo_execution.py`; PROJECT_JOURNAL 2026-09-10
explicit-target milestone entry.

## Documentation rule going forward

For every material architectural, trading, risk, testing, or data-model decision, record the decision here before or alongside implementation. The entry should be understandable to someone reviewing the repository months later without access to the original ChatGPT or Claude conversation.

When a decision changes, do not silently rewrite history. Mark the old decision as superseded and add a new decision explaining why the project changed direction.
