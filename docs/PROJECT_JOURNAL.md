# Project Journal

Use this file as the concise chronological record of milestone progress, evidence, blockers, and decisions that matter to future work.

## 2026-09-05 — Project initialization

- Created `Jams411/prediction-market-arbitrage`.
- Changed repository visibility to private during development.
- Established GitHub repository documentation and tested code as the authoritative source of truth.
- Adopted evidence labels: VERIFIED, OBSERVED, TESTED, ASSUMPTION, UNKNOWN.
- Adopted modular adapter architecture so external venue clients and third-party components can be replaced without rewriting the core.
- Confirmed live trading remains disabled during initial build and paper testing.
- Began Milestone 0.1 documentation baseline.

## 2026-09-05 — M1.1 Domain models

- Implemented normalized, venue-neutral domain models in
  `src/prediction_market_arbitrage/domain/`: Venue, Market, Contract, PriceLevel,
  OrderBook, MarketPair, Opportunity.
- All models are frozen dataclasses that validate their invariants at
  construction: non-empty identifiers, timezone-aware timestamps, probability
  prices in `[0, 1]`, strictly positive quantities/edge, ordered and
  duplicate-free order-book sides, and rejection of truly crossed books.
- Decimal discipline (D-005): models require an explicit `Decimal`; `float`,
  `bool`, and non-finite values are rejected, never coerced. `to_decimal` is
  provided for adapter/parsing boundaries (M1.2+).
- Locked order books (best bid == best ask) are accepted as a valid transient
  state; only crossed books (best bid > best ask) are rejected. See A-005.
- Introduced assumptions A-004..A-007 in `ASSUMPTIONS.md`; to be re-verified
  against real venue data in M1.2 and M1.3.
- No arbitrage arithmetic, execution, transport, or venue-specific code added.
  `Opportunity` is a data container only; edge computation is deferred to M1.5.
- Tests: `tests/test_domain_models.py`, deterministic, covering valid
  construction, boundary/invalid values, Decimal preservation, timezone
  enforcement, best bid/ask behavior, and equality/immutability.
- Marked M0.1 and M1.1 complete in `ROADMAP.md` after ruff, mypy, pytest, and
  pre-commit all passed.

## 2026-09-05 — M1.2 Kalshi REST market-data adapter

- Added `src/prediction_market_arbitrage/adapters/kalshi/`: `transport.py`
  (stdlib `urllib` + `Transport` protocol), `client.py` (raw JSON fetch +
  HTTP/timeout/JSON error handling), `normalize.py` (payload → domain models),
  `adapter.py` (`KalshiMarketDataAdapter` façade), `errors.py`.
- Read-only market data only: `GET /markets`, `/markets/{ticker}`,
  `/markets/{ticker}/orderbook`. No auth, orders, portfolio, WebSocket, storage,
  or UI code. Domain layer does not import the adapter (test enforces this).
- **Live verification (unauthenticated, no credentials).** All three production
  endpoints returned HTTP 200 without auth headers; demo host likewise. Unknown
  ticker → 404 `{"error":{"code":"not_found",...}}`; unknown-ticker orderbook →
  200 with empty arrays. This **resolves the documented auth conflict**: the
  Get-Market-Orderbook reference page renders an "Authentication Required" block,
  but market data is public (OpenAPI `security: []`, and observed 200s).
- **Order-book mapping (verified — docs + live + tests).** `orderbook_fp` holds
  bids only in `yes_dollars` / `no_dollars`, ascending, best bid last, each level
  `[price_dollars_str, count_str]`. Normalized per side:
  `bids` = that side's bids reversed to descending; `asks` = opposite side's bids
  as `1 - price` (size unchanged). Only `market_type == "binary"` accepted.
  Worked example: best YES bid 0.2000 → NO ask 0.8000; best NO bid 0.7900 →
  YES ask 0.2100 — matches the market's quoted `yes_ask_dollars` / `no_ask_dollars`.
- All monetary values parsed via explicit `Decimal` (`domain.to_decimal`); raw
  float/int in a payload is rejected, never coerced. Timestamps parsed as
  timezone-aware; book timestamp is an injected `clock()` reading (Kalshi sends
  no per-book server time).
- Sanitized public fixtures under `tests/fixtures/kalshi/` (no credentials /
  account ids / auth headers). Test suite is fully offline and deterministic:
  +39 new tests (47 → 86 total) across `test_kalshi_client.py`,
  `test_kalshi_normalize.py`, `test_kalshi_adapter.py`.
- Evidence: new `docs/API_SOURCES.md`; assumptions A-008–A-011 in
  `docs/ASSUMPTIONS.md`; decisions D-007 (stdlib HTTP + transport seam) and
  D-008 (implied-ask normalization) in `docs/DECISIONS.md`.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run --all-files`
  all pass. Not committed — awaiting review.

## 2026-09-05 — M1.2 branch-correction incident (Git protocol)

- While starting M1.2, stale local refs led to the claim "branch
  `feat/kalshi-market-data` did not exist". After `git fetch origin --prune`:
  M1.1 was already squash-merged to `origin/main`, and
  `origin/feat/kalshi-market-data` already existed on that merged baseline.
- No work was lost: uncommitted + untracked M1.2 changes were preserved with
  `git stash -u`, the local branch was reset onto `origin/feat/kalshi-market-data`,
  and the stash was re-applied (one `docs/DECISIONS.md` conflict, resolved as a
  pure insertion — no M1.1 content overwritten).
- New rule: **D-010** — `git fetch origin --prune` before any claim about
  branch/merge/remote state; local refs are stale until refreshed.

## 2026-09-05 — M1.3 Polymarket US REST market-data adapter

- Added `src/prediction_market_arbitrage/adapters/polymarket_us/`: `transport.py`
  (stdlib `urllib` + its own `Transport` seam / error family — independent of the
  Kalshi adapter), `client.py`, `normalize.py`, `adapter.py`, `errors.py`.
- Read-only market data only: `GET /v1/markets`, `/v1/market/slug/{slug}`,
  `/v1/market/id/{id}`, `/v1/markets/{slug}/book`, `/v1/markets/{slug}/bbo`.
  No auth, orders, portfolio, WebSocket, storage, or UI. Domain layer does not
  import the adapter (test enforces this).
- **Live verification (unauthenticated, no credentials/cookies).** Host
  `gateway.polymarket.us`, `/v1`. `markets` / `market/slug` / `book` / `bbo` all
  returned HTTP 200 with no auth (official SDK README: "Public Endpoints (No
  Authentication)"; OpenAPI `security: []`). Unknown slug → 404 with gRPC-style
  `{"code":<int>,"message":...,"details":[]}`. A live market can return a fully
  empty book (`bids: []`, `offers: []`) — observed and fixtured.
- **Market model (evidence question answered).** A Polymarket US market is a
  single binary market. `marketSides` has exactly two entries: one `long: true`
  (tradeable long side, `description` e.g. "Yes" or a team name) and one
  `long: false`. There is **one** book per slug, quoted in the long side's price
  space, with **explicit** `bids` and `offers`. Mapping: market → `Market`
  (id=slug, title=question, close_time=endDate); the two sides → `:LONG` /
  `:SHORT` `Contract`s; the book → **one** `OrderBook` on `:LONG`
  (bids=book.bids, asks=book.offers). **No `1 - x` synthesis** (contrast D-008) —
  the API is already two-sided. **No domain mismatch** — the model represents the
  observed semantics without distortion.
- Book ordering (bids high→low, offers low→high) matches `bbo` and the domain's
  required order, but the adapter still **sorts explicitly** and rejects
  duplicate price levels rather than assuming source order.
- `transactTime` (nanosecond RFC-3339) is present on every book and is used as
  the `OrderBook` timestamp; the parser truncates >6 fractional digits to
  microseconds; `observed_at` is the documented fallback only if the field is
  absent.
- Decimal discipline: only string fields (`px.value`, `qty`, `endDate`,
  `description`, `slug`, `question`) reach the domain via `domain.to_decimal`;
  Polymarket's genuine JSON floats (`orderPriceMinTickSize`, `feeCoefficient`)
  are never read, so no float can leak.
- Sanitized public fixtures under `tests/fixtures/polymarket_us/` (no
  credentials/cookies/account ids/headers; bulky sports-media sub-objects
  dropped, `description` truncated, all numeric/time/id fields verbatim).
  Offline deterministic tests: +53 (86 → 139 total) across
  `test_polymarket_us_client.py`, `test_polymarket_us_normalize.py`,
  `test_polymarket_us_adapter.py`.
- Evidence: `docs/API_SOURCES.md` (P-01..P-14 + mapping table); assumptions
  A-012–A-017; decisions **D-009** (Polymarket book mapping) and **D-010** (Git
  fetch protocol).
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run --all-files`
  all pass. Not committed — awaiting review.

## 2026-09-06 — M1.4 Manual verified market-pair registry

- Added `src/prediction_market_arbitrage/registry/`: `models.py` (`PairStatus`,
  `OutcomeRelation`, `VenueLeg`, `MarketPairRecord`, `RegistryError`),
  `loader.py` (`load_registry` / `load_registry_text`, `MarketPairRegistry`),
  and `data/market_pairs.toml` (the curated file).
- Format: **TOML** via stdlib `tomllib` — no new dependency (YAML would need
  `pyyaml`); supports the comments a manual risk file needs; array-of-tables
  diffs cleanly. See D-011.
- **Domain `MarketPair` left unchanged.** It is a sufficient domain *value*
  (id + two `Contract`s + note); review-workflow metadata (reviewer, status,
  sources, checklist, …) lives in the registry layer's `MarketPairRecord`, not
  in the frozen domain model. Rationale in D-011.
- Each record: `pair_id`, normalized `proposition`, both venue legs
  (`venue` + `market_id` + `outcome` + primary-source URLs), explicit
  `relation` (`IDENTICAL` / `COMPLEMENTARY`), an 11-item human review
  `checklist`, `reviewer`, `verified_at`, `settlement_notes`,
  `known_differences` (+ `known_differences_reviewed`), `status`, and
  `live_use_eligible` + `blocking_reason`.
- **Fails closed.** Malformed record, unknown status, duplicate `pair_id`,
  unknown field, non-bool checklist value, or a conflicting venue mapping →
  `RegistryError`, nothing loads. `eligible()` returns **only** `VERIFIED`
  pairs; a `VERIFIED` record additionally requires reviewer + tz-aware
  timestamp + settlement notes + sources on **both** legs + every checklist
  item `true` + (`known_differences` non-empty **or**
  `known_differences_reviewed = true`). `live_use_eligible = true` is rejected
  in M1.4.
- **No pairs shipped.** The canonical `market_pairs.toml` contains **zero**
  records and no real venue identifiers — `load_registry().all()` and
  `.eligible()` both return `()`. Worked format examples (DRAFT / VERIFIED /
  etc.) live only in `docs/MARKET_PAIRING.md` and
  `tests/test_market_pair_registry.py`, using synthetic ids
  (`kalshi-test-market`, `polymarket-test-market`).
  (A safety cleanup after the first draft removed example records that had used
  real, intentionally-unrelated Kalshi/Polymarket US market ids.)
- Anti-hallucination recorded in `docs/MARKET_PAIRING.md` + D-011: title
  similarity is not evidence; fuzzy/embedding similarity optimizes for the
  failure mode; LLM matching is deferred (may later *propose*, never
  *approve*); hardcoded pair logic in the engine is rejected. A `VERIFIED`
  pair is **not** a live-trading approval — A-013/A-015/A-016 and
  A-001/A-002/A-003 remain unresolved live-use blockers.
- New doc `docs/MARKET_PAIRING.md` (why matching is dangerous, worked
  false-pair examples, the checklist, why automation is deferred, status →
  eligibility). Assumptions A-018 (relation expressiveness) and A-019
  (fail-closed file is a sufficient gate) added. Decision D-011 added.
- Tests: `tests/test_market_pair_registry.py`, deterministic + offline, +36
  (139 → 175 total).
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting review. `docs/ROADMAP.md`
  M1.4 checkboxes left as-is (M1.2/M1.3 boxes are likewise still unchecked on
  `main`; box-marking is a review step).

## Journal rules

- Record only material progress, evidence, blockers, and changes in direction.
- Do not use this file as a dump of terminal output.
- Link detailed reasoning to `DECISIONS.md`, assumptions to `ASSUMPTIONS.md`, and validation requirements to `TEST_PLAN.md`.
