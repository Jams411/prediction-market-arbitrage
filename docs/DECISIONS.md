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

## Documentation rule going forward

For every material architectural, trading, risk, testing, or data-model decision, record the decision here before or alongside implementation. The entry should be understandable to someone reviewing the repository months later without access to the original ChatGPT or Claude conversation.

When a decision changes, do not silently rewrite history. Mark the old decision as superseded and add a new decision explaining why the project changed direction.
