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

## Journal rules

- Record only material progress, evidence, blockers, and changes in direction.
- Do not use this file as a dump of terminal output.
- Link detailed reasoning to `DECISIONS.md`, assumptions to `ASSUMPTIONS.md`, and validation requirements to `TEST_PLAN.md`.
