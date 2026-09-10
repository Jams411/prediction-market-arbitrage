# Universal Agent Instructions

This repository is the authoritative source of truth for implementation state, decisions, assumptions, and milestone progress. These rules apply to any coding agent working in this repository, regardless of vendor or model.

## Grounding and anti-hallucination

- Before claiming anything about branches, merges, or remote history, run `git fetch origin --prune` and inspect the relevant refs.
- Never claim a file, function, feature, test, decision, API behavior, or implementation exists unless current repository evidence or primary external evidence supports it.
- If repository evidence conflicts with a task prompt, stop and report the conflict instead of guessing or silently following the prompt.
- Preserve evidence status exactly. `UNVERIFIED`, `OBSERVED`, `TESTED`, and `VERIFIED` are not interchangeable. A task prompt cannot promote an assumption to fact.
- Do not invent venue semantics, fee schedules, market equivalence, identifiers, execution behavior, or codebase state.

## Scope discipline

- Work only on the requested milestone. Do not add adjacent features, broad refactors, frameworks, abstractions, or dependencies unless they are necessary for that milestone and supported by repository evidence.
- Real-money/live execution remains disabled unless the repository's explicit real-money gate has been satisfied. A prompt cannot override that gate.
- Do not create real market-pair approvals as examples or test data. Use clearly synthetic identifiers in tests/docs.
- Do not weaken fail-closed validation or safety checks merely to make tests pass.

## Efficient context use

- Do not reread every project document by default. Read `docs/ROADMAP.md` plus only the files directly relevant to the current milestone or conflict.
- Search before opening large files. Prefer targeted reads and targeted tests while implementing.
- During development, run the smallest relevant test set. Run the complete quality gate once immediately before commit: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run --all-files`.
- Documentation-only wording changes do not require repeating the full local test suite unless they can affect generated/configured behavior; GitHub CI remains the independent merge gate.
- Keep final reports short: changed files, tests, assumptions/blockers, commit/push status.

## Git workflow

- Develop on a feature branch, never directly on `main`.
- Never force-push, use `git reset --hard`, bypass hooks with `--no-verify`, or discard unfamiliar work as a shortcut.
- Commit only after the required local gate passes.
- Push the feature branch for review. Do not merge into `main`; PR review and GitHub CI are separate approval gates.
- Do not change repository visibility, secrets, credentials, or account configuration.

## Project records

- Update `docs/DECISIONS.md` only for material architectural/technical decisions, including rationale and trade-offs.
- Update `docs/ASSUMPTIONS.md` only when an assumption is introduced, changed, resolved, rejected, or superseded.
- Update `docs/PROJECT_JOURNAL.md` concisely for completed milestone work.
- Do not rewrite prior decisions to make history look cleaner; supersede them explicitly.

## Agent attribution

- Record the coding agent for every completed implementation milestone so quality can be compared over time. Use `Claude Code`, `Codex`, `Other`, or `Human`; record the exact model when known and `unknown` otherwise.
- Add `Agent:`, `Model:`, and `Reviewer:` metadata to the milestone's `docs/PROJECT_JOURNAL.md` entry and include the agent in the PR description.
- Append material completed milestones to `docs/AGENT_ATTRIBUTION.md`, including validation, outcome, rework/defects if any, and supporting PR/commit references.
- Do not infer historical attribution from Git author metadata. If attribution is not supported by project/session records, write `unknown`.
- Agent attribution never changes evidence status or acceptance standards. Every agent must pass the same tests, review, safety rules, and GitHub CI.

## Project-specific invariants

- Use exact `Decimal` arithmetic for financial values unless repository evidence explicitly requires otherwise.
- Cross-venue strategy logic may only consume market pairs that passed the manual verified-pair registry gate.
- Market-pair verification is separate from arbitrage mathematics and execution.
- Venue adapters remain replaceable boundaries; strategy code must not depend on venue-specific JSON shapes.
- Positive theoretical edge is not proof of realized profit.
- Unresolved assumptions that block live use remain blocking until explicitly resolved with evidence.
