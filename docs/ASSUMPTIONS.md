# Assumptions Register

Every unverified project assumption must be recorded here before implementation depends on it.

## Status values

- UNVERIFIED
- VERIFIED
- REJECTED
- SUPERSEDED

## Rules

- An assumption cannot silently become a fact.
- Any assumption affecting market equivalence, pricing, fees, execution, risk, or live behavior must be resolved before real-money use.
- If evidence conflicts with an assumption, update this file and the related decision or implementation.

## Current assumptions

| ID | Assumption | Status | Blocks live use? |
|---|---|---|---|
| A-001 | Exact cross-venue contract equivalence can be established through explicit resolution-term review. | UNVERIFIED | Yes |
| A-002 | Venue data can be normalized into a shared internal order-book representation without losing required execution information. | UNVERIFIED | Yes |
| A-003 | Paper execution can approximate enough fill, latency, and leg-risk behavior to support a go/no-go decision for limited live testing. | UNVERIFIED | Yes |
| A-004 | Normalized contract prices can be represented as probability-style decimals in the inclusive range [0, 1] across every supported venue. | UNVERIFIED | No |
| A-005 | A locked order book (best bid == best ask) is a valid transient market state and only a truly crossed book (best bid > best ask) indicates malformed data. | UNVERIFIED | No |
| A-006 | A normalized Opportunity always carries a strictly positive quantity and a strictly positive per-unit edge; non-positive values indicate a producer error, not a zero-value opportunity. | UNVERIFIED | No |
| A-007 | A contract outcome can be represented as a free-form venue-neutral string label; no fixed outcome enumeration (e.g. YES/NO only) is imposed at the domain layer. | UNVERIFIED | No |
| A-008 | Every Kalshi `/markets` and `/markets/{ticker}` payload includes `ticker`, `title`, `market_type`, and a timezone-aware `close_time`; the adapter treats any missing/invalid one as a payload error rather than defaulting it. | PARTIAL — OBSERVED on sampled `KXHIGHNY` markets only | No |
| A-009 | Kalshi public market-data endpoints (`/markets`, `/markets/{ticker}`, `/markets/{ticker}/orderbook`) need no authentication. | OBSERVED 2026-09-05 (unauth HTTP 200 on production and demo); OpenAPI `security: []`. Conflicts with the rendered auth block on the Get-Market-Orderbook reference page. | No |
| A-010 | Kalshi `orderbook_fp.{yes_dollars,no_dollars}` are bids only, ascending, best bid last; for a binary market the implied ask price on one side equals `1 - (opposite side's bid price)` with the bid's size carried over unchanged. | VERIFIED (docs) + OBSERVED (top-of-book matches `yes_ask_dollars`/`no_ask_dollars`) + TESTED | No |
| A-011 | Dropping Kalshi identifiers other than `ticker` (e.g. `event_ticker`, `series` grouping) loses no information the market-data pipeline needs in M1.2–M1.3. `ticker` is preserved inside `Market.id` and `Contract.id`. | UNVERIFIED — revisit in M1.4 (market-pair registry) | No |
| A-012 | Every Polymarket US market is binary: `marketSides` is exactly one `long: true` side + one `long: false` side. The adapter rejects anything else. | OBSERVED on `futures` and `moneyline` captures 2026-09-05; multi-outcome markets not seen | No |
| A-013 | The single Polymarket US book per slug is quoted in the **long** side's price space, so its `bids`/`offers` map to the `:LONG` contract's `OrderBook`. | **UNVERIFIED (interpretation).** Price *alignment* was OBSERVED (`bbo.longQuote`/`shortQuote` and `stats.lastPriceSample.longPx` track the book) but no primary doc/SDK statement confirms the book is the long-side book; no independent short-side book was seen. Not promoted to VERIFIED — no new primary evidence obtained. | Yes |
| A-014 | `marketData.transactTime` is a trustworthy server timestamp for the book snapshot; the adapter uses it directly and only falls back to `observed_at` if the field is absent. | OBSERVED — present on every book capture incl. the empty book; semantics per docs ("timestamp of data") | No |
| A-015 | Preserving only the Polymarket US `slug` (in `Market.id` / `Contract.id`) is enough traceability for future execution/reconciliation; `id`, `marketSides[].id`, `identifier`, `teamId` are dropped. | **UNVERIFIED** — sufficiency for order routing / fill reconciliation is untested; revisit in M1.4 and before any live path. | Yes |
| A-016 | `question` is the correct normalized `Market.title` across all Polymarket US market types (vs `title` / `subtitle`). | **UNVERIFIED** — `question` chosen from limited samples; `futures` markets showed `title` = team name, `question` = the market question. A wrong label could mislead human pair verification (D-006). | Yes |
| A-017 | Polymarket US market prices are probability-style decimals in `[0, 1]` (USD notional $1), consistent with A-004. | OBSERVED — all captured prices in `(0, 1)`; `outcomePrices` pairs ≈ sum to 1 | No |
| A-018 | A two-value `relation` (`IDENTICAL` / `COMPLEMENTARY`) plus one named `outcome` per leg is enough to express every economic outcome mapping later arbitrage code (M1.5) needs between a Kalshi contract and a Polymarket US contract. | UNVERIFIED — no arbitrage math exists yet; revisit in M1.5. Additional relations (e.g. scalar/laddered) may be needed if non-binary markets are ever supported. | Yes |
| A-019 | A human-curated TOML file behind a fail-closed loader, exposing only `VERIFIED` pairs, is a sufficient gate to keep unverified/rejected pairs out of strategy code. | UNVERIFIED (design assumption) — behaviour is enforced by `tests/test_market_pair_registry.py` and now by the M1.5 engine's registry gate (`tests/test_arbitrage_engine.py`); "sufficient" still depends on all future strategy code routing through `eligible()` / a VERIFIED check. | Yes |
| A-020 | A registry `VenueLeg` names exactly one order book via `f"{market_id}:{outcome}"` == the adapter-built `OrderBook.contract.id` (Kalshi `YES`/`NO`; Polymarket US `LONG`/`SHORT`). The M1.5 engine joins books to legs on this key and raises on any mismatch. | UNVERIFIED (convention) — followed by the M1.4 example records and both adapters' `Contract.id` construction, but not enforced by the registry loader. If a curator uses a different `outcome` vocabulary the engine fails closed rather than guessing. | Yes |
| A-021 | For a `COMPLEMENTARY` pair, buying one unit of each leg's named outcome yields exactly 1 unit of settlement value regardless of outcome (payout normalization = $1). The engine computes edge as `size - total_acquisition_cost - fees - buffer`. | UNVERIFIED for real pairs — true by construction for the synthetic tests; for real markets it depends on the human VERIFIED review (A-001, D-006) and on both venues settling complementary sides to a combined $1. | Yes |
| A-022 | Real Kalshi / Polymarket US fee schedules are not yet known. The M1.5 engine takes an injected `FeeModel`; `ZeroFeeModel` and `FixedPerUnitFeeModel` are baseline/synthetic only. | SUPERSEDED by A-024 (Kalshi) and A-025 (Polymarket US) — the venue **taker** formulas are now verified from primary sources. The injected-`FeeModel` design is unchanged; `ZeroFeeModel` / `FixedPerUnitFeeModel` remain baseline/synthetic. | Yes |
| A-023 | Reporting `net_edge_per_unit` / `gross_edge_per_unit` as `total / executable_quantity` (a Decimal division that may round to context precision when it does not divide evenly) is acceptable because the engine's *decision* (`net_edge > 0`) and every reported *total* use exact Decimal arithmetic with no division. | ACCEPTED (design) — the per-unit fields are explicitly documented as derived; totals are authoritative. | No |
| A-024 | Kalshi's general trading (taker) fee is `fees = round_up_to_next_cent(M · 0.07 · C · P · (1−P))`, `P` the contract price in dollars, `C` the contract count, `M` a per-contract multiplier that is `1` "unless otherwise indicated" and is overridden only for the series in Kalshi's current "non-standard fees" table; there is no settlement fee. Maker uses `M · 0.0175`. The pre-July-2026 standalone `0.035` S&P 500 / Nasdaq-100 table has been folded into the `M` system and is no longer a separate coefficient. Implemented as `KalshiTradingFeeModel(multiplier=…)` (default `M = 1`). | VERIFIED (docs) — Kalshi "Fee Schedule for July 2026 - 7.7.26 Update" (`kalshi.com/docs/kalshi-fee-schedule.pdf`, 12 pages, opens in a normal browser; confirmed 2026-09-06) + Help Center "Fees"; extract `docs/evidence/kalshi-fee-schedule-2026-07-07.txt`. The `M = 1` formula reproduces every row of Kalshi's published general fee table (`tests/test_arbitrage_fees.py`); multiplier scaling is covered by independently-calculated cases. The PDF's per-series "non-standard fees" multiplier table is present in the source; no individual multiplier is transcribed or hardcoded — the model takes `M` as a caller-supplied parameter, and a caller evaluating such a series reads its `M` from the current PDF. Not OBSERVED against a real fill; series/market type is not auto-detected from an `OrderBook`. | Yes |
| A-025 | Polymarket US's trading (taker) fee is `Fee = 0.06 · C · p · (1−p)`, rounded to the nearest cent with banker's rounding (round half to even), `p` in dollars; the maker side is a `−0.0125 · C · p · (1−p)` **rebate** and the >$250k prior-month volume taker rebate is a retrospective weekly account credit. Only the taker fee is modelled (`PolymarketUsTradingFeeModel`). | VERIFIED (docs), re-verified 2026-09-06 — `docs.polymarket.us/fees` "Trading Fee Schedule", "Effective exchange-wide from 12 AM ET, Wednesday July 1, 2026" (retained extract `docs/evidence/polymarket-us-fee-schedule.txt`); the single exchange-wide taker `Θ = 0.06` formula reproduces every row of the published "Fee Schedule by Price" taker column (`tests/test_arbitrage_fees.py`). **Unresolved:** a task prompt asserted the current coefficient is `0.05`; this is **not supported and is contradicted** by the primary source above. Third-party sites describe a July-2026 category split (sports 0.05 / tech 0.04 / crypto 0.07 / geo-econ 0.00) and a March-2026 CFTC filing has been reported as a basis-points-of-"Total Contract Premium" schedule — none of these appears on the official page. Model stays at `0.06` until a primary source says otherwise; any category/series coefficient must be independently evidence-backed. Not OBSERVED against a real fill. | Yes |
| A-026 | The venue fee models round **each fill slice** `(P_i, qty_i)` independently and sum the rounded slices. | UNVERIFIED (modelling choice) — **still explicitly unresolved.** Every worked example in both venues' published schedules is a single price; neither states how a single taker order that sweeps several price levels is rounded (per level, or once on the aggregate), and Kalshi's API fee-rounding docs describe a per-order "fee accumulator" whose exact effect on a multi-level sweep is not specified. Per-slice rounding can differ from the realized fee by up to one cent per extra level. Fee reconciliation against real fills stays a real-money-gate item. | Yes |

## M1.1 notes

- A-004 through A-007 were introduced by the M1.1 domain model implementation
  (`src/prediction_market_arbitrage/domain/`). They are representational choices
  in the internal model and must be re-checked against real venue data in M1.2
  (Kalshi) and M1.3 (Polymarket US).
- OrderBook rejects only crossed books; ordering (bids strictly descending, asks
  strictly ascending), duplicate price levels, non-finite decimals, non-positive
  quantities, out-of-range prices, and naive timestamps are all rejected at
  construction.

## M1.2 notes (Kalshi market-data adapter)

- A-008 through A-011 were introduced by the Kalshi REST adapter
  (`src/prediction_market_arbitrage/adapters/kalshi/`). Full evidence trail with
  live-capture details is in `docs/API_SOURCES.md`.
- A-004 (prices are decimals in `[0, 1]`) and A-005 (locked books valid, only
  crossed rejected) held against real Kalshi data: prices arrive as dollar
  strings in `[0, 1]`, and no captured book was crossed after implied-ask
  normalization.
- A-002 (normalize without losing execution info): fractional sizes and the
  `depth` parameter are preserved; still UNVERIFIED overall until execution work.
- The adapter refuses any `market_type` other than `"binary"` — the
  complementary YES/NO price identity (A-010) is only valid for binary markets.
- Book timestamp: Kalshi sends no per-book server time, so the adapter stamps
  each normalized `OrderBook` with an injected `clock()` reading taken when the
  responses are received.

## M1.3 notes (Polymarket US market-data adapter)

- A-012 through A-017 were introduced by the Polymarket US REST adapter
  (`src/prediction_market_arbitrage/adapters/polymarket_us/`). Full evidence
  trail in `docs/API_SOURCES.md` (P-01..P-14).
- A-004 (prices are decimals in `[0, 1]`) held again: Polymarket US prices are
  USD-denominated probability decimals in `(0, 1)`.
- A-005 (locked books valid, only crossed rejected): unchanged — the domain
  `OrderBook` still enforces it; no captured Polymarket book was crossed.
- Unlike Kalshi (D-008), Polymarket US returns an explicit two-sided book, so
  there is **no `1 - x` implied-ask synthesis** — D-008's per-venue caveat is
  satisfied by not reusing that trick here (see D-009).
- Book timestamp: Polymarket US **does** provide `transactTime`, so the adapter
  uses it and treats `observed_at` as a documented fallback (contrast Kalshi).
- The adapter never reads Polymarket's genuine JSON floats
  (`orderPriceMinTickSize`, `feeCoefficient`); only string fields cross into the
  domain, so no float can leak (D-005).

## M1.4 notes (manual market-pair registry)

- A-018 and A-019 were introduced by the registry (`prediction_market_arbitrage.registry`).
  See `docs/DECISIONS.md` D-011 and `docs/MARKET_PAIRING.md`.
- The registry does **not** resolve or override A-013 / A-015 / A-016 (Polymarket
  US market/book semantics) or A-001 / A-002 / A-003. A `VERIFIED` pair means
  "contract equivalence has been human-reviewed for paper analysis" — it is not a
  live-trading approval. `live_use_eligible` must be `false` on every record in
  M1.4 (the loader rejects `true`).
- Title similarity is explicitly **not** evidence of equivalence; LLM/fuzzy
  semantic matching is deferred (D-006). The registry stores human decisions and
  performs no matching.
- The shipped `market_pairs.toml` contains **zero pairs** and no real venue
  identifiers. Worked format examples live only in `docs/MARKET_PAIRING.md` and
  `tests/test_market_pair_registry.py`, using synthetic ids
  (`kalshi-test-market`, `polymarket-test-market`).

## M1.5 notes (deterministic arbitrage engine)

- A-020 through A-023 were introduced by the arbitrage engine
  (`prediction_market_arbitrage.arbitrage`). See `docs/DECISIONS.md` D-012 and
  `docs/ARBITRAGE_METHODOLOGY.md`.
- The engine is a pure function; it evaluates a pair only if its status is
  `VERIFIED` (registry gate, not bypassable — `evaluate_from_registry` also
  checks `registry.eligible()`).
- A positive `net_edge` is **necessary, not sufficient** for realized profit.
  Leg risk, one-sided fills, latency/staleness beyond the freshness guards,
  unverified fees (A-022), and settlement edge cases are all deferred to the
  paper broker / risk work (M2.4 / M2.5). No engine result or synthetic test is
  a claim of real-world profitability.
- The engine does **not** resolve A-001/A-002/A-003 or A-013/A-015/A-016; a
  VERIFIED pair with a positive edge is still not live-approved.
- Same-market complete-set arbitrage (a ROADMAP M1.5 bullet) is **not**
  implemented — `MarketPairRecord` is cross-venue by construction. Flagged for a
  future registry extension.

## M1.6 notes (evidence-backed venue fee models)

- Work lives on `feat/venue-fee-models`, branched from `origin/main` after M1.5
  merged there (D-013).
- A-024 / A-025 hold the venue **taker** fee formulas; A-026 records the
  per-fill-slice rounding choice and stays explicitly unresolved. A-022 is
  SUPERSEDED (the fee-formulas-unknown part), not deleted — the
  injected-`FeeModel` design and the baseline/synthetic models are unchanged
  (D-012, D-013).
- **Kalshi** tracks the current "7.7.26 Update" schedule:
  `round_up_cent(M · 0.07 · C · P · (1−P))`, `M` a per-contract multiplier
  (default `1`). The old standalone `0.035` S&P 500 / Nasdaq-100 coefficient is
  gone — such series now carry a multiplier in Kalshi's per-series
  "non-standard fees" table (present in the current PDF; no value transcribed
  or hardcoded — A-024). `KalshiTradingFeeModel(multiplier=…)` takes an
  evidence-backed `M`; it cannot detect a series from an `OrderBook`.
- **Polymarket US** stays at the primary-source taker `Θ = 0.06` (re-verified
  2026-09-06). A prompt's `0.05` claim was **not adopted** — it is contradicted
  by the live official schedule (A-025).
- Primary-source extracts are retained under `docs/evidence/`; the Kalshi PDF
  opens in a normal browser but blocks plain CLI fetchers, and Polymarket's
  page is client-rendered.
- Only the **taker** path is modelled — the buy/buy engine always lifts asks.
  Kalshi maker (`M · 0.0175`) and Polymarket US maker **rebate** (`−0.0125`) and
  the Polymarket US volume-tier taker rebate are documented but not computed; a
  rebate is a negative fee the `FeeModel` contract does not represent.
- The models do **not** resolve fee reconciliation for the real-money gate:
  no formula has been OBSERVED against a real fill, multi-level-sweep rounding
  is unverified (A-026), a caller must supply the right Kalshi series `M` from
  the current PDF, and the Polymarket US category / CFTC-filing coefficient
  questions are open (A-025).

### Live-execution gate (M1.3)

- The M1.3 Polymarket US adapter is **market-data only**. Live/real-money
  trading remains disabled (D-002; ROADMAP "Real-money gate").
- **A-012, A-013, A-015, A-016 are unresolved market/book semantics and MUST NOT
  be relied on for live execution.** In particular: which side the single book
  represents (A-013), whether slug-only identifiers are enough to route and
  reconcile orders (A-015), and whether the normalized `Market.title` is correct
  (A-016) are all UNVERIFIED. Each must be confirmed with primary evidence
  (official docs/SDK behaviour or a real authenticated round-trip) before any
  Polymarket US market flows into a paper broker leg that could be promoted to
  live, and before any cross-venue pair is trusted (A-001, D-006).
