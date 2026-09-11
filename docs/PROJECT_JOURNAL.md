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

## 2026-09-07 — M3.1 Operational dashboard

- New package `src/prediction_market_arbitrage/dashboard/` — a **read-only,
  deterministic projection** of the objects the pipeline already produces.
  Branch `feat/dashboard` off `origin/main` (M2.5 #13 merged). **No new runtime
  dependency, no strategy logic.**
- `errors.py` (`DashboardError`), `models.py` (frozen view dataclasses +
  `Severity` / `Alert` / `DashboardView`), `build.py` (`build_dashboard`),
  `render.py` (`render_text`).
- `build_dashboard(*, now, feeds?, registry?, opportunities?, orders?,
  positions?, marks?, pnl?, leg_risk?, risk?, last_risk_decision?,
  max_data_age?)` → immutable `DashboardView` with `feeds`, `pairs`,
  `opportunities`, `orders`, `fills` (flattened from `Order.fills`), `positions`,
  `pnl`, `leg_risk`, `risk`, `alerts`, `worst_data_age`, `.healthy`.
- Shows: venue/feed health + derived WebSocket state, verified/curated pairs,
  current opportunities, paper orders/fills, positions/PnL + best-effort
  exposure, risk state (kill switch / error streak / daily PnL / unhedged
  pairs / last decision), latency/data-age. Unhealthy & stale states are
  surfaced as ranked `alerts` (`ALERT` before `WARN`) and tokenised
  `[ALERT]` / `[WARN]` / `[STALE]` in `render_text`.
- WebSocket state is derived from `FeedHealth.status` (livebook exposes no
  separate socket-state accessor). Exposure reuses the A-034 mark fallback
  (explicit `marks` → cost basis → none); cost-basis exposure is labelled
  approximate.
- Consumes M1.4 / M1.5 / M2.1 / M2.2 / M2.4 / M2.5 objects unchanged; imports
  those types only; nothing imports `dashboard`. No wall-clock (naive `now` →
  `DashboardError`), no socket, no recorder / DuckDB read, no order submission.
- Records: D-020; A-035. `docs/ROADMAP.md` M3.1 checkboxes left unticked per
  precedent (all eight items implemented).
- Not implemented: live-updating TUI / web server, alert escalation, live
  broker/orders, strategy changes, failure testing (M3.2), performance report
  (M3.3), real-money activation.
- Tests: `tests/test_dashboard.py` (28) + `tests/dashboard_support.py` —
  deterministic offline (empty view, naive-`now` reject, immutability, render
  determinism; healthy / stale / disconnected / uninitialized / market-not-open
  feeds; registry projection; opportunity + stale flag; order/fill flattening +
  rejected-order warn; position exposure via explicit mark / cost-basis / none
  + stale; PnL net; leg-risk warn + both-terminal quiet; kill switch alert,
  error streak + daily loss warn, unhedged-pair listing, rejected last decision;
  alert ranking; worst-data-age; render tokens). Suite 412 → 440.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Committed to `feat/dashboard` and pushed for review
  (no PR, no merge to `main`).

## 2026-09-07 — M3.2 Deterministic failure testing

- New `tests/test_failure_scenarios.py` (35 tests) — one section per
  `docs/ROADMAP.md` M3.2 bullet, driving **existing** seams / fakes with an
  injected failure and asserting the fail-closed contract plus the designed
  recovery / resync. Branch `feat/failure-testing` off `origin/main` (M3.1 #14
  merged). **Tests only — no production feature added, no new dependency.**
- Coverage by category:
  - **Venue disconnects** — `mark_disconnected` → trading disabled → `begin_resync`
    + snapshot → HEALTHY; `LiveBookConnection.reconnect` deterministic backoff
    (`[1.0, 2.0]`) then `resync`; give-up after `max_attempts` stays failed
    closed; disconnect shows as a dashboard `ALERT` and vetoes a risk
    `evaluate_opportunity`.
  - **Stale prices** — feed STALE disables trading and clears on the next
    update; engine `max_book_age` rejection; risk `max_data_age` + future-dated
    health rejection.
  - **Empty / malformed books** — empty ask side is never an opportunity;
    duplicate price levels rejected; a crossing delta → DESYNCED (trading
    disabled); non-JSON transport frame → `LiveBookError`; structurally
    malformed Kalshi frame → decoder `LiveBookError`.
  - **Fee mismatch** — a higher fee model flips a gross edge to no-opportunity;
    execution buffer absorbs a thin edge; risk `min_net_edge_per_unit` floor.
  - **Partial / one-leg fills** — IOC partial fill cancels the remainder; a
    one-legged `LegRiskSnapshot` is allowed inside the window and vetoed past
    `max_unhedged_time`; unhedged leg shows on the dashboard; a hedged
    observation clears the timer.
  - **Duplicate messages / orders** — duplicate-sequence delta → `DUPLICATE`
    (book unchanged); stale-sequence snapshot dropped; duplicate `order_id`
    → `PaperBrokerError`; recorder exposes no update/delete surface.
  - **API timeout / rate limit** — adapter propagates `KalshiTimeoutError`
    (not swallowed); HTTP 429 → `KalshiHTTPError(status=429)`; Polymarket HTTP
    503 → `PolymarketHTTPError(status=503)`, never a partial book.
  - **Invalid contract mapping** — non-VERIFIED pair → `ArbitrageError`;
    book/record contract mismatch → `ArbitrageError`; feed rejects a message
    for another contract; connection rejects a feed from another venue.
  - **Database / process restart** — a recording read back by a fresh
    `ReplaySession` after "process 1" closed is byte-identical across two
    reopens; reopening a recorder file continues append-only; a foreign
    `schema_version` file is refused (no migration); unknown `session_id`
    → `ReplayError`.
- **No real defect discovered** — every fail-closed / recovery seam behaved as
  designed; these are modelled scenarios only (see `docs/DECISIONS.md` D-021,
  `docs/ASSUMPTIONS.md` M3.2 notes). `docs/ROADMAP.md` M3.2 checkboxes left
  unticked per precedent (all nine items covered).
- Not implemented: performance report (M3.3), live broker, UI changes, strategy
  changes, real-money activation.
- Suite 440 → 475. Gates: `ruff check .`, `mypy src tests`, `pytest`,
  `pre-commit run --all-files` all pass. Committed to `feat/failure-testing` and
  pushed for review (no PR, no merge to `main`).

## 2026-09-07 — M3.3 Deterministic paper-performance report

- New package `src/prediction_market_arbitrage/perf_report/` — a **pure
  read-only projection** of one M2.2 recording, read through the M2.3
  `ReplaySession`. Branch `feat/paper-performance-report` off `origin/main`
  (M3.2 #15 merged). **No new runtime dependency.**
- `errors.py` (`PerfReportError`), `models.py` (`Stats` + section dataclasses +
  `PerfReport`), `build.py` (`build_report`), `render.py` (`render_text`).
- `build_report(session, *, pnl_scope="portfolio", pnl_scope_id=None)` →
  immutable `PerfReport`:
  - **Opportunities**: observed / positive-edge / rejected + rejection-reason
    histogram; mean/median/min/max net edge (total and per unit) over
    positive-edge rows; executable-quantity stats; depth-capped count + fraction.
  - **Opportunity duration** (derived): an episode is a maximal run of
    consecutive positive-edge evals for one `pair_id`; duration =
    `last_eval_time − first_eval_time`; single-observation episodes counted
    separately (no duration).
  - **Paper trades**: orders, fully/partially/unfilled, fill rate, partial-fill
    rate, filled-quantity ratio, final-status histogram, fills, fill liquidity,
    fill fees.
  - **Depth**: best and total size per side over recorded order books.
  - **PnL / drawdown**: for one scope, final realized/unrealized/fees/net, peak
    net, max peak-to-trough drawdown of the `realized + unrealized − fees`
    series.
- **Missing ≠ zero.** `Stats` aggregates are `None` when there is no data; each
  unavailable metric is listed in `PerfReport.unavailable` with its reason. The
  renderer prints `n/a` (+ reason) vs a real number.
- **Leg-risk events are not persisted** (no recorder table) — reported as
  unavailable, never as `0` events.
- Pure: no wall-clock, no DuckDB access, no writes, no order submission; imports
  the replay / recorder types only; nothing imports `perf_report`. Bad
  `pnl_scope` → `PerfReportError`.
- Records: D-022; A-036. `docs/ROADMAP.md` M3.3 checkboxes left unticked per
  precedent (all eight items covered where persisted data supports them).
- Not implemented: leg-risk persistence, live broker, dashboard changes,
  strategy changes, real-money activation.
- Tests: `tests/test_perf_report.py` (19) + `tests/perf_report_support.py` —
  a hand-built known-answer recording (5 opportunities: 3 positive / 2 rejected;
  net-edge [2,4,1]; a 2-eval P1 episode = 20s + a single-obs P2 episode;
  3 orders fully/partial/unfilled; 2 order books; portfolio pnl net
  [0,5,2,6.5] → peak 6.5, drawdown 3; a `contract`-scope row that must be
  filtered out) plus an empty-session test asserting every aggregate is `None`
  not `0`. Suite 475 → 493.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Committed to `feat/paper-performance-report` and pushed
  for review (no PR, no merge to `main`).

## 2026-09-07 — M3.4 Live-broker interface boundary

- New package `src/prediction_market_arbitrage/live_broker/` — the **shape** of a
  live path plus its non-bypassable safety machinery, and **nothing that can
  place a real order**. Branch `feat/live-broker-interface` off `origin/main`
  (M3.3 #16 merged). **No new runtime dependency.**
- `errors.py`, `gate.py` (`LiveTradingGate`, `LIVE_TRADING_ENABLED = False`,
  `REQUIRED_PHRASE`), `models.py` (venue-neutral `LiveOrderRequest` /
  `CancelRequest` / `LiveOrderAck` / `LiveOrderStatus` / `LivePosition` /
  `LiveOrderState`), `idempotency.py` (`IdempotencyGuard`), `interface.py`
  (`LiveBroker` ABC), `credentials.py` (`Kalshi/PolymarketUsTradingCredentials`
  + `*_from_env`), `kalshi.py` / `polymarket_us.py` (venue adapters).
- `LiveBroker` defines `submit_order` / `cancel_order` / `get_order` /
  `get_positions`. Every public method enforces, in order: input validation +
  tz-aware `now` + venue match → `LiveTradingGate.assert_live_allowed` →
  (`submit_order` only) `IdempotencyGuard.register(client_order_id)` → subclass
  `_do_*` hook. A subclass cannot skip the gate or the dedupe check.
- **`LIVE_TRADING` off by default, un-armable by accident:** `LiveTradingGate`
  is a frozen dataclass; the default and `LIVE_TRADING_ENABLED` are `False`;
  arming requires the exact literal
  `I_UNDERSTAND_THIS_PLACES_REAL_ORDERS` (any other phrase raises in
  `__post_init__`); `from_env` arms only when `PMA_LIVE_TRADING` equals that
  string (`1` / `true` do nothing); there is no setter.
- **Both venue adapters are explicitly unsupported.** `docs/API_SOURCES.md` has
  primary evidence for market data only — no order-placement / cancel /
  order-status / positions shape for either venue — so `KalshiLiveBroker` /
  `PolymarketUsLiveBroker` raise `UnsupportedLiveOperationError` for every
  operation, even with an armed gate + credentials. Nothing signs or sends.
- **Idempotency guard is the local half only** (process memory); venue-side
  dedupe is unverified. **Trading credentials are isolated** from the M2.1
  market-data credentials (separate types + `KALSHI_TRADING_*` /
  `POLYMARKET_US_TRADING_*` env vars) and redacted in `repr`.
- Records: D-023; A-037. `docs/ROADMAP.md` M3.4 items ("Interface may exist",
  "LIVE_TRADING remains false by default") are both now literally true;
  checkboxes left unticked per precedent. No Real-money gate item is resolved.
- Not implemented: real venue calls, automatic activation, strategy / dashboard
  / risk changes, real-money order submission (including in tests), any guessed
  venue behaviour.
- Tests: `tests/test_live_broker.py` (39) + `tests/live_broker_support.py` —
  gate off-by-default / phrase-arming / env-arming / frozen; wrapper enforces
  gate + dedupe before any `_do_*` (proved with a venue-less `RecordingLiveBroker`
  whose hooks only record); `LiveOrderRequest` validation; credential redaction
  + env isolation; `KalshiLiveBroker` / `PolymarketUsLiveBroker` every op
  `UnsupportedLiveOperationError` even when armed, and gated before that when
  not. Suite 493 → 532.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Committed to `feat/live-broker-interface` and pushed
  for review (no PR, no merge to `main`).

## 2026-09-08 — Kalshi demo authenticated read-only observation

- **First authenticated calls in the project.** Kalshi **demo** environment
  only, **GET-only** — no order submitted / cancelled / modified, `LIVE_TRADING`
  untouched, no Polymarket US call. Credentials read at runtime (demo key id
  from macOS Keychain, RSA key from `~/.config/pma/…`), never printed / logged /
  persisted / fixtured / committed; not read from env vars. Signature via
  `openssl` RSA-PSS shell-out — **no `cryptography` dependency added**.
- Tool: `scripts/observe_kalshi_demo.py` (not shipped, ruff-clean). Sanitised
  captures in `docs/evidence/kalshi-demo/*.json`. Sanitisation is
  **structure-first / fail-safe** (D-024): structure + field names + path +
  status kept; every body scalar → `<number>` / `<redacted>` unless on a short
  allowlist of fixed API constants; unknown/future fields redacted by default.
  `tests/test_observe_kalshi_demo_sanitiser.py` covers nested objects/lists and
  unexpected sensitive fields.
- OBSERVED (see `docs/API_SOURCES.md` **K-TR-OBS-01..10**): demo REST base +
  the three `KALSHI-ACCESS-*` headers + the `ts+GET+/trade-api/v2+path`
  RSA-PSS(SHA-256, MGF1-SHA256, salt=digest) signed string authenticate a real
  demo request; auth failure → **401** `{"error":{"code":"authentication_error",
  "details":<ENUM>}}` (`INCORRECT_API_KEY_SIGNATURE` / `INVALID_PARAMETER`);
  `GET /portfolio/positions` → `{market_positions:[],event_positions:[],
  cursor:""}`, `/portfolio/fills` → `{fills:[],cursor:""}`, `/portfolio/orders`
  (legacy, still live on demo) → `{orders:[],cursor:""}`;
  `GET /portfolio/events/orders` → **404 text/plain**;
  `GET /portfolio/orders/{non-uuid}` → **400 `invalid_UUID`**; no
  `X-RateLimit-*` / `Retry-After` on 2xx.
- Still open: array **element** shapes (demo account empty), well-formed-unknown
  UUID order-get, `409` duplicate-`client_order_id` and `429` bodies (need an
  order submission / load — out of scope). **No Real-money gate item resolved;
  A-037 / D-023 stand.**
- No `src/` change, no dependency, no `ASSUMPTIONS` state change.
- Follow-up (PR #19 security review): fixture sanitiser reworked from a
  key-name denylist to the structure-first allowlist above (D-024); committed
  Kalshi demo fixtures re-reduced by hand (no new network calls); deterministic
  sanitiser tests added. Evidence classifications unchanged.

## 2026-09-08 — Kalshi demo order-lifecycle observation (blocked: account not order-entry provisioned)

- Branch `obs/kalshi-demo-order-lifecycle` (from `main` after #19). Goal: place
  **one** minimal `DEMO` order to move K-TR-06..10 to OBSERVED.
- Market selected via the verified read-only `KalshiClient` (demo base): an
  `active` binary market with a **completely empty** order book, so the probe
  order (**1 contract, `yes` bid @ $0.01, `post_only`**, synthetic
  `client_order_id`, max notional $0.01) could not cross. DEMO only; production
  never called; no Polymarket US; `LIVE_TRADING` untouched; demo credentials via
  the existing Keychain + `~/.config/pma/…` pattern.
- **No order was placed.** `POST /portfolio/events/orders` → **404
  `user_not_found`** ("Exchange user not found … Exchange Sharding");
  `POST /portfolio/orders` (legacy) → **410 `deprecated_v1_order_endpoint`**.
  Every `GET /portfolio/*` on the same key still 200; positions/fills unchanged
  and empty. The demo key is read-only-provisioned — see **A-038**.
- New: `scripts/observe_kalshi_demo_order_lifecycle.py` (not shipped; reuses
  `observe_kalshi_demo` signing + D-024 `sanitise_body`; at most two create
  attempts, no schema-guess iteration, always cancels any `order_id` it
  receives). Fixtures: `docs/evidence/kalshi-demo/lifecycle/*.json`.
  `_ALLOWED_BODY_SCALARS` gained four fixed order-endpoint `error.code` /
  `error.message` constants (never `error.details`).
- OBSERVED: `docs/API_SOURCES.md` **K-TR-OBS-11..13**. **No Real-money gate item
  resolved**; K-TR-05..10 stay `VERIFIED (docs)`; A-037 / D-023 stand, A-038
  added. No `src/` change, no dependency.

## 2026-09-08 — A-038 investigation: Kalshi Exchange Sharding / demo trading provisioning (docs-only)

- Official Kalshi sources only (`docs.kalshi.com`, `help.kalshi.com`); no
  network calls to the API, no order submissions, no account changes.
- Findings recorded as `docs/API_SOURCES.md` **K-TR-14..17** (VERIFIED (docs))
  + a new gap bullet; **A-038 expanded** and kept **blocking**:
  - The probe market was a `…-SHARD1-…` ticker and `exchange_index` was omitted,
    so the order auto-routed to exchange shard 1 (K-TR-14).
  - Sharded order entry requires **preallocating collateral on that shard first**
    (K-TR-15); demo accounts are **not pre-funded** and this key's account is
    unfunded (`portfolio_value = 0`, K-TR-17 / K-TR-OBS-10).
  - Kalshi API keys are **self-service, unscoped, no approval step**, identical
    demo/prod (K-TR-16) → not a key-permission issue.
  - Remediation is self-service + documented (fund the demo account, then
    `intra_exchange_instance_transfer` / `target_balance_allocation`, check
    `GET /exchange/status`) — but requires funding + account configuration,
    which is out of scope here.
- **UNKNOWN kept:** `404` / `user_not_found` / "Exchange user not found" is
  undocumented for create-order-v2; the precise cause and whether a *different*
  demo account (vs the same one funded) is required are not stated by Kalshi.
- No evidence classification changed (K-TR-OBS-* stay OBSERVED; new rows are
  VERIFIED (docs)). No `src/` change, no dependency, no `DECISIONS` change.

## 2026-09-08 — A-038: demo shard-balance / exchange-status read-only probe

- Docs (official Kalshi only): captured the self-service **demo-funding flow**
  (K-TR-18: test debit card / Plaid sandbox / Google Pay / testnet crypto at
  `demo.kalshi.co/sign-up`; no shard step in the funding flow itself), the exact
  **`GET /portfolio/balance` `exchange_index` param** semantics (K-TR-19), and
  the **collateral move / allocate** endpoints (K-TR-20:
  `intra_exchange_instance_transfer` in centicents, `target_balance_allocation`
  `allocations[]` %; **no GET** for the current split — corrects K-TR-15).
  New sources K-TR-S15 / K-TR-S16.
- Read-only probe: new `scripts/observe_kalshi_demo_shard_balance.py` (GET-only;
  reuses `observe_kalshi_demo` signing + D-024 `sanitise_body`; signs path
  without the query string; public `/exchange/status` body kept verbatim).
  Fixtures `docs/evidence/kalshi-demo/shard-balance/*.json`. Test
  `tests/test_observe_kalshi_demo_shard_balance.py`.
- OBSERVED (`docs/API_SOURCES.md` **K-TR-OBS-14..16**): `GET
  /portfolio/balance?exchange_index=N` live on demo for N=0..3 (200, full
  4-entry `balance_breakdown` even when scoped); `GET /exchange/status`
  unauthenticated → 4 demo shards, all `trading_active` /
  `intra_exchange_transfers_active` true; the probe did **not** fund the account
  or move collateral and the redacted fixtures cannot confirm funding /
  shard-1 allocation.
- **A-038 stays blocking** — direct confirmation of demo shard
  funding/allocation is still outstanding. No Real-money gate item resolved;
  K-TR-05..10 stay `VERIFIED (docs)`; A-037 / D-023 stand. No `src/` change, no
  dependency, no `DECISIONS` change.

## 2026-09-08 — A-038: manual demo-UI shard transfer failed; GET-only diagnosis

- **Manual operator evidence** (official Kalshi demo web UI, not scripted): demo
  account funded with $100 mock cash (UI: Exchange 0 $100 / Exchange 1–3 $0); a
  manual **Exchange 0 → Exchange 1, $10** transfer returned **"Transfer failed:
  Service unavailable, please try again later."** Not retried; no order placed.
  **Cause treated as UNKNOWN** — not inferred to be funds/provisioning/capacity.
- GET-only diagnosis: new `scripts/observe_kalshi_demo_shard_transfer.py`
  (reuses `observe_kalshi_demo` signing + `observe_kalshi_demo_shard_balance._request`;
  no `POST`). Fixtures `docs/evidence/kalshi-demo/shard-transfer/*.json`
  (account bodies redacted; `/exchange/status` verbatim). Test
  `tests/test_observe_kalshi_demo_shard_transfer.py`. `observe_kalshi_demo`
  allowlist gained the transfer enum constants `pending` / `complete` /
  `event_contract` / `margined` (shape evidence only; amounts/ids/timestamps
  still redacted).
- OBSERVED (`docs/API_SOURCES.md` **K-TR-OBS-17..21**, new docs rows
  **K-TR-21** + source **K-TR-S17**): `GET /portfolio/intra_exchange_instance_transfers`
  → 200 `{"transfers": []}` (no record from the failed UI attempt);
  `GET /portfolio/target_balance_allocation` → 200 `{"allocations": []}`
  (endpoint exists — **supersedes K-TR-20's "no GET documented"**; no standing
  split); `GET /exchange/status` → all 4 demo shards + top-level
  `trading_active` and `intra_exchange_transfers_active` = true, i.e.
  **Exchange 1 reports trading and transfers active**.
- **Comparison vs documented requirements:** every read-only-observable
  precondition for an intra-exchange-instance transfer was satisfied; Kalshi
  documents no 503 / "Service unavailable" case for the transfer `POST`. The
  failure is **UNDOCUMENTED**; cause **UNKNOWN**.
- **A-038 stays blocking** — demo shard collateral cannot currently be
  allocated. No evidence classification changed (K-TR-OBS-* stay OBSERVED; new
  rows VERIFIED (docs)). No `src/` change, no dependency, no `DECISIONS` change.
  `LIVE_TRADING` untouched; no Polymarket US work.

## 2026-09-08 — A-038: demo shard transfer succeeded; GET-only confirmation

- **Manual operator evidence** (official Kalshi demo web UI): the operator
  re-attempted the `Exchange 0 → Exchange 1` **$10** transfer and it
  **succeeded**; UI then showed **Exchange 0 $90 / Exchange 1 $10**. No order
  placed; transfer not repeated.
- GET-only confirmation via `scripts/observe_kalshi_demo_shard_transfer.py`
  (now takes an optional evidence-subdir arg; run as `… shard-funded`).
  Fixtures `docs/evidence/kalshi-demo/shard-funded/*.json`.
- OBSERVED (`docs/API_SOURCES.md` **K-TR-OBS-22..25**): `GET
  /portfolio/intra_exchange_instance_transfers` now returns **one** record,
  `status = "complete"`, `source`/`destination` = `event_contract` (was `[]` at
  K-TR-OBS-18) — the retried cross-shard transfer settled, so the earlier
  "Service unavailable" was **transient**. Balances still 200 but redacted (the
  $90/$10 split rests on operator UI evidence). `target_balance_allocation`
  still `{"allocations": []}`; `/exchange/status` unchanged (all shards active).
- **A-038 stays blocking.** Demo-funding + cross-shard-transfer remediation now
  works end-to-end up to *funded shard 1*, but no order round-trip is OBSERVED
  and `POST /portfolio/events/orders` was not re-attempted since funding
  (K-TR-OBS-12's `404` unretested). K-TR-05..10 stay `VERIFIED (docs)`; A-037 /
  D-023 stand. No `src/` change, no dependency, no `DECISIONS` change.
  `LIVE_TRADING` untouched; no Polymarket US work.

## 2026-09-09 — A-038: funded-shard demo order lifecycle (submit → cancel round-trip)

- With demo shard 1 funded (K-TR-OBS-22), ran one **1-contract `yes` bid @
  $0.01, `post_only`, GTC** on the verified shard-1 demo market
  `KXMVECROSSCATEGORY-SHARD1-…` (`status = active`, empty book — cannot cross)
  and cancelled it immediately. Max risk $0.01 demo funny-money; no fill; qty
  never raised.
- Tool: `scripts/observe_kalshi_demo_order_lifecycle.py lifecycle-funded`
  (now takes an optional evidence-subdir arg; V2 cancel + single-order GET are
  **shard-routed** with `?market_ticker=`; the server `order_id` is scrubbed to
  `{order_id}` in every persisted path). New fixtures
  `docs/evidence/kalshi-demo/lifecycle-funded/*.json`; the pre-funding
  `lifecycle/` fixtures (K-TR-OBS-11/12) are kept intact.
- OBSERVED (`docs/API_SOURCES.md` **K-TR-OBS-26..33**):
  - `POST /portfolio/events/orders` → **201** with the K-TR-06 response key set
    — the K-TR-OBS-12 `404 user_not_found` was the *unfunded target shard*
    state (K-TR-OBS-12 marked SUPERSEDED).
  - Order row in `GET /portfolio/orders` carries a **superset** of the K-TR-08
    documented field names (values redacted).
  - Duplicate `client_order_id` → **409** (K-TR-07 confirmed).
  - Cancel needs shard routing: unrouted `DELETE` → 404, legacy path → 410,
    `DELETE …?market_ticker=…` → **200** `{order_id, reduced_by, ts_ms}`
    (K-TR-10 updated with the query params). Same routing rule for single-order
    GET.
  - Post-cancel `?status=resting` list empty; `positions` / `fills` empty; an
    independent re-check showed 0 resting / 0 fills / 0 positions, every demo
    order `canceled`.
- **A-038 → RESOLVED (demo-observation scope).** It never governed the
  real-money gate; live/real-money trading stays disabled by **D-002** and
  **A-037 / D-023** (`live_broker` is an interface boundary only). Still
  doc-only: per-fill rows (K-TR-09), partial-fill reporting, and all redacted
  order values. `ASSUMPTIONS.md` A-038 "Blocks live use?" → No.
- No `src/` change, no dependency, no `DECISIONS` change. `LIVE_TRADING` never
  read or set; production Kalshi never called; no Polymarket US work.

## 2026-09-09 — ROADMAP.md reconciliation with repository state

- Ticked the milestone checklists whose deliverables are proven on `main` by a
  merged PR + a source package + dedicated deterministic tests (556 passing) +
  a detailed journal entry: **M1.2, M1.3** (6/6 each — live OBSERVED
  verification + sanitized fixtures), **M1.4** (3/3), **M2.1** (6/6), **M2.2**
  (6/6), **M2.3** (1/1), **M2.4** (7/7), **M2.5** (9/9), **M3.1** (8/8),
  **M3.2** (9/9), **M3.4** (2/2).
- **Left unchecked (evidence does not support completion):**
  - M1.5 "Same-market complete-set logic" — engine is buy/buy only; `IDENTICAL`
    deferred to execution work (`arbitrage/engine.py`; D-012).
  - M1.5 "Slippage reserve" — only a generic `execution_buffer_per_unit`
    exists; nothing names a slippage reserve and slippage modelling is deferred
    to M2.4.
  - M3.3 "Leg-risk events" — the report section is permanently "unavailable"
    (no recorder leg-risk table; D-022).
- **Real-money gate: unchanged, every item stays locked.** Demo order-lifecycle
  evidence (A-038) is demo-observation scope only; live/real-money execution
  stays blocked by D-002 and A-037 / D-023 (`live_broker` is an interface
  boundary; no signed venue order is possible; Polymarket US trading API has no
  primary evidence).
- Documentation change only — no `src/` change, no test change, no dependency,
  no `DECISIONS` / `ASSUMPTIONS` change. `ROADMAP.md` remains authoritative;
  box-ticking is a review step and these can be reverted by review.

## 2026-09-09 — M1.5 same-market complete-set arbitrage

- Added `ArbitrageEngine.evaluate_complete_set(books, *, evaluation_time,
  requested_quantity=None)` → new `CompleteSetEvaluation` (exported from
  `arbitrage/__init__.py`). Branch `feat/m1.5-complete-set` off `origin/main`
  (M1.5..M3.4 + roadmap reconcile merged). **No new dependency.**
- Buys one unit of **every** mutually exclusive outcome of one market on one
  venue; a matched set pays exactly `executable_quantity` at settlement, so
  `gross_edge = size − Σ acquisition_cost`, `net_edge = size − (gross +
  fees + execution_buffer)`, opportunity iff `net_edge > 0` (exact break-even
  is not one). Reuses the `evaluate` conventions verbatim: exact `Decimal`,
  `_walk_asks` depth-walking, `executable_quantity = min(ask depth over every
  outcome, max_quantity, requested_quantity)`, injected `FeeModel` summed per
  outcome, `max_book_age` / `max_cross_book_skew` (max−min timestamp),
  `require_full_fill`.
- **No registry** — there is no equivalence question for the outcomes of one
  market. The engine verifies only same venue+market, distinct contracts, ≥ 2
  books; "complete + mutually exclusive" is a caller assertion (**A-039**).
  `CompleteSetEvaluation.to_opportunity()` maps a binary set to the domain
  `Opportunity`; a categorical (> 2) set raises.
- Records **D-025** (registry-free method, not a `MarketPairRecord` extension;
  D-012's "does not implement complete-set" superseded in part); **A-039**;
  `docs/ARBITRAGE_METHODOLOGY.md` §1a. `docs/ROADMAP.md` M1.5 "Same-market
  complete-set logic" ticked (M1.5 now 8/9; "Slippage reserve" still the only
  open M1.5 item — not implemented here).
- Not implemented: slippage reserve, new venue adapters, live execution,
  recorder / reporting changes, Polymarket US changes. The cross-venue
  `evaluate` path is untouched.
- Tests: `tests/test_arbitrage_complete_set.py` (30) + an `outcome_book`
  builder in `tests/arbitrage_support.py` — profitable / breakeven /
  unprofitable / insufficient-depth (capped + `require_full_fill` reject) /
  stale-data (+ future-stamp + skew), depth-weighted multi-level cost,
  `max_quantity` cap, fees summed across outcomes, execution buffer, 3-way
  categorical set, `to_opportunity` (binary + categorical-raises +
  no-opportunity-raises), misuse (< 2 books / non-OrderBook / mixed venue /
  mixed market / duplicate outcome / naive time / non-positive + float
  requested qty), exact Decimal precision. Suite 556 → 586.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-09 — M1.5 explicit slippage reserve (last M1.5 item)

- Added `EngineConfig.slippage_reserve_per_unit: Decimal = _ZERO` — a **peer**
  of `execution_buffer_per_unit`, not a rename or fold-in (D-026). Validated
  finite `>= 0`. Branch `feat/m1.5-slippage-reserve` off `origin/main`
  (M1.5 complete-set #27 merged). **No new dependency.**
- Both `evaluate` and `evaluate_complete_set` compute
  `slippage_reserve = slippage_reserve_per_unit * executable_quantity` and add
  it to `net_total_cost` alongside fees + execution buffer;
  `net_edge = size − net_total_cost`; opportunity iff `net_edge > 0`. Both
  `OpportunityEvaluation` and `CompleteSetEvaluation` gain a `slippage_reserve`
  field (audit trail). Exact `Decimal`, no internal rounding. `0` (the default)
  reproduces the pre-reserve result byte-for-byte.
- `recorder` untouched — `record_opportunity` reads a fixed field list; the
  `opportunities` table records `net_total_cost` / `net_edge` (which include the
  reserve) but has no separate `slippage_reserve` column (a versioned schema
  change, out of scope; same limitation as per-leg fees). No paper-broker /
  dashboard / risk / adapter / Polymarket US changes; `LIVE_TRADING` unchanged.
- Records **D-026**, **A-040** (the reserve is a caller-chosen parameter with no
  venue-microstructure backing — like the injected `FeeModel`).
  `docs/ARBITRAGE_METHODOLOGY.md` §0/§2 updated. **`docs/ROADMAP.md` M1.5
  "Slippage reserve" ticked — M1.5 is now 9/9 complete.**
- Tests: `tests/test_arbitrage_engine.py` +9, `tests/test_arbitrage_complete_set.py`
  +6 — zero reserve reproduces the baseline, positive reserve reduces net edge
  deterministically, reserve scales with executable quantity, pushes an
  opportunity to exact break-even, makes one unprofitable, stacks with
  fees + execution buffer, invalid values (negative / NaN / Infinity / float)
  rejected, and the complete-set path (binary + categorical). Suite 588 → 603.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-09 — M3.3 recorder-backed leg-risk events (last M3.3 item)

- Branch `feat/m3.3-leg-risk-events` off `origin/main` (M1.5 slippage #28
  merged). **No new dependency; recorder not redesigned.**
- **Recorder** — new append-only `leg_risk_events` table + `seq_leg_risk_events`,
  a `LegRiskEventRow` value-object, and `Recorder.record_leg_risk_event`.
  `LegRiskEventRow` **fails closed** on `unhedged_quantity == 0` (a balanced
  measurement is not an event — the metric can't be padded with synthetic
  zeros). `SCHEMA_VERSION` stays **1**: every table is `CREATE TABLE IF NOT
  EXISTS`, so an older recording re-opened by the new build additively gains
  the table; the version tracks existing tables' column shape, unchanged
  (D-027).
- **Paper broker** — `LegRiskSnapshot.is_leg_risk_event` /
  `to_leg_risk_event_row()` bridge the existing on-demand `leg_risk(a, b, …)`
  measurement to the recorder row. Dependency stays paper_broker → recorder.
- **Replay** — `RecordedLegRiskEvent`, `ReplaySession.leg_risk_events()` (exact
  `Decimal` + UTC round-trip), `has_leg_risk_stream()`, a `leg_risk` timeline
  kind + `counts()` entry. A recording whose DB predates the table →
  `has_leg_risk_stream()` False, empty stream, `counts()['leg_risk'] == 0`.
- **perf_report** — `LegRiskStats` gains `events` / `temporary_events` /
  `unresolved_events` / `order_pairs_affected` / `max_abs_unhedged_quantity` /
  `unhedged_notional` (`Stats` over priced events); `build_report` aggregates
  `session.leg_risk_events()` when the stream exists, else keeps the
  "unavailable, not 0" behaviour. `render_text` prints the LEG RISK section.
- Records **D-027**; supersedes D-022's "leg-risk unavailable" and A-036's "not
  persisted" for recordings made by this build. `docs/ROADMAP.md` M3.3
  "Leg-risk events" ticked → **M3.3 is now 8/8 complete.**
- Not touched: live execution, `LIVE_TRADING`, venue adapters, Polymarket US,
  M1.5. Recorder additive only (no column change to any existing table, no
  migration).
- Tests: `tests/test_leg_risk_events.py` (new, 5 — persist → replay exact
  Decimal/UTC → timeline → perf aggregation → determinism → legacy-DB
  unavailable path), `tests/test_paper_broker.py` +3 (no event when both fill;
  temporary exposure + row conversion; unresolved/both-terminal),
  `tests/test_recorder.py` +4 (exact persist; NULL optionals; non-row reject;
  zero-unhedged reject), `tests/test_perf_report.py` 2 updated (leg-risk zero
  is now a real 0 with the table present). Suite 603 → 615.
- Gates: `ruff check .`, `mypy src tests`, `pytest`, `pre-commit run
  --all-files` all pass. Not committed — awaiting request.

## 2026-09-09 — Real-money gate audit (audit only; no checkboxes changed)

Reviewed all 15 unchecked `docs/ROADMAP.md` Real-money gate items against
repository evidence. **Result: 0 / 15 legitimately checkable** under "Real money
remains locked until all are verified." Every item needs live/production
exchange evidence (not demo), an OBSERVED fill, an integration that does not
exist, a manual pair review, or resolution of a Polymarket US doc conflict.
Classification + smallest next action per item (DEMO evidence flagged as such):

| # | Item | Class | Evidence | Checkable? |
|---|------|-------|----------|-----------|
| 1 | Official API behavior | OBSERVED (Kalshi **demo** only) / UNKNOWN (Polymarket US, prod Kalshi) | K-TR-OBS-26..33 (demo create/cancel/dup-409/reads); all P-TR-* = `VERIFIED (docs)` with open UNKNOWNs; A-038 "RESOLVED demo scope — does NOT lift the gate" | No |
| 2 | Stable live market data | OBSERVED production REST (snapshot init + a 5-min sustained live session, K-MD-OBS-01..03, 2026-09-09) / UNKNOWN for the live WS feed | `scripts/observe_kalshi_prod_market_data.py`, `docs/evidence/kalshi-live/market-data/`; **A-030** (prod WS needs auth — K-WS-01 — no prod credential; loopback only), **A-028** (Kalshi delta semantics UNVERIFIED) | No — REST half only; the stable-feed core is unverified |
| 3 | Successful paper execution | TESTED (sim) / ASSUMPTION | `tests/test_paper_broker.py`; **A-003** UNVERIFIED; no live-data→engine→broker→recorder session ever run | No |
| 4 | Fee reconciliation | VERIFIED (docs) formula / UNKNOWN reconciliation | M1.6 `arbitrage/fees.py`, A-024/A-025/A-026; ASSUMPTIONS "models do not resolve fee reconciliation"; no OBSERVED fee-vs-computed (demo produced no fill) | No |
| 5 | Contract equivalence | TESTED (gate mechanism) / ASSUMPTION | `tests/test_market_pair_registry.py`; `registry/data/market_pairs.toml` has **zero** records; **A-001** UNVERIFIED | No |
| 6 | Partial-fill behavior | TESTED (paper) + VERIFIED (docs both venues) / UNKNOWN OBSERVED | `test_paper_broker.py`; K-TR-08 / P-TR-06 (docs); K-TR-OBS-32 — no fill produced | No |
| 7 | Stale-data handling | TESTED / residual UNKNOWN (live feed) | `test_livebook_state.py`, `test_failure_scenarios.py`; depends on A-028/A-030 for the real trigger | No |
| 8 | Disconnect/reconnect | TESTED (incl. real socket on loopback) / UNKNOWN (real venue) | `test_livebook_transport.py`, `test_livebook_ws_transport.py`, `test_failure_scenarios.py`; **A-030** | No |
| 9 | Duplicate-order prevention | TESTED (local) + OBSERVED (Kalshi **demo** 409) / UNKNOWN (Polymarket US, prod) | `IdempotencyGuard` `test_live_broker.py`; K-TR-OBS-29; **P-TR-10** doc conflict (no retail `ClOrdID` field documented) | No |
| 10 | Position/order reconciliation | OBSERVED (Kalshi **demo**, cancelled-order path only) / UNKNOWN (filled position, Polymarket US) | K-TR-OBS-31/32/33; `live_broker.get_order`/`get_positions` raise `UnsupportedLiveOperationError` (A-037) | No |
| 11 | Kill switch | TESTED (mechanism) / not integrated | `risk/manager.py`, `test_risk_manager.py`, A-034; `live_broker/` does **not** import `risk` — no live order path to stop | No |
| 12 | Position limits | TESTED (mechanism) / not integrated | `risk/limits.py` `max_position`; same non-integration as #11 | No |
| 13 | Daily loss limits | TESTED (mechanism) / not integrated + needs real PnL feed | `risk/state.py` per-UTC-day ledger; same non-integration as #11 | No |
| 14 | Credential isolation | TESTED (types/env/redaction) / isolated trading-cred path never authenticated a call | `live_broker/credentials.py`, `test_live_broker.py`, A-037; the demo lifecycle used the market-data Keychain key, not `KalshiTradingCredentials` | No |
| 15 | Live mode cannot activate accidentally | TESTED (comprehensively) / A-037 records it as still-blocking | `live_broker/gate.py` frozen, phrase-only, env ignores `1`/`true`; `test_live_broker.py` (39); every adapter raises `UnsupportedLiveOperationError`. **A-037 explicitly lists this item as still requiring a live run.** | No (per A-037; closest to checkable — needs a decision) |

**Smallest next action per item:** 1 → prod-Kalshi + Polymarket US authenticated
read-only capture; 2 → one authenticated live Kalshi WS connect with a real
`Signer`, capture `orderbook_snapshot`+`orderbook_delta`+a reconnect (also
closes 7, 8, A-030, A-028); 3 → run the live-data→M1.5→M2.4→M2.2 loop for one
session; 4/6 → one small demo Kalshi *fill* and compare venue fee + partial-fill
fields; 5 → D-006 manual review of one real pair → VERIFIED record; 9 → resolve
P-TR-10, then a Polymarket US duplicate-submit observation; 10 → a demo Kalshi
round-trip that fills, reconcile local vs `GET /portfolio/fills|positions`;
11–13 → wire `RiskManager` into the `LiveBroker` submit path + integration tests
(code — out of audit scope); 14 → one authenticated read-only trading call using
`kalshi_trading_credentials_from_env`; 15 → a decision on whether the
deterministic gate tests + `UnsupportedLiveOperationError` floor satisfy it
(no exchange dependency), superseding A-037's claim, or define the live check.

**Recommended next item: #2 (Stable live market data)** — highest leverage
(also unblocks 7, 8 and resolves A-030 + A-028), fully read-only (no orders, no
funds). Prerequisite: a `Signer` implementation (currently caller-supplied, not
in the repo).

No ROADMAP checkbox changed. Doc note added to `docs/API_SOURCES.md` "Real-money
gate status" (its 2026-09-08 "no authenticated trading request on either venue"
line predated the K-TR-OBS-26..33 demo lifecycle). No code, no network calls,
no `LIVE_TRADING` change.

## 2026-09-09 — Real-money gate #2 attempt: production live market data (REST only; item stays unchecked)

- **Blocker/conflict surfaced first:** the task asked for a bounded live
  **production** market-data session covering WebSocket connect / message
  receipt / `seq` handling / disconnect+reconnect. Repository evidence
  **K-WS-01** says Kalshi's production market-data WS requires an authenticated
  handshake (public channels included); there is **no production Kalshi
  credential** in this environment (only the demo key), and the task forbids
  creating credentials, substituting demo for production, and implementing a
  Signer for a non-required path. So the WS half could not be done.
- **What was done (smallest safe available path):** new
  `scripts/observe_kalshi_prod_market_data.py` — unauthenticated, read-only
  production REST polling (K-09 public). One bounded session: pick an active
  market from `KXBTCD`/`KXBTC`/`KXETHD` by observed two-sided depth, then poll
  `GET /markets/{ticker}/orderbook` + `GET /markets/{ticker}` every 6 s for
  300 s. Sanitised evidence in `docs/evidence/kalshi-live/market-data/`
  (SUMMARY + a structure-only orderbook sample — every price/size → a token).
- **OBSERVED (production):** `KXBTCD-26SEP0904-T84299.99`, 44 polls / 300.2 s
  (`2026-09-09T07:28:05Z…07:33:05Z`), HTTP-status histogram `{200: 44}`,
  market `status` `"active"` throughout, **8 distinct book states / 7 changes**
  (max ~64 s between changes) → a real sustained session with a live book, not
  a smoke test. REST snapshot init returns the documented `orderbook_fp` shape
  (K-05/K-06). A REST-level unreachable-host probe raised `URLError`; the next
  real GET returned 200 (recorded as K-MD-OBS-03, explicitly **not** a WS
  reconnect). Rows K-MD-OBS-01..04 in `docs/API_SOURCES.md`.
- **NOT verified:** WS connection, real `orderbook_snapshot`/`orderbook_delta`
  receipt, per-subscription `seq` / snapshot-then-delta ordering, stream
  disconnect detection, reconnect + `get_snapshot` resync, `LiveBookFeed`
  `HealthStatus` transitions across a reconnect. **A-030 / A-028 stay
  UNVERIFIED.**
- **Gate impact:** #2 "Stable live market data" stays **unchecked** — the
  stable-**feed** core is unverified; REST polling is not the feed the M2.1
  code or the gate item concern. #7 (stale-data handling) and #8
  (disconnect/reconnect) are **not** advanced — both need the WS reconnect
  path. Recommended next: a production Kalshi API key + an RSA-PSS signer, then
  one authenticated `wss://external-api-ws.kalshi.com/trade-api/ws/v2` session.
- No orders, no funds, no balances/positions/fills (unauthenticated), no
  `LIVE_TRADING`, no credential change, no Polymarket US, no risk/execution
  code. Tests: `tests/test_observe_kalshi_prod_market_data.py` (4, offline —
  the sanitiser / book-parse helpers). Full gate green. Not committed.

## 2026-09-09 — Kalshi production authenticated WS: auth re-verified + read-only observation path prepared (not run)

- **Goal:** the minimum auth/signing support to later run a read-only
  authenticated Kalshi **production** market-data WebSocket session — code +
  tests ready, nothing executed.
- **Docs re-verified** against official Kalshi sources (WS-A-S1
  `quick_start_websockets`, WS-A-S2 `quick_start_authenticated_requests`). Every
  production WS auth fact is **unchanged** from K-WS-AUTH-01..04: URL
  `wss://external-api-ws.kalshi.com/trade-api/ws/v2`; headers
  `KALSHI-ACCESS-KEY` / `-TIMESTAMP` (Unix **ms** string) / `-SIGNATURE`
  (base64); signed message `timestamp + "GET" + "/trade-api/ws/v2"`; RSA-PSS,
  MGF1-SHA256, salt = digest length, SHA-256. New rows K-WS-AUTH-05..08 in
  `docs/API_SOURCES.md`. Only drift noted: the key-creation UI wording is now
  "Account & security → API Keys → Create Key" (K-TR-16 recorded the older
  "Profile Settings …"); same self-service, unscoped, no-approval flow.
- **Credential requirement:** a standard Kalshi API key (RSA key pair). There is
  **no** read-only vs trading key type and no scopes — same key type for demo
  and production, only the host differs. **No production key exists here** and
  the repo must not create one — the operator creates it manually in the Kalshi
  web UI, downloads the PEM once, stores the key id in the macOS Keychain
  (`pma-kalshi-prod-api-key-id`) and the PEM at
  `~/.config/pma/kalshi-prod-private-key.pem` (mode 600).
- **One signer, read-only by construction:** the signature is RSA-PSS/SHA-256
  over an opaque string with no method/endpoint meaning, so the same key signs
  REST and WS identically (K-TR-03 ≡ K-WS-AUTH-03). The signer cannot grant or
  block execution (keys are unscoped); read-only is enforced by the calling
  script only issuing market-data WS frames + public `GET /markets` — no
  `/portfolio`, no order endpoints.
- **Changed:**
  - `scripts/kalshi_signer.py` — `OpensslRsaPssSigner` (implements
    `livebook.Signer` via an `openssl` subprocess, no `cryptography` dep, same
    approach as `observe_kalshi_demo.py`) + `read_keychain_password`. Private
    key read from a file path only; never env/CLI/logged; `repr` shows the path
    only.
  - `scripts/observe_kalshi_prod_ws_market_data.py` — default `--check` runs a
    local preflight and prints the manual key-creation step; **opens no socket**.
    `--observe` refuses unless `PMA_KALSHI_PROD_WS_OBSERVE=1` **and** preflight
    passes; only then does it connect + subscribe one market's `orderbook_delta`
    + record `seq` and a sanitised snapshot/delta + disconnect + reconnect +
    resubscribe (fresh snapshot = resync) + disconnect.
  - `tests/test_kalshi_signer.py` (offline — generates a throwaway RSA key with
    `openssl`, round-trip verifies incl. through `kalshi_ws_handshake`;
    Keychain lookup stubbed).
  - `tests/test_observe_kalshi_prod_ws_market_data.py` (offline — `--check`
    opens no socket, `--observe` refuses without the env guard, stream consumer
    sends only `subscribe`, sanitiser tokenises scalars, no account/order path
    literal or trading import in the module).
  - Doc updates: `API_SOURCES.md` (K-WS-AUTH-05..08 + transport-status note),
    `ASSUMPTIONS.md` (A-030 / A-028 detail: signer now exists, still
    docs-only), this entry.
- **Ready for observation:** yes, pending one manual step — the operator creates
  a production Kalshi API key (Kalshi web UI → **Account & security → API Keys →
  Create Key**), stores the id in the Keychain and the PEM at the path above,
  then runs `PMA_KALSHI_PROD_WS_OBSERVE=1 python
  scripts/observe_kalshi_prod_ws_market_data.py --observe`.
- **Not done / unchanged:** no production API key created, no authenticated
  production network call, no order/balance/position/fill access, no
  `LIVE_TRADING`, no Polymarket US, no execution wiring. **A-030 / A-028 stay
  UNVERIFIED**; Real-money gate items **#2 / #7 / #8 remain unchecked**. Full
  local gate green. Not committed.

## 2026-09-09 — Kalshi production authenticated WS session: OBSERVED (gate #2/#7/#8 stay unchecked)

- **What ran:** the operator created a production Kalshi API key manually
  (Kalshi web UI), stored the id in the Keychain + the PEM at
  `~/.config/pma/kalshi-prod-private-key.pem`, and ran
  `PMA_KALSHI_PROD_WS_OBSERVE=1 python scripts/observe_kalshi_prod_ws_market_data.py --observe`
  once. One ~35 s session, `2026-09-09T15:29:36Z…15:30:12Z`, two connections.
  Sanitised evidence: `docs/evidence/kalshi-live/ws-market-data/SUMMARY.json`.
- **OBSERVED (production) — K-WS-OBS-01..08 in `API_SOURCES.md`:**
  - The RSA-PSS handshake built by `livebook.ws_auth.kalshi_ws_handshake` +
    `scripts.kalshi_signer.OpensslRsaPssSigner` was **accepted by the real
    Kalshi server** on both connections (`wss://external-api-ws.kalshi.com/trade-api/ws/v2`).
  - `subscribe` body (K-WS-AUTH-04) accepted; the ack frame type is
    `subscribed` (not `ok`).
  - `orderbook_snapshot` received + decoded on both connections
    (`decode_orderbook_snapshot` accepted the real frame; `yes_dollars_fp`
    absent = one-sided book, allowed by K-WS-03).
  - `orderbook_delta` received + decoded once, on the reconnect session
    (`decode_orderbook_delta` accepted it; both `ts_ms` int and deprecated `ts`
    string present — K-WS-04).
  - Per-subscription `seq` sequential: snapshot `seq=1` → delta `seq=2`,
    strictly increasing; `seq` **resets to 1** for a new subscription on a new
    connection (per-subscription, not global).
  - Clean disconnect (`t1.close()`) → reconnect with a fresh handshake →
    resubscribe → the channel re-sent a **fresh `orderbook_snapshot`** (then a
    delta): the "resubscribe = full resync" path (K-WS-02) proven end-to-end
    against prod.
- **NOT observed (K-WS-OBS-08):** a sustained multi-minute feed; more than one
  delta (the first connection idle-timed-out after its snapshot); an
  unexpected / server-side disconnect and its detection; `LiveBookFeed` /
  `FeedHealth` `HEALTHY → DISCONNECTED → RESYNCING → HEALTHY` transitions (the
  script drove `WebsocketsTransport` + decoders directly, never
  `LiveBookConnection`); staleness gating; **A-028** additive-delta application.
- **Assumptions:** **A-030 — Kalshi half resolved** (handshake / subscribe /
  snapshot / delta formats match the live production server); Polymarket US half
  still UNVERIFIED (no live handshake; P-WS-AUTH-03 casing/enum discrepancy
  open). **A-028 unchanged** (UNVERIFIED — the one delta was decoded, never
  applied).
- **Gate impact — no checkbox flips:**
  - **#2 "Stable live market data":** unchecked. Authenticated WS connect +
    snapshot + one delta + `seq` ordering are now OBSERVED, but "stable /
    sustained live feed with healthy state throughout" is not — ~35 s, one
    delta, no `FeedHealth` tracking.
  - **#7 "Stale-data handling":** unchecked, not advanced — no staleness event,
    no `LiveBookFeed` gating exercised against the live feed.
  - **#8 "Disconnect/reconnect behavior":** unchecked. The resubscribe/resync
    *mechanism* now works against prod, but the run used a clean client-side
    close (not an unexpected drop) and captured no health-state recovery.
- **Not done:** no additional network calls, no orders, no balances/positions/
  fills, no funds, no `LIVE_TRADING`, no credential change in the repo, no
  Polymarket US. ROADMAP unchanged. Docs updated: `API_SOURCES.md`
  (K-WS-AUTH-08 → EXECUTED; K-WS-OBS-01..08; gate #2 verdict; transport-status
  note), `ASSUMPTIONS.md` (A-030 partly resolved), this entry. No code/logic
  change → no new tests; existing gate still green from the prior pass. Not
  committed.

## 2026-09-09 — Kalshi production live-book *runtime* observation: gate #2 CHECKED; #7/#8 stay unchecked; A-028 → OBSERVED

- **Goal:** advance real-money gates #2/#7/#8 by running a bounded production
  read-only observation through the **shipped runtime**
  (`livebook.LiveBookConnection` + `LiveBookFeed` + `WebsocketsTransport` + a
  REST `SnapshotSource` over `KalshiMarketDataAdapter`), not the standalone WS
  script. One market wired through; read-only market data only.
- **New:** `scripts/observe_kalshi_livebook_runtime.py` (`--check` preflight /
  `--observe` env-guarded). Phases: A REST-snapshot init → B WS subscribe +
  sustained delta consumption → C staleness probe (pause consumption
  > `max_staleness`) → D one induced socket drop + detection → E reconnect +
  resync → F resume. Sanitised evidence
  `docs/evidence/kalshi-live/livebook-runtime/SUMMARY.json` (phase timeline with
  UTC timestamps, per-feed `HealthStatus`/`trading_enabled`/`last_sequence`,
  `DeltaOutcome` tallies, per-subscription `seq` epochs, value-free book
  fingerprints, A-028 additive check). No `/portfolio`, order, balance/position/
  fill; `LIVE_TRADING` untouched; no Polymarket US.
- **Bug found + fixed (D-028 / K-LB-OBS-12):** `WebsocketsTransport` did not
  release `_conn`/`_cm` when a socket closed, so `LiveBookConnection.reconnect()`
  → `connect()` raised "already connected" — the reconnect path was broken
  against any real socket. Fix: `receive()`/`send()` also catch `OSError` and
  call a new `_release()`; `close()` delegates to it. Targeted tests added
  (`test_livebook_ws_transport.py`: release-then-reconnect; full
  `LiveBookConnection` drop→reconnect→resync over the loopback server).
- **OBSERVED (production, session 2026-09-09T21:04:53Z…21:05:57Z, ~64 s, market
  `KXBTCD-…`) — K-LB-OBS-01..12 in `API_SOURCES.md`:**
  - REST-snapshot init → both feeds `UNINITIALIZED → HEALTHY`.
  - WS subscribe via the runtime → **30** `orderbook_delta` applied over **~14 s
    of continuous consumption**, `delta_outcomes = {applied: 30}` (no other
    outcome), **0** desyncs, per-subscription `seq` strictly monotone 2→16,
    both feeds `HEALTHY` throughout; **17** more buffered deltas applied cleanly
    later. Book fingerprint changed **32** times.
  - **A-028:** for every APPLIED delta, `qty_after == qty_before + delta_fp`,
    with the level removed when the sum hit 0 (**6** removals) — **34/34**
    checked, 0 mismatches, 0 desyncs across ~51 real deltas. Raw quantities not
    persisted. **A-028 → OBSERVED** (narrow: one market/session).
  - **Staleness:** consumption paused 35 s → `LiveBookFeed.health()` = `STALE`,
    `trading_enabled = false` on both feeds, from the feed's real `_last_update`.
  - **Disconnect:** socket dropped abruptly → 17 buffered frames drained, then
    `pump_one()` raised `TransportClosed`; `handle_disconnect()` → both feeds
    `DISCONNECTED`, `trading_enabled = false`.
  - **Recovery:** `reconnect()` succeeded first attempt → still `DISCONNECTED`
    (`healthy_before_resync = false`) → `resync()`: `RESYNCING` → fresh REST
    snapshot (fingerprints differ from init — book moved) → both feeds
    `HEALTHY`. Full path `UNINITIALIZED→HEALTHY→STALE→DISCONNECTED→RESYNCING→HEALTHY`.
- **Gate reassessment:**
  - **#2 "Stable live market data" → CHECKED (ROADMAP updated).** A real,
    stable live feed through the actual runtime: sustained `seq`-ordered delta
    stream, 0 desyncs, `HEALTHY` throughout, book mutating. Resolves the earlier
    "REST polling is not the feed" caveat.
  - **#7 "Stale-data handling" → stays unchecked.** The `STALE` verdict is real
    but was **induced by pausing consumption**, not a naturally quiet market;
    `STALE → HEALTHY` recovery not observed.
  - **#8 "Disconnect/reconnect behavior" → stays unchecked.** The full
    detection → unhealthy → reconnect → resync → healthy-only-after-resync cycle
    is OBSERVED through the runtime, but the disconnect **trigger was
    harness-induced** (local socket drop), not a server/network drop; reconnect
    used 0 backoff retries.
- **Not done:** no orders, no cancel/modify, no balances/positions/fills, no
  funds, no `LIVE_TRADING`, no credential change, no production execution
  wiring, no Polymarket US, no broadening of signer use. Full local gate green
  (657 tests). Not committed.

## 2026-09-09 — Kalshi production runtime: stale (#7) + disconnect/reconnect (#8) follow-up — both stay unchecked

- **Goal:** resolve real-money gates #7 (stale-data handling) and #8
  (disconnect/reconnect) with production evidence through the shipped runtime,
  without pausing consumption for #7. Branch
  `obs/kalshi-livebook-stale-reconnect` off `main` @ 1090665.
- **Harness changes (`scripts/observe_kalshi_livebook_runtime.py`):** split into
  two bounded read-only modes. `--observe` (gate #8): unchanged flow **minus the
  consumption pause** — the induced socket drop now hits genuinely `HEALTHY`
  feeds. `--observe-stale` (gate #7): **new** `watch_staleness_lifecycle` —
  consumes continuously via `pump_one()`, samples `LiveBookFeed.health()` and
  the fail-closed `current_order_book(now, require_healthy=True)` between reads,
  looks for a natural `HEALTHY → STALE → HEALTHY` round trip; `pick_moderate_market`
  probes for an alive-but-thin market. Evidence now in `SUMMARY_RECONNECT.json`
  and `SUMMARY_STALE.json` (original `SUMMARY.json` retained). New offline tests
  for both functions + `--observe-stale` guards. No runtime/logic change.
- **OBSERVED — #8 (`SUMMARY_RECONNECT.json`, session 2026-09-09, liquid BTC-daily
  market, ~20 s; K-LB-OBS-13..15):** 8 applied deltas → `all_healthy() == true`
  confirmed pre-drop → one induced socket close → `pump_one()` raised
  `TransportClosed` (0 buffered frames) → `handle_disconnect()` both feeds
  `DISCONNECTED`/`trading_enabled=false` → `reconnect(time.sleep)` succeeded
  attempt 0 (fresh RSA-PSS handshake + K-WS-AUTH-04 subscribe) → still
  `DISCONNECTED` (`healthy_before_resync=false`) → `resync()` fresh REST snapshot
  → both `HEALTHY` → 4 more real deltas, new `seq` epoch 2→3,
  `delta_outcomes={applied:12}`, 0 desyncs. Clean
  `HEALTHY→DISCONNECTED→HEALTHY-after-resync` (improves on the gate-#2 pass where
  feeds were already `STALE` at the drop).
- **BLOCKED — #7 (`SUMMARY_STALE.json`; K-LB-OBS-16..17, D-029):** no natural
  stale lifecycle captured in a bounded window. Two independent reasons: (a) the
  public `GET /markets?status=open` listing is all empty-book
  `KXMVECROSSCATEGORY-SHARD1-*` markets, and the only reliably two-sided live
  markets are the crypto firehose (observed `max_pump_gap_s=6.685` over ~90 s,
  400 deltas, `empty_pumps=0`); (b) architectural — `pump_one()` blocks in
  `receive()` between deltas, so a continuously-consuming caller can't sample
  `health()` during a quiet gap, and `recv_timeout` treats a quiet socket as a
  dead one. Recorded as an accepted gap (D-029); harness keeps the mode for a
  later capture.
- **Gate reassessment:**
  - **#2** unchanged (still CHECKED).
  - **#7 "Stale-data handling" — STAYS UNCHECKED.** Fail-closed staleness
    behaviour is correct in tests and K-LB-OBS-07, but the natural end-to-end
    lifecycle is not OBSERVED. Blocker D-029 / K-LB-OBS-16..17.
  - **#8 "Disconnect/reconnect behavior" — STAYS UNCHECKED (materially
    strengthened).** Full runtime recovery from healthy feeds is now OBSERVED
    (K-LB-OBS-13..15). Two items remain before a reviewer checks it: a
    **spontaneous** (server/network) disconnect rather than a harness-induced
    socket close, and `BackoffPolicy` retry/backoff exercised live
    (`reconnect_attempts` was 0 — backoff stays TESTED-only). *Note: the task
    prompt's stated #8 standard permits a harness-induced drop through the normal
    path; the repo's prior verdict additionally wants a spontaneous drop and
    backoff > 0. Left unchecked pending the gate owner's call on that criteria
    conflict.*
- **A-028** unchanged (OBSERVED, narrow — no new additive-delta check this pass).
- **Not done:** no orders, no cancel/modify, no balances/positions/fills, no
  funds, no `LIVE_TRADING`, no credential change, no execution wiring, no
  Polymarket US, no runtime/architecture change. ROADMAP real-money gate
  checkboxes unchanged. Full local quality gate run once after the code change.
  Not committed.

## 2026-09-09 — Real-money gate audit: #9 / #11 / #12 / #13 / #14 / #15 — none completed; offline behaviour hardened

- **Goal:** audit the six non-market-data real-money gates for whether current
  repository evidence already meets the verification standard, and close any
  small deterministic test gap. Branch `obs/realmoney-gates-9-11-15` off `main`
  @ 973ea07. No architecture change, no network, no orders/balances/funds, no
  `LIVE_TRADING`, no Polymarket US.
- **Finding — repository evidence already adjudicates these gates.** `A-037`
  and `D-023` state explicitly that the M3.4 `live_broker` package "does **not**
  resolve any Real-money gate item" and that "Live mode cannot activate
  accidentally", "Duplicate-order prevention", and "Credential isolation" are
  *supported* by the boundary but **not verified — verification needs a captured
  trading API and a live reconciliation run.** No box is checked; per AGENTS.md
  the prompt cannot promote an assumption to fact.
- **Per-gate classification (evidence status):**
  - **#9 Duplicate-order prevention — TESTED (local half) / ASSUMPTION (venue).**
    `IdempotencyGuard.register()` runs in `LiveBroker.submit_order` before
    `_do_submit`; a repeat `client_order_id` raises `DuplicateOrderError`,
    including after a submit whose hook already failed downstream, and on the
    concrete `KalshiLiveBroker`. No execution intent is produced at all (every
    `_do_submit` raises `UnsupportedLiveOperationError`). Venue-side idempotency
    is unverified (A-037). **Not complete.**
  - **#11 Kill switch — TESTED (veto behaviour), NOT on an execution path.**
    `RiskManager._check_kill` rejects in both `evaluate_order` and
    `evaluate_opportunity` when `RiskState.killed`; deterministic, fail-closed.
    Nothing forces a caller through `RiskManager` before
    `LiveBroker.submit_order`, and no execution path exists (D-023). **Not
    complete** — an interface that vetoes is not proof it gates execution.
  - **#12 Position limits — TESTED, NOT on an execution path.** `_check_position`
    projects the signed quantity and rejects `abs(projected) > max_position`
    (strict `>`, both signs), fails closed without positions. Same wiring gap as
    #11. **Not complete.**
  - **#13 Daily loss limits — TESTED, NOT on an execution path.**
    `_check_daily_loss` uses a per-UTC-day realized-PnL ledger, rejects once
    `loss >= max_daily_loss` (blocks *at* the limit), resets the next UTC day,
    never blocks a net-profit day. Same wiring gap as #11. **Not complete.**
  - **#14 Credential isolation — TESTED (isolation properties) / OBSERVED
    (market-data creds).** Market-data prod creds: Keychain key-id + file-only
    PEM (`scripts/kalshi_signer` — never CLI, env, or logged; `repr` shows the
    path only), `.gitignore` excludes `*.pem` / `*.key` / `.env` / `.env.*`,
    `repr`/`str`/`format`/`%`/exception paths all redacted (used read-only in the
    prod WS runs, never leaked into evidence). Trading creds: separate types +
    `KALSHI_TRADING_*` / `POLYMARKET_US_TRADING_*` env vars, redacted. Full
    verification still needs the live trading path (A-037/D-023). **Not
    complete.**
  - **#15 Live mode cannot activate accidentally — TESTED (comprehensive,
    multi-layer).** `LIVE_TRADING_ENABLED = False`; default `LiveTradingGate`
    disabled; frozen (no setter); `enabled=True` without the exact
    `REQUIRED_PHRASE` raises in `__post_init__` (including via
    `dataclasses.replace`); `from_env` arms only on an exact
    `PMA_LIVE_TRADING == REQUIRED_PHRASE` match — `"1"` / `"true"` / `"yes"` /
    whitespace-padded / substring variants all yield a disabled gate; an armed
    gate still hits `UnsupportedLiveOperationError` on every venue op. A-037/D-023
    require a live path before this is verified end-to-end. **Not complete.**
- **Changed — regression tests only (no src change):** +17 deterministic offline
  tests locking the offline-provable behaviour of every gate —
  `tests/test_live_broker.py` (#9 dup-after-failed-submit + concrete adapter;
  #15 exact-match/near-miss/`replace` bypass/absent-var; #14 trading-cred no-leak
  matrix + `.gitignore` guard), `tests/test_risk_manager.py` (#11 kill blocks
  `evaluate_opportunity`; #12 boundary strict-`>` both signs; #13 blocks at
  exactly the limit / never on a profit day), `tests/test_livebook_credentials.py`
  (#14 market-data cred no-leak matrix + non-echoing validation error).
- **Blocker (all six):** the real-money verification standard for these gates
  requires a captured venue trading API and a live reconciliation run (A-037,
  D-023); #11/#12/#13 additionally need the `RiskManager` veto bound to a real
  execution path (no orchestrator wires `RiskManager` → `LiveBroker`, and no
  live execution exists). Both are out of scope here (network + architecture).
  ROADMAP real-money gate checkboxes unchanged.
- Full local quality gate run once after the test-only change. Not committed.

## 2026-09-10 — Real-money gate audit: #3 / #4 / #5 / #6 / #10 — none completed; paper-execution pipeline proven offline

- **Goal:** audit the paper-execution / fee / equivalence / partial-fill /
  reconciliation gates and close any small deterministic offline gap. Branch
  `obs/realmoney-gates-3-4-5-6-10` off `main` @ a768497. No architecture change,
  no network, no orders/balances/funds, no `LIVE_TRADING`, no Polymarket US.
- **Per-gate classification (evidence status):**
  - **#3 Successful paper execution — TESTED end-to-end (offline), NOT complete.**
    Before this pass the chain existed only as isolated component tests
    (`test_arbitrage_engine`, `test_paper_broker`, `test_recorder`,
    `test_replay`); `test_failure_scenarios` joins the imports but only for
    injected fail-closed seams, and `replay_support.build_recording` hand-writes
    the order/fill/position rows rather than running `PaperBroker`. Added
    `tests/test_paper_execution_pipeline.py`: `ArbitrageEngine.evaluate` →
    `PaperBroker` (real two-level depth match, partial fill) → derived
    position/fees → `Recorder` (DuckDB) → `ReplaySession`, asserting the
    replayed fills fold to the replayed position and two runs record
    identically. **Residual (the "real market data" clause):** the books are
    synthetic; no *recorded real venue market-data session* has been driven
    through the chain. Blocker → *required future observation.*
  - **#4 Fee reconciliation — model TESTED vs published schedule; reconciliation
    vs observed venue fees UNKNOWN. NOT complete.** `KalshiTradingFeeModel` /
    `PolymarketUsTradingFeeModel` match the retained published fee-schedule
    extracts (A-024 / A-025) and `test_arbitrage_fees` checks the worked
    examples; the new pipeline test also confirms the model is applied per fill
    slice inside `PaperBroker` (non-zero, matches `FeeModel` output). But **no
    actual venue fee from a real fill has ever been compared** — the funded Kalshi
    **demo** order lifecycle (K-TR-OBS-26..33) produced **no fill** (A-038), and
    A-026 (per-slice rounding of a multi-level sweep) stays explicitly
    UNVERIFIED. No fee schedule invented. Blocker → *required future
    observation.*
  - **#5 Contract equivalence — mechanism TESTED; the gate itself UNKNOWN. NOT
    complete.** `registry/data/market_pairs.toml` ships **zero pairs** by
    design; the fail-closed loader + VERIFIED-only `eligible()` + 11-item
    checklist + `live_use_eligible` forced false (D-011) are covered by
    `test_market_pair_registry`, and `test_failure_scenarios` proves the engine
    rejects a non-verified pair and books that do not match a pair record. There
    is **no economically-equivalent pair** to point at — nothing to verify,
    nothing unsafe. No safety gap found; no change. A-001 / A-013 / A-015 /
    A-016 remain the standing blockers on ever adding one.
  - **#6 Partial-fill behavior — simulated TESTED; venue behavior UNKNOWN. NOT
    complete.** `PaperBroker` walks depth and emits `PARTIALLY_FILLED` /
    working-remainder / IOC-cancel deterministically (`test_paper_broker`,
    `test_failure_scenarios`, and now the pipeline test's two-level walk).
    Actual venue partial-fill behavior has **never been observed** — the demo
    order produced no fill at all (A-038). Blocker → *required future
    observation.*
  - **#10 Position/order reconciliation — offline replay reconstruction TESTED;
    authenticated venue reconciliation UNKNOWN. NOT complete.** The recorder is
    append-only DuckDB (D-016); `test_failure_scenarios` proves a recording
    survives a process restart and a reopened file continues ids append-only;
    `ReplaySession` streams orders/fills/positions/pnl and
    `test_two_identical_recordings_replay_identically` proves determinism. The
    new pipeline test adds the missing link: recorded fills **fold back to** the
    recorded position, and two independent runs produce byte-identical rows.
    There is **no** component that reconciles recorded/expected state against
    **authenticated venue** order/position/fill state — `LiveBroker.get_order` /
    `get_positions` raise `UnsupportedLiveOperationError` (A-037 / D-023).
    Blocker → *required future observation.*
- **Changed — regression test only (no src change):**
  `tests/test_paper_execution_pipeline.py` (+2 deterministic offline tests).
- **Required future observations (to advance the blocked gates):**
  - #3: capture a bounded **real** Kalshi book session to a `Recorder` DuckDB
    file, then replay it through engine → paper broker → positions/PnL and
    retain the recording as evidence.
  - #4 / #6: a **real or demo** order that actually fills (ideally partially
    across levels), so the venue fee line and partial-fill semantics can be
    reconciled against the model. Requires a read-only-plus-one-order demo
    observation — out of scope for this milestone.
  - #10: an authenticated venue `get_order` / `get_positions` / fills read
    reconciled against a recorded expected state — requires a captured trading
    API (A-037 / D-023).
- **Not done:** no production execution orchestrator, no live execution path, no
  network calls, no orders/balances/positions/fills, no funds, no
  `LIVE_TRADING`, no Polymarket US. ROADMAP real-money gate checkboxes
  unchanged. Full local quality gate green (ruff, mypy src+tests, 683 pytest,
  pre-commit). Not committed.

## 2026-09-10 — M3.5: Kalshi DEMO-only execution orchestrator (offline; no order placed)

- **Goal:** the smallest demo-only execution path that can later produce the
  real-money-gate evidence (#3/#4/#6/#10) safely, by composing existing
  components. Branch `feat/kalshi-demo-execution-orchestrator` off `main` @
  17b5ef9. No network call made; no demo order placed.
- **New package `prediction_market_arbitrage.demo_execution`** (see
  `docs/DECISIONS.md` D-030):
  - `transport.py` — `DemoTransport` protocol + `DemoResponse` + hard host guard
    `assert_demo_host` (rejects any production Kalshi marker, any
    non-`demo.kalshi.co` host, non-`https`, empty). **No networked
    implementation** ships (same posture as `livebook`'s socket).
  - `broker.py` — `KalshiDemoLiveBroker(live_broker.LiveBroker)`: the first
    concrete `LiveBroker` with implemented `_do_*` hooks, mapping the K-TR-05
    create body / K-TR-06+K-TR-08 responses to the venue-neutral value objects
    over the injected transport. Host-pinned at construction. Still runs through
    the unchanged `LiveTradingGate` + `IdempotencyGuard` wrapper; a venue `409`
    (K-TR-07) → `DuplicateOrderError`.
  - `orchestrator.py` — `DemoExecutionOrchestrator`: record intent → run the
    **unchanged** `RiskManager.evaluate_order` (all configured fail-closed
    checks) → submit only on approval → record the venue ack; explicit `cancel`
    / `reconcile` follow-ups. `reconcile` reads venue order status + positions,
    records local state, and fails closed (`DemoCapabilityError`) on any missing
    / ambiguous field. Deterministic except the injected transport + clock.
    Rejects a non-demo broker.
- **No recorder schema change:** the lifecycle maps onto existing
  `OrderEventRow` statuses + `reason` and `record_position`; the full
  `RiskDecision` + raw venue body live in the returned `ExecutionOutcome` /
  `to_evidence_dict()`.
- **Changed:** `src/prediction_market_arbitrage/demo_execution/` (new, 5 files);
  `tests/test_demo_execution.py` + `tests/demo_execution_support.py` (new, 27
  deterministic offline tests, fake transport); `docs/DECISIONS.md` (D-030);
  `docs/ASSUMPTIONS.md` (A-037 note — unchanged status, cross-ref D-030); this
  entry. **No `src/` change outside the new package.**
- **Tests prove:** production host / base URL rejected (guard + broker ctor);
  risk rejection / kill switch / position / order-size / daily-loss /
  data-freshness / min-edge each prevent the broker call (venue never touched);
  local idempotency guard *and* a venue 409 prevent a second submission;
  recorder captures intent→submit→cancel→reconcile + the local position row;
  reconciliation is byte-identical across identical fake-response runs; a 2xx
  create without an `order_id`, an ambiguous order status, and a failed
  positions read all fail closed; a non-2xx create is recorded `rejected`, never
  assumed placed.
- **Gate impact:** none. #3/#4/#6/#10 stay UNCHECKED — offline orchestration
  tests are not venue evidence (D-030). A-037 / D-023 unchanged (they govern the
  *production* boundary, which still implements nothing).
- **Required demo observation (next milestone):** implement the concrete
  `DemoTransport` (openssl RSA-PSS signing + `urllib`, demo Keychain credential
  — a `scripts/` concern), then run **one** minimal approved intent through the
  orchestrator against Kalshi demo shard 1 and retain the sanitised
  `ExecutionOutcome` + recorder rows as evidence for #3 (real execution), #4
  (fee line if a fill occurs), #6 (real partial fill), #10 (authenticated
  reconcile). Explicitly gated; not part of this milestone.
- **Safety:** DEMO host only; `LIVE_TRADING` never read/set; no production
  credential path; production read-only WS credential path untouched; no
  Polymarket US; no fund movement; no network call this milestone. Full local
  quality gate green (ruff, mypy src+tests, pytest, pre-commit). Not committed.

## 2026-09-10 — M3.6: concrete Kalshi DEMO REST transport + unrun one-order observation harness

- **Goal:** turn the M3.5 demo orchestrator into a real Kalshi-demo execution
  path (no production safety weakened), and prepare — **without running** — one
  bounded demo execution observation. Branch `feat/kalshi-demo-transport` off
  `main` @ b8f80b5. No network call made.
- **New:**
  - `src/prediction_market_arbitrage/demo_execution/rest_transport.py` —
    `KalshiDemoRestTransport(DemoTransport)`: stdlib `urllib` only, K-TR-03
    signed string + K-TR-02 headers, **injected `livebook.Signer`** (openssl
    signer stays in `scripts/`), **injected `HttpSender`** seam
    (`urllib_sender` default) so tests are offline. `assert_demo_host` at
    construction. Fail-closed: non-JSON/non-object body → `{}`;
    transport/timeout → `DemoTransportError` with only method + path +
    exception class (no host/headers/key/signature/message); 401/409/429/5xx
    flow through as a `DemoResponse` (409 → `DuplicateOrderError` in the
    broker).
  - `tests/test_demo_rest_transport.py` (+22 offline): exact signed-string
    construction (POST/GET/DELETE, path without query); demo host accepted /
    production+bad host rejected at ctor; empty api_key_id rejected;
    create/get/cancel/fills/positions request + response parsing; non-2xx and
    409 flow through, not raised; malformed / empty / array / scalar body →
    `{}`; transport failure → `DemoTransportError` with no secret material;
    `urllib_sender` maps `URLError`/`TimeoutError` → `DemoTransportError` and
    returns `HTTPError` bodies; create-order body shape through the real
    transport (K-TR-05 fields); duplicate client intent cannot issue a second
    create via the real transport; reconcile deterministic with fake venue
    state via the real transport.
  - `scripts/observe_kalshi_demo_execution.py` — the bounded one-order demo
    harness (see "Observation command" below). **Not run.**
- **Docs:** D-031 (the concrete transport + harness); D-030 evidence line
  extended; `ASSUMPTIONS.md` M3.4 note extended (A-037 still UNCHANGED).
- **Changed:** `src/prediction_market_arbitrage/demo_execution/rest_transport.py`
  + `__init__.py` (exports); `tests/test_demo_rest_transport.py`;
  `scripts/observe_kalshi_demo_execution.py`; `docs/DECISIONS.md`;
  `docs/ASSUMPTIONS.md`; this entry. No change to `demo_execution/broker.py` /
  `orchestrator.py` / `transport.py`; no change to `live_broker`, `risk`,
  `recorder`, or the production credential / WS path.
- **Full local gate green:** ruff, mypy (src+tests, +the harness), 731 pytest,
  pre-commit. Not committed.
- **Gate impact:** none. Offline tests are not venue evidence.
- **Future-evidence reassessment (what the pending one-order demo run can /
  cannot advance):**
  - **#3 Successful paper execution — the demo run can add a *real venue*
    end-to-end trace** (detector-sized intent → risk → demo submit → venue
    order state → recorder) to sit beside the offline pipeline test; still
    "paper"/demo, not production. Plausible to CHECK #3 on demo evidence if the
    gate owner accepts demo as "real market data".
  - **#4 Fee reconciliation — advances only if the 1-contract order actually
    fills.** A demo fill returns `average_fee_paid` (K-TR-06) / `fee_cost` per
    fill (K-TR-09), which can be reconciled against `KalshiTradingFeeModel`
    output. A resting/cancelled order yields no fee line — blocker persists
    (A-024/25/26).
  - **#6 Partial-fill behavior — advances only on a *partial* demo fill**
    (count taken across levels with `remaining_count_fp` > 0). A tiny
    1-contract order rarely partials; may need a 2–3 contract order against a
    1-lot top level in a follow-up. Simulated partials already TESTED.
  - **#9 Duplicate-order prevention — the demo run adds the venue half**: a
    re-`POST` of the same `client_order_id` → HTTP 409 (K-TR-07/K-TR-OBS-29),
    now flowing through `KalshiDemoRestTransport` → `DuplicateOrderError`. Local
    half already TESTED; demo 409 is OBSERVED-ready.
  - **#10 Position/order reconciliation — the demo run exercises the
    authenticated read + fold**: `get_order` + `get_positions` + `get_fills`
    vs the recorder rows, deterministically. Demo (not production) authenticated
    state; production reconciliation still needs a captured production API
    (A-037).
  - **#11 Kill switch / #12 Position limits / #13 Daily loss limits — now on a
    real execution path.** The orchestrator runs `RiskManager.evaluate_order`
    (all these checks, fail-closed) *before* the demo submit; the offline tests
    prove the venue is never touched on a veto. A demo run can OBSERVE that the
    veto blocks a real submit — the "not wired to execution" gap from the
    2026-09-09 audit is closed **for the demo path**.
  - **#14 Credential isolation — the concrete transport keeps the property**:
    the demo key id + RSA key load via the existing Keychain / file-only
    pattern (`scripts/kalshi_signer`), never logged; `DemoTransportError`
    messages carry no secret (regression-tested). Production credential path
    untouched. Full gate still needs the production trading path (A-037).
  - **#15 Live mode cannot activate accidentally — unchanged and preserved**:
    the demo broker still requires an armed `LiveTradingGate`; `LIVE_TRADING`
    is never read/set; `assert_demo_host` makes a production base URL a hard
    failure, so an armed gate cannot reach production through this package.
- **Safety:** DEMO host only (hard-fail); no production credentials / requests /
  balances / positions / fills; no fund movement; no Polymarket US;
  `LIVE_TRADING` untouched; production `LiveBroker` interface not broadened; no
  network call this milestone.

## 2026-09-10 — M3.6: read-only `--diagnose` for demo market selection (no order)

- **Why:** the first bounded demo `--observe` exited safely with "no open demo
  market with a two-sided book and best ask <= 0.60". Needed to see *what the
  picker sees* before touching `--max-price` or the order path.
- **Changed:** `scripts/observe_kalshi_demo_execution.py` — new `--diagnose`
  mode (public `GET /markets*` on the demo host only; no auth, no preflight, no
  order, no evidence file). Reuses `KalshiClient` + `KalshiMarketDataAdapter`.
  Reports per open demo market: ticker, venue `status`, YES best bid / best ask,
  two-sided?, level count per side, size at best ask, and whether it passes the
  picker rule at the given `--max-price`. New pure helpers `assess_candidate`
  (scores one YES book against the exact picker rule) and `recommend_max_price`
  (advisory only — see DECISIONS). Extracted `MIN_BOOK_DEPTH = 2` and
  `DIAG_MARKET_LIMIT = 100` and pointed the picker at them (no behaviour
  change). Optional `--pages N` widens the read-only scan past page 1 (default
  1 = exactly what the picker scans).
- **OBSERVED 2026-09-10 (demo, read-only):** page 1 of
  `GET /markets?status=open&limit=100` is entirely one-sided or empty YES books
  — hourly metals ladders (`KXPLATINUMH` / `KXPALLADIUMH` / `KXSILVERH`, a
  handful with a single 0.01 bid and no ask) and `KXMVECROSSCATEGORY-SHARD1`
  markets with no levels at all. **0** markets have a two-sided YES book, so the
  picker correctly selected nothing. The blocker is book *shape* (no resting
  asks), not price — raising `--max-price` cannot help. Recommendation:
  **keep `--max-price 0.60` unchanged**; re-run `--diagnose` (optionally
  `--pages 3+`, slower) later or when demo liquidity is present.
- **Tests:** `tests/test_observe_kalshi_demo_execution.py` +12 offline cases
  (mode routing skips preflight/observation; `assess_candidate` for one-sided /
  in-range / above-max / sub-depth books; `recommend_max_price` never surfaces a
  `--max-price` increase as a recommendation; `MIN_BOOK_DEPTH` matches the
  picker). Full local gate green (ruff, mypy, pytest 759, pre-commit).
- **Safety:** read-only public market data on the DEMO host; no credentials /
  account data / production call; `--max-price` never changed automatically; no
  order submitted or cancelled; `LIVE_TRADING` untouched.

## 2026-09-10 — M3.6 follow-up: paginated Kalshi Demo candidate observation

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **OBSERVED:** the existing read-only `--diagnose` path inspected 10 pages / 1,000
  open Kalshi Demo markets at the unchanged `--max-price 0.60`. The API returned
  pagination as a top-level opaque string `cursor`, passed back as the next
  request's `cursor` parameter; the observed cursor was non-empty, 60 characters,
  and changed between the first two pages.
- **Liquidity:** 282 markets had a non-empty YES book, 47 had a two-sided YES
  book, and 3 passed the existing picker rule (two-sided, at least 2 levels per
  side, and `0 < best ask <= 0.60`). Recommended observed target:
  `KXMLBHR-26SEP101305HOUPHI-PHILARRAEZ1-1`, YES best bid `0.0600`, best ask
  `0.0800`, size at best ask `27083.29`, with 4 bid / 3 ask levels.
- **Evidence:**
  `docs/evidence/kalshi-demo/execution/candidate-scan-2026-09-10.json`.
- **Fresh revalidation (OBSERVED 2026-09-10T16:50:04Z):** the exact recommended
  target remained `active` and picker-eligible: YES best bid `0.0600`, best ask
  `0.0800`, 4 bid / 3 ask levels, and `64583.23` available at the best ask.
  Evidence:
  `docs/evidence/kalshi-demo/execution/candidate-revalidation-2026-09-10.json`.
  This read-only snapshot is not evidence of execution readiness, fill behavior,
  or realized profitability.
- **First bounded execution attempt blocked safely (OBSERVED
  2026-09-10T16:56:22Z):** host-level preflight passed, and an immediate public
  revalidation again found the target `active` and picker-eligible at YES bid
  `0.0600`, ask `0.0800`, 4 bid / 3 ask levels, with `83333.20` at the best ask.
  However, the supported `--observe` path accepts no ticker and its picker scans
  only the first 100 open Demo markets; a mirror diagnostic found 0 eligible
  markets on that page and did not include the authorized target. Execution
  therefore failed closed before the environment guard was set or any account,
  position, order, cancel, balance, or fill call occurred. No code was changed.
  Evidence:
  `docs/evidence/kalshi-demo/execution/bounded-execution-blocked-2026-09-10.json`.
- **Safety:** public Kalshi Demo market data only; no credentials, orders,
  cancellations, account/position/fill calls, production access, risk-limit or
  max-price changes, `LIVE_TRADING`, or Polymarket US work.

## 2026-09-10 — M3.6 follow-up: explicit target for bounded Demo execution

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Root cause:** `run_observation` always used the first-page discovery picker,
  and the CLI had no ticker argument. An eligible market found on a later page
  therefore could not be selected without changing the supported path.
- **Changed:** `--observe` now requires exactly one `--ticker KX...` argument.
  `pick_authorized_demo_market` retrieves that exact Demo market, checks response
  identity and `active` status, reads its current YES book, and reuses
  `assess_candidate` before credentials or authenticated clients are loaded.
  Discovery/diagnostic behavior is unchanged when explicit targeting is not
  requested.
- **Safety preserved:** unchanged `Decimal("0.60")` default cap,
  `MIN_BOOK_DEPTH = 2`, one-contract quantity/risk limits, Demo-only host and
  credentials, environment guard, pre-submit real position check, orchestrator
  duplicate protection, cancellation/reconciliation, evidence sanitization, and
  disabled production real-money path. Explicit ticker selection is
  authorization to evaluate, not proof of eligibility.
- **Tests:** 11 targeted cases added/updated for mandatory single-ticker CLI
  routing, exact retrieval independent of discovery ordering, missing,
  unavailable, mismatched, inactive, over-cap, insufficient-depth, and one-sided
  targets, unchanged discovery behavior, and continued position/orchestrator
  sequencing. Full local gate: `ruff check .`, `mypy src tests`, `pytest`, and
  `pre-commit run --all-files`.
- **No execution:** no Demo order, account call, production request, credential
  change, `LIVE_TRADING` change, or Polymarket US work occurred.

## 2026-09-10 — M3.6: first explicit-target bounded Kalshi Demo attempt

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Merge prerequisite:** reviewed PR #40 was verified at head
  `e62d15d4cf4072aafcad183c7ed871ec5e203389` with green GitHub CI and no
  GitHub review blocker, then squash-merged as
  `5b42b4dc512b961ffd82f40c8b8aaf8d830d4651` before this observation.
- **Attempt (OBSERVED 2026-09-10T18:54:47Z):** the merged explicit-target path
  evaluated `KXMLBHR-26SEP101305HOUPHI-PHILARRAEZ1-1` on Kalshi Demo. Identity,
  `active` status, two-sided YES book, minimum 2 levels per side, and the
  unchanged `--max-price 0.60` constraint passed. The harness selected the
  current best ask `0.0800` for exactly 1 contract. The harness did not emit or
  persist the contemporaneous best bid or exact level counts, so those values
  remain unavailable; only the minimum depth pass is evidenced.
- **Pre-submit checks:** Demo host/environment guard passed; the authenticated
  current-position read returned 0 contracts. Risk was allowed with checks
  `kill_switch`, `max_daily_loss`, `max_order_size`, `feed_health`, and
  `max_position`; reason count 0. Duplicate flag was false.
- **Outcome:** exactly one create request was attempted. Kalshi Demo rejected it;
  `venue_accepted = false`, `venue_state = rejected`, and no venue order ID was
  created. Submitted/accepted quantity was 0; fill quantity was 0. With no
  accepted order, cancellation and order/position reconciliation were not
  applicable; the summary records `reached_venue = false` in that lifecycle
  sense. No retry was made.
- **Evidence:** sanitized harness output
  `docs/evidence/kalshi-demo/execution/SUMMARY.json`. The ignored local
  `recording.duckdb` is not durable evidence.
- **Gate impact:** none. This is OBSERVED Demo rejection evidence, not proof of
  successful execution, fill behavior, realized profit, or production readiness;
  no real-money gate is promoted.
- **Safety:** no production endpoint, real money, `LIVE_TRADING`, cross-venue
  execution, fund movement, or second create attempt.

## 2026-09-10 — M3.6: Kalshi Demo create-rejection diagnosis and safe observability

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Diagnosis:** the exact venue rejection cause is **UNKNOWN** because the prior
  sanitized evidence retained neither HTTP status nor venue error code. Current
  official Create Order V2 documentation matches the implemented request:
  `POST /portfolio/events/orders`; ticker; YES-side `bid`; string count `"1"`;
  fixed-point dollar price `"0.0800"`; `good_till_canceled`; `maker` self-trade
  prevention; client order ID; and omitted `exchange_index` auto-routing by
  ticker. No confirmed request/API mismatch was found.
- **Authentication:** the transport signs timestamp milliseconds + uppercase
  method + `/trade-api/v2` path without query, using RSA-PSS/SHA-256 and the
  documented headers. The successful authenticated position GET supports key
  and signer correctness for that read, but does not prove create authorization.
  K-TR-16 is superseded: current docs expose `read`, `write`, and `write::trade`
  key scopes (K-TR-22), plus a region-attestation expiry that can bar Sports
  trading (K-TR-23). The configured key's current scope/attestation was not read.
- **Ranked hypotheses (UNVERIFIED):** (1) missing collateral/provisioning on the
  target's routed shard — official docs place new baseball events on shard 3
  after 2026-08-24 and require preallocated shard collateral, while retained
  project evidence establishes only the earlier shard-1 funding; the target's
  authoritative `exchange_index` was not retained; (2) expired/missing API-key
  location attestation for a Sports market; (3) configured key missing current
  `write`/`write::trade` scope; (4) a transient market/account validation change
  between the public read and create. None can be promoted without the discarded
  response metadata or a separately authorized read.
- **Detail-loss path:** `urllib_sender` and `KalshiDemoRestTransport` made the
  non-2xx HTTP status and parsed error object available. The broker omitted the
  status and flattened only top-level scalars (dropping older nested
  `error.code`); the orchestrator classified every non-409 non-2xx response as
  generic `venue_rejected`; the observation evidence then omitted `ack.raw`.
- **Changed (D-034):** failed creates now retain only HTTP status, a fixed
  internal category, and a conservative allowlisted venue error code; venue
  message/details, arbitrary response fields, request data, headers, signatures,
  and identifiers remain discarded. The harness independently allowlists these
  fields before persistence. Current top-level and older nested code envelopes
  are covered by offline tests.
- **Evidence status:** this change cannot retroactively diagnose the existing
  OBSERVED rejection. It only makes a future separately authorized attempt more
  diagnosable. No new evidence file was manufactured for the missing response.
- **Safety:** offline code/docs/tests only. No order, cancel, authenticated venue
  request, production access, credential access/change, `LIVE_TRADING` change,
  risk/price/quantity change, or Polymarket work occurred.

## 2026-09-10 — M3.6: reviewed rejection diagnostics merged; target finalized

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Merge:** PR #41 was re-verified open at reviewed head
  `b2d5796a10358270677efd0535332ebea9bae2c1`, with green GitHub `quality` CI,
  no GitHub review/comment blocker, and one reviewed commit. It was squash-merged
  using the repository's established strategy as main commit
  `d5a7d2cc25b8ef505895558ccb8c5b306da8b30e`.
- **Fresh public observation (OBSERVED):** exact Demo identity matched for
  `KXMLBHR-26SEP101305HOUPHI-PHILARRAEZ1-1`, but status was `finalized` on
  exchange index 3. The YES book was empty: best bid/ask unavailable, 0 bid
  levels, 0 ask levels, and no size at the best ask. It failed the unchanged
  two-sided-book / minimum-2-level eligibility rule before authentication.
- **Fail-closed result:** the bounded execution command was not run. No Demo
  position, duplicate, or risk check ran; create attempts = 0; cancel attempts =
  0; no replacement market was selected. HTTP rejection fields are not
  applicable because no create request occurred.
- **Evidence:**
  `docs/evidence/kalshi-demo/execution/target-finalized-2026-09-10.json`.
- **Gate impact:** none. This read-only observation is not execution, fill,
  profitability, or production-readiness evidence. A new candidate requires a
  separate read-only selection and revalidation milestone.
- **Safety:** public Kalshi Demo market data only for the observation. No
  authenticated venue call, order, cancel, account/position/fill/balance call,
  production/real-money action, `LIVE_TRADING` change, or cross-venue work.

## 2026-09-10 — Kalshi Demo 10-page replacement-candidate observation

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Observation (OBSERVED):** the established credential-free diagnostic ran
  with `--diagnose --max-price 0.60 --pages 10`. Cursor pagination inspected 10
  pages / 1,000 open Demo markets. Of those, 123 had a non-empty YES book, 27
  were two-sided, and exactly 1 passed the unchanged picker rule.
- **Eligible candidate:** `KXUCLSPREAD-26SEP10BMUBOG-BMU5`, `active`, YES best
  bid `0.0500`, best ask `0.0700`, 4 bid levels / 3 ask levels, and `11896.81`
  available at the best ask. It is the recommended candidate because it was the
  only market marked `picker-eligible`; this is discovery, not authorization or
  execution readiness.
- **Diagnostic discrepancy / blocker:** the primary eligible count and row say
  1, but `recommend_max_price` says 9 markets "satisfy the picker rule." Its
  implementation counts markets with two-sided, depth-qualified books before
  applying `--max-price`; eight of those do not pass the cap. No code was
  changed, per the milestone instruction to stop on a diagnostic defect.
- **Evidence:**
  `docs/evidence/kalshi-demo/execution/candidate-scan-2026-09-10T2051Z.json`.
  The verbose scan output remained temporary.
- **Safety:** public Kalshi Demo market data only. No credential, authenticated,
  account, position, balance, fill, order, cancel, production, `LIVE_TRADING`,
  risk-check, duplicate-check, or cross-venue action occurred.

## 2026-09-10 — Kalshi Demo diagnostic advisory-count correction

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Confirmed root cause:** `recommend_max_price` correctly identified
  structurally tradeable markets using two-sided/depth/positive-ask checks, but
  used that pre-cap count in text claiming every one "satisf[ies] the picker
  rule." The primary diagnostic rows and eligible count correctly applied the
  active `--max-price`; execution eligibility was not defective.
- **Changed:** the advisory now partitions structurally tradeable candidates
  into currently eligible (`best_ask <= current_max_price`) and above-cap
  groups. Only the first group is described as satisfying the picker. Above-cap
  markets are labeled structurally tradeable but currently ineligible; when all
  are above cap, the function still returns no suggested price increase.
- **Tests:** focused cases cover multiple depth-qualified markets with one under
  cap, all structurally valid markets above cap, multiple already-eligible
  markets, no structurally tradeable market, exact `Decimal` preservation, and
  semantic consistency between primary diagnostic and advisory counts.
- **Historical evidence:** the prior scan artifact and journal discrepancy are
  unchanged; this entry records the later correction separately.
- **Safety:** offline code/tests/docs only. The live Demo scan was not rerun. No
  credential, authenticated, account, position, balance, fill, order, cancel,
  production, `LIVE_TRADING`, risk-limit, or cross-venue action occurred.

## 2026-09-10 — Deterministic synthetic paper-arbitrage lifecycle

- **Agent:** Codex
- **Model:** unknown
- **Reviewer:** ChatGPT
- **Gap closed:** replaced the prior manual detector-to-single-order test seam
  with a narrow offline orchestrator that loads a synthetic VERIFIED pair through
  the registry, evaluates the same books used for both paper fills, runs
  opportunity/order risk gates, derives positions/exposure/P&L, persists explicit
  lifecycle/risk linkage, and reconciles the rows through replay.
- **Deterministic result (TESTED, synthetic only):** quantity `4`; gross cost
  `3.60`; venue-model fees `0.13`; execution buffer `0.020`; slippage reserve
  `0.04`; net edge `0.210`. Paper fills were Kalshi `4 @ 0.40` and Polymarket US
  `4 @ 0.50`; positions matched both fills; exposure `3.60`; pair P&L was
  realized `0`, unrealized gross locked value `0.40`, fees `0.13`, net `0.27`.
- **Traceability:** additive `paper_lifecycles` and `risk_decisions` tables link
  pair → opportunity → three allowed risk decisions → two order intents and
  lifecycles → fills → positions → pair P&L. Replay reconciles opportunity id,
  pair id, order ids, fill quantities, positions, and P&L.
- **Safety/evidence boundary:** synthetic deterministic TESTED evidence only.
  No real pair, venue data, network, authentication, Demo/production order,
  cancellation, credential, `LIVE_TRADING`, risk-limit, or Demo-cap change.

## Journal rules

## 2026-09-11 — Read-only contract-equivalence discovery triage

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Gap closed:** added a deterministic, bounded discovery surface that turns
  existing public Kalshi and Polymarket US market metadata into ranked,
  field-by-field candidates for human contract review. It cannot create a
  registry record or make a pair strategy-eligible.
- **Result (TESTED):** synthetic fixtures cover exact and material semantic
  matches, cancellation/void and multiple-winner differences, threshold and
  inclusivity differences, unknown fields, Decimal precision, deterministic
  ordering, and the unchanged VERIFIED-only registry gate.
- **Observation (OBSERVED 2026-09-11):** one bounded unauthenticated run inspected
  100 public markets per venue and surfaced zero candidates above the
  conservative lexical generation threshold. This limited first-page result is
  not evidence that no cross-venue pair exists.
- **Safety:** output is always `UNVERIFIED — human/primary-source verification
  required`; no order books, credentials, account data, registry writes,
  strategy evaluation, authentication, orders, or production execution.

## 2026-09-11 — Broader bounded contract-discovery observation

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Merge prerequisite:** PR #44 remained open at reviewed head
  `39aad872e5992bd7fd9cbfa2307786019a24b959`, with green CI and no new review
  blocker, then was squash-merged as `a687f779225ff945961d98de8f25774c959b2dd5`.
- **Observation (OBSERVED 2026-09-11T06:31:05Z):** the unchanged maximum-bounds
  public CLI inspected 1,000 Kalshi and 1,000 Polymarket US market records and
  surfaced 16 `UNVERIFIED` rows. All had priority 2, zero semantic MATCH fields,
  and were lexical false positives linking Kalshi cross-category combo titles
  to Polymarket US NFL futures through shared team-name tokens.
- **Finding:** UNKNOWN dominated 112 of 224 comparisons; 80 were MISMATCH and 32
  NOT_APPLICABLE. The current output does not retain below-threshold comparisons,
  so same-event records failing the lexical gate cannot be distinguished from
  universe-coverage gaps. No matching logic was changed during this observation.
- **Safety:** public metadata/rules only; no credentials, authentication,
  order-book/account call, strategy evaluation, registry write, pair approval,
  order/cancel, production execution, or real-money action.

## 2026-09-11 — Candidate-generation rejection diagnostics

- **Agent:** Codex
- **Model:** GPT-5
- **Reviewer:** ChatGPT
- **Gap closed:** extended the read-only discovery CLI with reconciled gate
  counters and streaming, bounded top-N diagnostics for below-threshold rows.
  Output shows normalized/shared/unique tokens, coarse event/entity/category/
  date/threshold signals, missing metadata, and the rejection reason without
  changing the `0.20` threshold, ranking, or registry gate.
- **Result (TESTED):** focused discovery/registry tests cover a strong same-event
  near miss, generic-token collision, deterministic tokens and top-N, explicit
  missing metadata, exact counter reconciliation, and registry isolation.
- **Observation (OBSERVED 2026-09-11T12:45:05Z):** 1,000 × 1,000 public records
  produced 1,000,000 comparisons: 34 passed and 999,966 rejected. The top 20
  rejected rows had zero extracted coarse matches and were participant-name
  collisions involving Kalshi multivariate combos. Evidence supports a mixed
  universe-overlap/normalization bottleneck, not a threshold-recall conclusion.
- **Safety:** public metadata only; no credentials, authentication, books,
  account data, strategy/execution, registry write, order/cancel, production
  execution, or real-money action.

- Record only material progress, evidence, blockers, and changes in direction.
- Do not use this file as a dump of terminal output.
- Link detailed reasoning to `DECISIONS.md`, assumptions to `ASSUMPTIONS.md`, and validation requirements to `TEST_PLAN.md`.
