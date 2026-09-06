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
