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

## Documentation rule going forward

For every material architectural, trading, risk, testing, or data-model decision, record the decision here before or alongside implementation. The entry should be understandable to someone reviewing the repository months later without access to the original ChatGPT or Claude conversation.

When a decision changes, do not silently rewrite history. Mark the old decision as superseded and add a new decision explaining why the project changed direction.
