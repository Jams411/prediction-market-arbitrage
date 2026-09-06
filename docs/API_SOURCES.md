# API Sources

Evidence log for every external-API claim the code depends on. One row per claim.

## Evidence status values

- **VERIFIED** — confirmed by an official source (docs / OpenAPI / SDK).
- **OBSERVED** — directly seen in a real response we captured.
- **TESTED** — a deterministic offline test pins the behavior.
- **ASSUMPTION** — reasonable but unconfirmed.
- **UNKNOWN** — insufficient evidence.

A claim may carry more than one status (e.g. VERIFIED + OBSERVED + TESTED).

---

## Kalshi — REST market data (M1.2)

Verification date: **2026-09-05** (UTC 2026-09-06 per server `date` header).
Live capture host: `external-api.kalshi.com` (production) and
`external-api.demo.kalshi.co` (demo). All requests **unauthenticated** — no API
key, no account, no signature headers.

### Official sources consulted

| # | Source | URL |
|---|---|---|
| S1 | Get Markets — API reference | https://docs.kalshi.com/api-reference/market/get-markets |
| S2 | Get Market — API reference | https://docs.kalshi.com/api-reference/market/get-market |
| S3 | Get Market Orderbook — API reference | https://docs.kalshi.com/api-reference/market/get-market-orderbook |
| S4 | Orderbook Responses — getting started | https://docs.kalshi.com/getting_started/orderbook_responses |
| S5 | Quick Start: Market Data — getting started | https://docs.kalshi.com/getting_started/quick_start_market_data |
| S6 | OpenAPI spec | https://docs.kalshi.com/openapi.yaml |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| K-01 | Production REST base is `https://external-api.kalshi.com/trade-api/v2`. | VERIFIED + OBSERVED | S1–S5; live `GET /markets` → HTTP 200. | `adapters/kalshi/client.py` `PROD_BASE_URL` |
| K-02 | Demo REST base is `https://external-api.demo.kalshi.co/trade-api/v2`. | VERIFIED + OBSERVED | S5; live `GET /markets?limit=1` → HTTP 200. | `client.py` `DEMO_BASE_URL` |
| K-03 | `GET /markets` lists markets; response is `{ "markets": [...], "cursor": "..." }`. | VERIFIED + OBSERVED + TESTED | S1; live capture `tests/fixtures/kalshi/markets_list.json`. | `client.list_markets`, `normalize.parse_market_page` |
| K-04 | `GET /markets/{ticker}` returns `{ "market": { ... } }`. | VERIFIED + OBSERVED + TESTED | S2; live capture `tests/fixtures/kalshi/market_single.json`. | `client.get_market`, `normalize.parse_market` |
| K-05 | `GET /markets/{ticker}/orderbook` returns `{ "orderbook_fp": { "yes_dollars": [...], "no_dollars": [...] } }`. | VERIFIED + OBSERVED + TESTED | S3, S4; live capture `tests/fixtures/kalshi/orderbook.json`. | `client.get_market_orderbook`, `normalize.parse_order_books` |
| K-06 | Each order-book level is `[price_dollars_string, count_string]`; both are strings, count may be fractional (`"96.31"`, `"0.01"`). | VERIFIED + OBSERVED + TESTED | S4 ("Price as a dollar string ... `\"0.4200\"` = $0.42"); observed fractional counts in K-05 capture. | `normalize._parse_levels` (rejects non-string price/size) |
| K-07 | Order-book arrays are **bids only**, in **ascending** price order; the best (highest) bid is the **last** element. | VERIFIED + OBSERVED + TESTED | S4 ("ascending order", "highest bid ... is the last element"); in K-05 capture, last `yes_dollars` price `0.2000` == market `yes_bid_dollars`, last `no_dollars` price `0.7900` == market `no_bid_dollars`. | `normalize._bid_levels` (reverses to descending) |
| K-08 | For a binary market the sides are complementary: a YES bid at price X implies a NO ask at `1 - X`; a NO bid at Y implies a YES ask at `1 - Y`. Ask size = the implying bid's size. | VERIFIED + OBSERVED + TESTED | S4 ("A YES BID at price X is equivalent to a NO ASK at price ($1.00 - X)"); K-04 market has `yes_ask_dollars` `0.2100` == `1 - no_bid 0.7900`, `no_ask_dollars` `0.8000` == `1 - yes_bid 0.2000`; `market_type` == `"binary"`, `notional_value_dollars` == `"1.0000"`. | `normalize._implied_ask_levels` |
| K-09 | Public market-data endpoints (`/markets`, `/markets/{ticker}`, `/markets/{ticker}/orderbook`) require **no authentication**. | OBSERVED + VERIFIED (partial) | Live: unauthenticated `GET` on all three → HTTP 200 (production **and** demo). S6 OpenAPI lists `security: []` for markets endpoints; S5 states market data is public. **Conflict:** S3's rendered page shows an "Authentication Required" block listing `KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP`. Observation overrides the S3 rendering for market data. | whole adapter (no auth code) |
| K-10 | `GET /markets/{ticker}` for an unknown ticker → HTTP 404 with body `{"error":{"code":"not_found","message":"not found"}}`. | OBSERVED + TESTED | Live `GET /markets/NOPE-DOES-NOT-EXIST` → 404; body captured as `tests/fixtures/kalshi/error_not_found.json`. | `client._http_error`, `KalshiHTTPError` |
| K-11 | `GET /markets/{ticker}/orderbook` for an unknown/edgeless market → HTTP 200 with empty arrays `{"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}` (it does **not** 404). | OBSERVED + TESTED | Live: bad ticker on production and an edgeless demo market both returned this. Fixture `tests/fixtures/kalshi/orderbook_empty.json`. | `normalize.parse_order_books` (empty sides allowed) |
| K-12 | Market objects carry monetary values as dollar strings under `*_dollars` keys (`yes_bid_dollars`, `last_price_dollars`, ...) and sizes as fixed-point strings under `*_fp` keys. Timestamps are ISO-8601 UTC (`...Z`, sometimes with microseconds). | OBSERVED | K-03/K-04 captures. | `normalize.parse_market`, `_parse_timestamp` |
| K-13 | `GET /markets` supports `status`, `series_ticker`, `event_ticker`, `tickers`, `limit` (max 1000), `cursor` query params. | VERIFIED | S1. | `client.list_markets` |
| K-14 | `GET /markets/{ticker}/orderbook` supports optional `depth` (0–100; 0 = all levels). | VERIFIED | S3. | `client.get_market_orderbook` |

### Real API calls made during verification (all unauthenticated)

| Method + path | Host | HTTP status |
|---|---|---|
| `GET /trade-api/v2/markets?limit=2&status=open` | production | 200 |
| `GET /trade-api/v2/markets?limit=1000&status=open` | production | 200 |
| `GET /trade-api/v2/markets?series_ticker=KXHIGHNY&status=open&limit=3` | production | 200 |
| `GET /trade-api/v2/markets/KXHIGHNY-26SEP06-T73` | production | 200 |
| `GET /trade-api/v2/markets/KXHIGHNY-26SEP06-T73/orderbook` | production | 200 |
| `GET /trade-api/v2/markets/NOPE-DOES-NOT-EXIST` | production | 404 |
| `GET /trade-api/v2/markets/NOPE-DOES-NOT-EXIST/orderbook` | production | 200 (empty) |
| `GET /trade-api/v2/markets?limit=1` | demo | 200 |
| `GET /trade-api/v2/markets/KXHIGHNY-26SEP06-T73/orderbook` | demo | 200 (empty) |

### Sanitized fixtures captured

Location: `tests/fixtures/kalshi/`. Contents are public market data only — no
credentials, account identifiers, or request/response auth headers. Long public
free-text fields (`rules_primary`, `rules_secondary`, `early_close_condition`)
were truncated to ≤120 chars; all price / size / timestamp / identifier fields
are verbatim.

| File | Source call |
|---|---|
| `markets_list.json` | `GET /markets?series_ticker=KXHIGHNY&status=open&limit=3` |
| `market_single.json` | `GET /markets/KXHIGHNY-26SEP06-T73` |
| `orderbook.json` | `GET /markets/KXHIGHNY-26SEP06-T73/orderbook` |
| `orderbook_empty.json` | observed empty-book shape (demo / unknown ticker) |
| `error_not_found.json` | `GET /markets/NOPE-DOES-NOT-EXIST` (404 body) |

### Not verified / out of scope for M1.2

- WebSocket market-data feed (documented for M2.1; interface only, no code here).
- Whether every market type (`scalar`, multivariate `KXMVE*`) exposes the same
  `*_dollars` fields — the adapter **rejects** non-`binary` `market_type`.
- Historical/candlestick/trades endpoints.
- Rate limits for unauthenticated market-data requests.
- Long-term stability of the `orderbook_fp` shape vs. an older cents-based
  `orderbook.{yes,no}` shape seen in some third-party write-ups (not observed).
