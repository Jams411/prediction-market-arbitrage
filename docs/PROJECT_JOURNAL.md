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

## 2026-09-06 — M1.5 Deterministic arbitrage engine

- Added `src/prediction_market_arbitrage/arbitrage/`: `errors.py`
  (`ArbitrageError`), `fees.py` (`FeeModel` protocol, `ZeroFeeModel`,
  synthetic `FixedPerUnitFeeModel`), `engine.py` (`EngineConfig`,
  `LegFill`, `LegEvaluation`, `OpportunityEvaluation`, `ArbitrageEngine`).
- **Pure function.** `ArbitrageEngine.evaluate(record, kalshi_book,
  polymarket_us_book, *, evaluation_time, requested_quantity)` →
  `OpportunityEvaluation`. No I/O, no wall-clock time, no venue knowledge, no
  positions/orders. `evaluate_from_registry(registry, pair_id, ...)` is the
  intended entry point.
- **Registry gate, not bypassable.** `evaluate()` raises unless
  `record.status == VERIFIED`; `evaluate_from_registry` also requires the record
  to be in `registry.eligible()`. DRAFT / REVIEW_REQUIRED / REJECTED / SUSPENDED
  → `ArbitrageError`.
- **Economics (exact Decimal, no internal rounding):**
  `gross_total_cost = acq_a + acq_b`; `gross_edge = size - gross_total_cost`;
  `net_total_cost = gross_total_cost + fees + execution_buffer`;
  `net_edge = size - net_total_cost`; opportunity iff `net_edge > 0` (exact
  break-even is not an opportunity). `expected_total_profit = net_edge`.
  `*_per_unit` are derived (`total / executable_quantity`) and documented as the
  only possibly-context-rounded fields (A-023).
- **Depth-walking.** `_walk_asks` fills a target quantity across ascending ask
  levels and reports each slice + total cost. Executable size =
  `min(requested, depth_a, depth_b, max_quantity)`; `require_full_fill` turns a
  depth shortfall into no-opportunity. No smaller partial-fill search (open
  bound without a verified tick size — deferred to M2.4).
- **Fees / buffer.** Injected `FeeModel` (no real venue schedule hardcoded —
  A-022); explicit `Decimal` `execution_buffer_per_unit`. Float config /
  requested-quantity inputs raise.
- **Freshness (optional).** `max_book_age` and `max_cross_book_skew` against an
  **injected** `evaluation_time` (tz-aware; naive raises). Stale / skewed /
  future-dated books → no opportunity.
- **Book↔leg join** is on `OrderBook.contract.id == f"{leg.market_id}:{leg.outcome}"`
  (A-020); any mismatch (wrong contract, swapped books, wrong venue) raises. The
  engine never guesses which book is which.
- **Relation scope:** only `COMPLEMENTARY` is evaluated; `IDENTICAL` needs a
  sell leg → no opportunity with a reason.
- `OpportunityEvaluation.to_opportunity()` builds the minimal domain
  `Opportunity` (+ a domain `MarketPair` from the two contracts) only when
  `has_opportunity`. **Domain models unchanged** — audit detail lives in the
  strategy layer (D-012, mirrors D-011).
- Docs: new `docs/ARBITRAGE_METHODOLOGY.md` (why sub-$1 complementary buys are
  arbitrage; gross vs net; depth; fees; top-of-book; equivalence as a separate
  prerequisite; positive edge ≠ realized profit; leg/execution risk deferred).
  Decision D-012 (engine isolation + 4-way separation rationale). Assumptions
  A-020..A-023.
- **No production pair added** — `market_pairs.toml` stays empty; all engine
  tests use in-memory synthetic VERIFIED records with fake ids.
- Tests: `tests/test_arbitrage_engine.py`, deterministic + offline, +34
  (175 → 209 total). Exact known-answer Decimal cases (0.45+0.52 baseline; the
  0.40x5/0.42x10 vs 0.50x8 depth example; fee/buffer/break-even/negative;
  precision; float rejection) plus registry-enforcement and freshness cases.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting review. `docs/ROADMAP.md`
  M1.5 checkboxes left as-is (M1.2–M1.4 boxes likewise unchecked on `main`).

## 2026-09-06 — M1.6 Evidence-backed venue fee models

- Branch: work moved onto `feat/venue-fee-models`, cut from `origin/main` after
  M1.5 merged there (was carried as an uncommitted diff on
  `feat/arbitrage-engine`).
- Added to `src/prediction_market_arbitrage/arbitrage/fees.py` (alongside the
  M1.5 baseline), all **taker** path:
  - `KalshiTradingFeeModel` — `round_up_to_next_cent(M · 0.07 · C · P · (1−P))`,
    the current "Fee Schedule for July 2026 — 7.7.26 Update". `M` = per-contract
    multiplier, `multiplier=` arg, default `Decimal("1")`. No settlement fee.
  - `PolymarketUsTradingFeeModel` — `bankers_round_cent(0.06 · C · p · (1−p))`
    (round half to even), the exchange-wide taker fee effective July 1, 2026.
  - `VenueFeeModel` — routes each leg's fills to its venue's model; unknown
    venue → `ArbitrageError` (fail closed). `VenueFeeModel.real_taker()` bundles
    both. All three exported from `arbitrage/__init__.py`.
- **Correction from first draft:**
  - Kalshi moved to the 7.7.26 multiplier schedule: added `M` (default 1),
    **removed** the stale standalone `0.035` S&P 500 / Nasdaq-100 coefficient
    and the `general_coefficient` override — those series now carry a per-series
    `M` in Kalshi's "non-standard fees" table. `M` is a caller-supplied,
    evidence-backed input; no series value is transcribed or hardcoded, so the
    implementation and tests need none.
  - Polymarket US taker coefficient **kept at `0.06`**. A prompt asked to change
    it to `0.05`; re-verifying `docs.polymarket.us/fees` (effective July 1,
    2026) shows a single exchange-wide taker `Θ = 0.06` and a self-consistent
    price table — `0.05` is contradicted by the primary source (it appears only
    on third-party sites, as one category in a claimed split). Not adopted;
    recorded as unresolved in A-025.
- **Evidence:** `docs/evidence/kalshi-fee-schedule-2026-07-07.txt` — the current
  "7.7.26 Update" PDF (12 pages) opens in a normal browser (confirmed
  2026-09-06); formula text quoted from the PDF via search indexing + Help
  Center, general `M=1` table reproduced, per-series `M` table noted as present
  but not transcribed. `docs/evidence/polymarket-us-fee-schedule.txt` —
  re-verified server-rendered page, `0.05` conflict documented.
- **Scope held tight:** taker only; per-fill-slice rounding (A-026, still
  explicitly unresolved); no series auto-detection; engine keeps its injected
  `FeeModel` protocol + fee-value validation, gains no venue knowledge
  (`EngineConfig.fee_model` still defaults to `ZeroFeeModel`).
- **Not modelled (documented, not guessed):** Kalshi maker (`M · 0.0175`);
  Polymarket US maker **rebate** (`−0.0125`) and volume-tier taker rebate;
  multi-level-sweep rounding; Kalshi's full per-series `M` table; Polymarket US
  category / reported-CFTC-filing coefficient questions.
- Records: D-013 (decision, updated); A-024 (Kalshi 7.7.26 formula — VERIFIED;
  per-series `M` table present in source, not transcribed), A-025 (Polymarket
  US `0.06` re-verified; `0.05` unresolved), A-026 (per-slice rounding —
  unresolved); A-022 SUPERSEDED; `docs/ARBITRAGE_METHODOLOGY.md` §4 / §7 / §8
  updated.
- Evidence-correction pass (2026-09-06): confirmed the Kalshi "7.7.26 Update"
  PDF opens in a normal browser (12 pages); removed the earlier
  "bot-gated / table unavailable" framing from the evidence file and A-024. No
  code or test change — the implementation hardcodes no multiplier.
- Tests: `tests/test_arbitrage_fees.py`, deterministic + offline, +47. Published
  fee-table vectors for both venues (Kalshi `M=1` general table), Kalshi
  `M`-scaling via independently-calculated cases (`M` = 0.5 / 1.5 / 2 / 0),
  per-slice rounding, price-at-bounds → $0, banker's half-to-even, wrong-venue
  and float / negative rejections, `VenueFeeModel` routing + fail closed, and
  two engine-integration cases with exact known net edge.
- No real market-pair approvals created; `market_pairs.toml` still ships empty.
  Real-money remains disabled — no fee formula OBSERVED against a real fill;
  fee reconciliation stays a real-money-gate item.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files`. Not committed — awaiting review.

## 2026-09-06 — M2.1 Live book state

- Branch `feat/live-book-state` off `origin/main` (includes M1.6).
- New package `src/prediction_market_arbitrage/livebook/`:
  - `updates.py` — venue-neutral `BookSnapshot` / `BookDelta` (exact `Decimal`,
    tz-aware timestamps, optional `sequence`).
  - `state.py` — `LiveBook` (one contract's `price → quantity` index; additive
    delta, zero-level removal) and `LiveBookFeed` (connection state + Kalshi
    `seq` sequencing + staleness vs an **injected** `now` + fail-closed
    `FeedHealth`). `trading_enabled` is `True` only for `HealthStatus.HEALTHY`;
    `UNINITIALIZED` / `STALE` / `DISCONNECTED` / `RESYNCING` / `DESYNCED` /
    `MARKET_NOT_OPEN` all disable trading and `current_order_book(now)` → `None`.
    Domain invariants enforced by building a real `OrderBook`; a crossed result
    → `DESYNCED`.
  - `kalshi_ws.py` — decodes `orderbook_snapshot` / `orderbook_delta` into a
    YES/NO pair of updates (reusing the K-08 `1 - opposite_bid` implied-ask
    rule). `delta_fp` applied additively (A-028).
  - `polymarket_us_ws.py` — decodes `SUBSCRIPTION_TYPE_MARKET_DATA` (a full book
    every frame) into one `:LONG` `BookSnapshot`; `state` drives market-open
    gating.
- **Disconnect / stale / resync:** `mark_disconnected()` → `DISCONNECTED`;
  `begin_resync()` → `RESYNCING`; the next `apply_snapshot()` restores
  `HEALTHY`. Kalshi `seq` gap / negative-quantity delta / crossed result →
  `DESYNCED`, and deltas are ignored until a resync snapshot. Polymarket (no
  sequence): every frame replaces the book; a `transactTime`-older frame is
  dropped (at-least-once).
- **No socket, no credentials, no wall-clock** — both venues' market-data WS
  need handshake auth (A-027). Decoders + state machine are the testable core;
  a real transport is a later boundary that calls the same methods.
- Evidence: `docs/API_SOURCES.md` new sections K-WS-01..06 (Kalshi AsyncAPI) and
  P-WS-01..04 (Polymarket Markets-WS + streaming guide), all **docs-only** — no
  live socket, no WS fixture captured. D-014; A-027 / A-028 (Kalshi additive
  delta — UNVERIFIED, not OBSERVED) / A-029 (Kalshi feed has no market-state
  gate).
- Not in scope / unchanged: recorder, replay, paper broker, orders, risk
  manager, UI. A-013 (Polymarket book side) not resolved. Real-money disabled.
  `docs/ROADMAP.md` M2.1 checkboxes left as-is (matches the M1.x precedent on
  `main`).
- Tests: `tests/test_livebook_state.py`, `tests/test_livebook_kalshi_ws.py`,
  `tests/test_livebook_polymarket_us_ws.py` — 34 deterministic offline tests;
  frames follow the published AsyncAPI / docs examples. Suite 256 → 290.

### M2.1 (cont.) — authenticated WebSocket transport boundary

- `livebook/credentials.py` — `KalshiCredentials` / `PolymarketUsCredentials`,
  frozen, **redacted** `repr`/`str`, `*_credentials_from_env` reading explicit
  env var names. No secret in repo, log, or disk.
- `livebook/ws_auth.py` — pure, **docs-verified** builders: sign string
  `timestamp + "GET" + path` (Kalshi `/trade-api/ws/v2`, Polymarket US
  `/v1/ws/markets`), the three auth headers, URL constants, and the subscribe
  command per venue. Signature (RSA-PSS / Ed25519) via an injected `Signer` —
  no `cryptography` import.
- `livebook/transport.py` — `WebSocketTransport` / `SnapshotSource` protocols,
  pure `BackoffPolicy` (exponential, capped, optional `max_attempts`), frame
  decoders (raw frame → M2.1 updates; acks/errors → `[]`), and
  `LiveBookConnection`: `connect_and_subscribe` → `pump_one` (route by
  `contract_id`) → `handle_disconnect` (all feeds → `DISCONNECTED`) →
  `reconnect(sleep)` → `resync()` (per feed: `begin_resync` → REST
  `SnapshotSource.fetch` → `apply_snapshot` → `HEALTHY`). `run_forever` is the
  only loop; socket / REST / clock / sleep all injected.
- **Concrete transport:** `livebook/ws_transport.py` — `WebsocketsTransport`
  over the `websockets` library (`websockets>=13` added to
  `pyproject.toml` — the project's **sole runtime dependency**; the client both
  venue docs use; pure Python, no transitive deps). Only module in `livebook`
  that does real network I/O or imports a third-party package.
  `connect`/`send`/`receive`/`close` wrap `websockets.sync.client`;
  `ConnectionClosed` and recv-timeout → `TransportClosed`; library handles
  Ping/Pong. Plugs into the unchanged `LiveBookConnection`.
- **Still not built:** a `Signer` implementation — the RSA-PSS / Ed25519 step
  stays the caller's, so **no `cryptography` dependency**. And no real
  authenticated connection to a venue: `WebsocketsTransport` is tested against a
  local `websockets` loopback server (real socket, accepts any headers), which
  is **not** OBSERVED handshake evidence (**A-030** stays UNVERIFIED; **A-028**
  and the Polymarket subscribe casing/enum conflict (P-WS-AUTH-03) also
  unresolved).
- Evidence: `docs/API_SOURCES.md` section WS-A-S1..S6 + K-WS-AUTH-01..04 /
  P-WS-AUTH-01..03 (docs-only) with a "transport implementation status" note.
  D-015 (updated: transport added, signer still injected); A-027 updated
  (boundary implemented), A-030 updated (still no venue handshake).
- Tests: `tests/test_livebook_credentials.py`, `tests/test_livebook_ws_auth.py`,
  `tests/test_livebook_transport.py` (31 — redaction, env loaders, sign strings
  verbatim, header assembly with a fake signer, subscribe validation, backoff
  math, frame-decoder routing, full connect/pump/disconnect/backoff-reconnect/
  resync with in-memory fakes) + `tests/test_livebook_ws_transport.py` (5 —
  real `websockets` round-trip on loopback: connect/send/receive/close, header
  propagation, recv-timeout → `TransportClosed`, dead-address → `TransportClosed`,
  and `LiveBookConnection` driving the real transport). Suite 290 → 326.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.
- M2.1 deliverables (REST snapshot init, WS updates, disconnect detection,
  stale handling, reconnect/resync, trading-disabled-on-unhealthy) are all
  implemented; `docs/ROADMAP.md` M2.1 checkboxes left unticked per the M1.x
  precedent on `main`.

## 2026-09-06 — M2.2 Persistent recorder

- New package `src/prediction_market_arbitrage/recorder/` — a **write-only,
  append-only** DuckDB sink (`duckdb>=1.0`, the second runtime dependency after
  `websockets`). Continues the `feat/live-book-state` branch.
- `schema.py` — idempotent `initialize(conn)` (`CREATE ... IF NOT EXISTS`) that
  refuses a foreign `SCHEMA_VERSION`; tables `recording_sessions`,
  `order_book_snapshots` + `order_book_levels`, `opportunities`, `order_events`,
  `fills`, `positions`, `pnl`, `health_events`, `schema_meta`; a per-table
  `SEQUENCE` gives monotonic `id`s.
- `models.py` — `OrderEventRow` / `FillRow` / `PositionRow` / `PnlRow` (frozen,
  validated) for entities with no domain type yet (M2.4 / M2.5).
- `recorder.py` — `Recorder` with `record_order_book`, `record_opportunity`
  (takes an M1.5 `OpportunityEvaluation`), `record_order_event`, `record_fill`,
  `record_position`, `record_pnl`, `record_health_event` (takes an M2.1
  `FeedHealth`). Each appends one row (order book: parent + level rows) and
  returns the new id. `Recorder.open(database=":memory:", ...)` connects + inits
  + registers the session (`INSERT OR IGNORE`). No update/delete API.
- **Fidelity (A-031):** money/price/qty stored as exact `str(Decimal)` in
  `VARCHAR` (no fixed-scale `DECIMAL`); timestamps must be tz-aware, normalized
  to naive-UTC `TIMESTAMP` (µs). Naive datetime / non-`Decimal` money →
  `RecorderError`.
- **Determinism:** no wall-clock, no random id; `session_id` + every timestamp
  injected. Same calls → byte-identical rows (test). Sequence ids persist across
  reopen of a file-backed DB (test).
- **Decoupling:** the recorder imports the *types* it stores and none of their
  behaviour; nothing in domain / arbitrage / livebook imports the recorder.
- Records: D-016; A-031. `docs/ROADMAP.md` M2.2 checkboxes left unticked per the
  M1.x / M2.1 precedent (all six items — DuckDB, order-book, opportunities,
  orders/fills, positions/PnL, health events — are implemented).
- Not in scope / unchanged: replay adapter (M2.3), paper broker, risk manager,
  UI, live execution. Real-money disabled.
- Tests: `tests/test_recorder_schema.py` (3) + `tests/test_recorder.py` (14) —
  17 deterministic offline (schema init/idempotency/version guard, Decimal +
  timestamp round-trip, monotonic ids, opportunity/health/order/fill/position/
  PnL writes, null `last_update`, byte-identical determinism, no-update/delete
  surface, file persistence). Suite 326 → 343.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-07 — M2.3 Replay adapter

- New package `src/prediction_market_arbitrage/replay/` — a **read-only,
  deterministic** consumer of an M2.2 recorder DuckDB database. Branch
  `feat/replay-adapter` off `origin/main` (which now has M2.1 #9 + M2.2 #10).
  **No new runtime dependency** (`duckdb` already present).
- `errors.py` (`ReplayError`), `_read.py` (stored text → exact `Decimal`;
  naive-`TIMESTAMP` → UTC reattached via `.replace(tzinfo=UTC)` per A-031;
  `rebuild_contract`), `models.py` (`RecordedOrderBook` + 6 stream row types +
  `ReplayEvent`), `session.py` (`ReplaySession`, `no_sleep`, `realtime`).
- `ReplaySession(connection | .open(path, read_only=True), *, session_id)` —
  checks `schema_version` + session existence, then one iterator per stream
  (`order_books`, `opportunities`, `order_events`, `fills`, `positions`, `pnl`,
  `health_events`), each `SELECT ... ORDER BY id`. No write/update/delete
  surface.
- `timeline()` merges the streams on `(recorded_at, kind_rank, row_id)` — a
  fixed total order; two identical recordings replay to equal timelines (test).
- `play(sleep=no_sleep, speed=1.0)` — injected timing; default `no_sleep` is a
  plain deterministic iterator, `realtime(speed)` wraps `time.sleep` for
  real-time playback.
- **Strategy-interface compatibility:** `as_book_snapshots()` yields
  `livebook.BookSnapshot` (`sequence` / `market_state` = `None`);
  `feed_book_snapshots({contract_id: LiveBookFeed})` applies replayed books
  through the unchanged `LiveBookFeed.apply_snapshot`, paced like `play` (test
  drives a real feed to `HEALTHY` with Decimal-exact levels). Re-running the
  M1.5 engine needs the verified pair record, which the recorder does not store
  — left to the caller with the reconstructed `OrderBook`s + `RecordedOpportunity`.
- **A-032:** `Venue.name` / `Market.title` are synthesized from ids (recorder
  stored identifiers only); `Contract.id`, `outcome`, `venue.id`, `market.id`,
  Decimal prices/qty, level order, UTC book timestamp are all exact.
- Records: D-017; A-031 (reattach noted), A-032. `docs/ROADMAP.md` M2.3 checkbox
  left unticked per precedent (item implemented).
- Not implemented: paper broker, risk manager, dashboard/UI, live execution,
  new recorder features. Real-money disabled.
- Tests: `tests/test_replay.py` (16) + `tests/replay_support.py` — deterministic
  offline (order-book Decimal + UTC fidelity incl. a 30-digit value, livebook
  `BookSnapshot` shape, real `LiveBookFeed` driven by `feed_book_snapshots`,
  opportunity/health/order/fill/position/PnL streams, null `last_update`,
  timeline ordering, two-recording determinism, `play` default no-sleep +
  gap/speed pacing, `realtime` scaling, non-recorder DB / missing session /
  foreign schema-version errors, no-write-API surface). Suite 343 → 359.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-07 — M2.4 Deterministic paper broker

- New package `src/prediction_market_arbitrage/paper_broker/` — a pure,
  injected-effect simulator of **taker** order execution against normalized
  `OrderBook` depth. Branch `feat/paper-broker` off `origin/main` (M2.3 #11
  merged). **No new runtime dependency.**
- `errors.py` (`PaperBrokerError`), `slippage.py` (`SlippageModel` protocol +
  `NoSlippage` / `FixedOffsetSlippage` / `PerLevelSlippage`), `models.py`
  (`OrderRequest`, `Fill`, `Order`, `OrderStatus`, `StatusTransition`,
  `BrokerEvent`, `LegRiskSnapshot`), `broker.py` (`PaperBroker`,
  `PaperBrokerConfig`).
- Driven by `submit(request, *, at)` / `cancel(order_id, *, at)` /
  `advance(*, at, books={contract_id: OrderBook})`. Monotonic simulated time
  (enforced); every timestamp injected; no wall-clock, no RNG.
- **Latency:** order effective at `submit + submit_latency`; a book stamped
  before that cannot fill it. **Depth / partial fills:** buy walks asks / sell
  walks bids, best-first, stops at limit price; short depth → `PARTIALLY_FILLED`
  and keeps working (unless IOC). **Slippage:** per-level `SlippageModel.adjust`
  clamped to `[0.0001, 0.9999]` (A-033). **Rejections:** malformed request,
  below `min_order_size`, IOC/market with no eligible liquidity on first
  eligible book, duplicate id. **Cancellation:** effective at
  `cancel + cancel_latency`; an earlier fill wins the race; IOC remainder
  canceled. **Expiry:** market-order remainder past `market_order_ttl`.
  **Leg risk:** `PaperBroker.leg_risk(a, b, *, as_of, books)` →
  `LegRiskSnapshot` (unhedged qty, avg prices, completion mid, unhedged
  notional) — measurement only, judgement is M2.5.
- Fees: injected `arbitrage.FeeModel` (reuses M1.6 schedules; `ZeroFeeModel`
  default), one `Fill` per level with its own fee.
- **Recorder integration, no redesign:** `Order.event_rows()` →
  `recorder.OrderEventRow`s, `Fill.to_row()` → `recorder.FillRow`,
  `PaperBroker.position(...)` → `recorder.PositionRow`. Broker imports only those
  row types; nothing in recorder/replay imports the broker. Test persists a
  simulated order through a real `Recorder` and reads it back.
- Records: D-018; A-033. `docs/ROADMAP.md` M2.4 checkboxes left unticked per
  precedent (all seven items implemented).
- Not implemented: live broker/API orders, risk manager, dashboard/UI,
  production live trading, automatic market pairing. Real-money disabled.
- Tests: `tests/test_paper_broker.py` (28) + `tests/paper_broker_support.py` —
  deterministic offline (latency gate incl. stale book, depth walk + partial +
  completion, limit-price cap, sell side, min-size / IOC-no-liquidity /
  IOC-remainder / duplicate / malformed rejections, fixed + per-level slippage +
  clamp, cancel-latency + fill-beats-cancel + cancel-after-terminal, market TTL
  expiry, leg risk, injected fee per fill, position averaging + flatten,
  recorder round-trip, script determinism, backwards-time + naive-datetime
  misuse, event-row history). Suite 359 → 387.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-07 — M2.5 Deterministic risk manager

- New package `src/prediction_market_arbitrage/risk/` — a fail-closed veto layer
  over the objects M1.5 / M2.1 / M2.4 already produce. Branch `feat/risk-manager`
  off `origin/main` (M2.4 #12 merged). **No new runtime dependency, no strategy
  logic.**
- `errors.py` (`RiskError`), `limits.py` (`RiskLimits` — 8 optional
  Decimal/timedelta limits + always-on kill switch, validated), `decision.py`
  (`RiskDecision(allowed, reasons, checks_run, as_of)` + `raise_if_rejected()`),
  `state.py` (`RiskState` — kill switch, consecutive-error counter, per-UTC-day
  realized-PnL ledger, "unhedged since" map; every mutation timestamp-driven),
  `manager.py` (`RiskManager`, `RiskSnapshot`).
- `evaluate_order(request, *, now, positions?, marks?, opportunity?, health?,
  leg?, leg_pair_key?)` runs every configured check and returns **all** failing
  reasons. `evaluate_opportunity(...)` is the session-wide + edge subset.
- Enforces: max position (projected signed qty), max exposure
  (`Σ |projected_qty| * mark`, mark = `marks` → `avg_price` → limit price), max
  order size, min `net_edge_per_unit`, max data age + unhealthy-feed reject, max
  unhedged time (`now − since`, non-terminal non-zero leg), consecutive-error
  limit, max daily loss (realized loss for `now`'s UTC day), kill switch.
- **Fail closed (A-034):** a set limit with a missing required input
  (`positions` / `opportunity` / `health` / `leg`) or an unhealthy /
  future-dated `FeedHealth` → reject. `evaluate_order` advances the unhedged
  timer as a deliberate side effect.
- Consumes `OpportunityEvaluation` / `FeedHealth` / `OrderRequest` /
  `LegRiskSnapshot` / `recorder.PositionRow` unchanged; imports those types
  only; nothing in strategy/execution imports `risk`.
- Records: D-019; A-034. `docs/ROADMAP.md` M2.5 checkboxes left unticked per
  precedent (all nine items implemented).
- Not implemented: live broker/API orders, dashboard/UI, live execution, new
  strategy logic. Real-money disabled.
- Tests: `tests/test_risk_manager.py` (25) + `tests/risk_support.py` —
  deterministic offline (one per limit + its fail-closed path, kill
  switch on/off, unhealthy-feed reject without an age limit, future-dated
  health, both-terminal leg = hedged, multi-reason decision, fully-configured
  happy path exercising all checks, `evaluate_opportunity` subset, script
  determinism, `snapshot`, naive-datetime + bad-limits + wrong-type misuse).
  Suite 387 → 412.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Committed to `feat/risk-manager` and pushed for review
  (no PR, no merge to `main`).

## Journal rules

- Record only material progress, evidence, blockers, and changes in direction.
- Do not use this file as a dump of terminal output.
- Link detailed reasoning to `DECISIONS.md`, assumptions to `ASSUMPTIONS.md`, and validation requirements to `TEST_PLAN.md`.
