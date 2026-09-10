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
