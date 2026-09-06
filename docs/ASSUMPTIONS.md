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
