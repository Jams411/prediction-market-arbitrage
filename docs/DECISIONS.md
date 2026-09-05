# Decision Log

Record architectural and methodological decisions here so they are not reconstructed from AI memory.

## Format

Each decision should include:

- ID
- date
- decision
- rationale
- alternatives considered
- status
- evidence or references

## Active decisions

### D-001 — Repository is the source of truth

**Decision:** Version-controlled repository documentation and tested code override chat history, Notion notes, and AI memory when conflicts exist.

**Status:** ACTIVE

### D-002 — Private-first development

**Decision:** Keep the repository private during development and paper testing. Review secrets, history, licensing, and documentation before any public release.

**Status:** ACTIVE

### D-003 — Modular adapter architecture

**Decision:** Keep venue-specific connectivity behind replaceable interfaces. Core arbitrage, normalization, risk, and analytics logic remain project-owned.

**Status:** ACTIVE

### D-004 — Deterministic core

**Decision:** LLMs do not participate in market-state maintenance, arbitrage arithmetic, risk approval, fill determination, or autonomous order decisions.

**Status:** ACTIVE

### D-005 — Decimal monetary arithmetic

**Decision:** Monetary values and prices use decimal arithmetic rather than binary floating point unless a verified external interface requires conversion at a boundary.

**Status:** ACTIVE

### D-006 — Manual contract pairing first

**Decision:** Initial cross-venue market pairs require explicit human verification of resolution terms. Semantic/LLM matching is deferred.

**Status:** ACTIVE
