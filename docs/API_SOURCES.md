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

---

## Polymarket US — REST market data (M1.3)

Verification date: **2026-09-05** (UTC 2026-09-06 per server `date` header).
Live capture host: `gateway.polymarket.us`, endpoints under `/v1`. All requests
**unauthenticated** — no API key, cookie, or account. (Responses set Cloudflare
`__cf_bm` / `_cfuvid` bot-management cookies; these are **not** auth and the
adapter never sends or stores cookies.)

### Official sources consulted

| # | Source | URL |
|---|---|---|
| P-S1 | Official Python SDK repo (`polymarket-us`) | https://github.com/Polymarket/polymarket-us-python |
| P-S2 | Markets API overview | https://docs.polymarket.us/api-reference/market/overview |
| P-S3 | Get Markets | https://docs.polymarket.us/api-reference/markets/get-markets.md |
| P-S4 | Get Market Book | https://docs.polymarket.us/api-reference/markets/get-market-book.md |
| P-S5 | Python SDK quickstart | https://docs.polymarket.us/api-reference/sdks/python/quickstart |
| P-S6 | Docs index | https://docs.polymarket.us/llms.txt |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| P-01 | REST host is `https://gateway.polymarket.us`; market-data endpoints are under `/v1`. | VERIFIED + OBSERVED | P-S4 quotes `GET https://gateway.polymarket.us/v1/markets/{slug}/book`; live `GET /v1/markets` → 200. | `client.py` `PROD_BASE_URL` |
| P-02 | Market-data endpoints require **no authentication**. | VERIFIED + OBSERVED | P-S1 README section "Public Endpoints (No Authentication)" lists `markets.list/retrieve_by_slug/book/bbo`; P-S4 OpenAPI `security: []`; P-S5 "No authentication required for market data". Live: unauthenticated `GET` on `/v1/markets`, `/v1/market/slug/{slug}`, `/v1/markets/{slug}/book`, `/v1/markets/{slug}/bbo` all → 200. | whole adapter (no auth code) |
| P-03 | `GET /v1/markets` → `{ "markets": [ ... ] }`; paginates via `limit` / `offset`; filters include `active`, `closed`, `archived`, `slug`, `id`, `categories`, `marketTypes`. | VERIFIED + OBSERVED + TESTED | P-S3; live capture `tests/fixtures/polymarket_us/markets_list.json` (`?active=true&closed=false&limit=3`). | `client.list_markets`, `normalize.parse_market_page` |
| P-04 | `GET /v1/market/slug/{slug}` → `{ "market": { ... } }`. `GET /v1/market/id/{id}` is the id variant. | VERIFIED + OBSERVED + TESTED | P-S2; live capture `tests/fixtures/polymarket_us/market_single.json`. | `client.get_market_by_slug` / `get_market_by_id`, `normalize.parse_market` |
| P-05 | A Polymarket US market is a **single binary market**. `marketSides` holds **exactly two** entries: one `long: true` (tradeable long side, `description` e.g. `"Yes"` or a team name) and one `long: false` (complement). | OBSERVED + TESTED | Every captured market (`futures` and `moneyline`) had exactly 2 `marketSides` with one `long:true` + one `long:false`. `market_single.json`: `[{description:"Yes",long:true},{description:"No",long:false}]`. | `normalize._split_sides`; adapter builds `:LONG` and `:SHORT` contracts |
| P-06 | `GET /v1/markets/{slug}/book` → `{ "marketData": { marketSlug, bids[], offers[], state, stats, transactTime } }`. **One book per slug**, quoted in the long-side price space, with **explicit** `bids` and `offers` (not bid-only). | VERIFIED + OBSERVED + TESTED | P-S4; live capture `tests/fixtures/polymarket_us/orderbook.json`. `bbo.longQuote`/`shortQuote` and `stats.lastPriceSample.longPx` confirm the book is long-side. | `client.get_book`, `normalize.parse_order_book` |
| P-07 | Each book level is `{ "px": { "value": <decimal string>, "currency": "USD" }, "qty": <decimal string> }`. `value` and `qty` are strings; `qty` can be fractional (`"27.0000"`). | VERIFIED + OBSERVED + TESTED | P-S4 schema (`BookEntry.px: Amount{value,currency}`, `qty: string`); capture confirms. | `normalize._parse_levels` (rejects non-string / non-`USD`) |
| P-08 | Book `bids` are ordered highest→lowest, `offers` lowest→highest — already the domain's required order. | OBSERVED + TESTED | P-S4 does **not** document the order; live capture `orderbook.json` bids strictly descending, offers strictly ascending, and `bids[0]`/`offers[0]` equal `bbo.bestBid` / `bbo.bestAsk`. | `normalize._sorted_levels` still **sorts explicitly** and rejects duplicates — does not rely on source order |
| P-09 | `marketData.transactTime` is an RFC-3339 UTC timestamp ("when the market data was recorded"), with **nanosecond** precision (`"...446134874Z"`). | VERIFIED + OBSERVED | P-S4 ("Timestamp of data"); capture shows 9 fractional digits. | `normalize._parse_timestamp` truncates >6 fractional digits to microseconds before `datetime.fromisoformat` |
| P-10 | The book carries its own `transactTime`, so it is used as the `OrderBook` timestamp. `observed_at` (caller `clock()`) is the fallback only when the field is absent. | OBSERVED + TESTED | `transactTime` present in every book capture (including the empty book). | `normalize._book_timestamp`, `adapter.get_order_book` |
| P-11 | `GET /v1/markets/{slug}/bbo` → `{ "marketData": { marketSlug, bestBid: Amount, bestAsk: Amount, bidDepth, askDepth, state, ... } }`. **No `transactTime`** on the bbo payload. | OBSERVED + TESTED | Live capture `tests/fixtures/polymarket_us/bbo.json`. | `client.get_bbo`, `normalize.parse_bbo` |
| P-12 | Unknown slug → HTTP **404** with a gRPC-style body `{ "code": <int>, "message": <str>, "details": [] }` (not Kalshi's `{"error":{...}}`). | OBSERVED + TESTED | `GET /v1/market/slug/this-market-does-not-exist-xyz` → 404 `{"code":5,"message":"The server was unable to process your request.","details":[]}`; `.../book` → 404 `{"code":5,"message":"market with slug \"...\" not found",...}`. Fixture `error_not_found.json`. | `client._http_error`, `PolymarketHTTPError(code:int)` |
| P-13 | A live market can legitimately return a **fully empty** book (`bids: []`, `offers: []`). | OBSERVED + TESTED | `GET /v1/markets/tec-mlb-champ-2026-09-27-cin/book` → 200 with both arrays empty. Fixture `orderbook_empty.json`. | `normalize.parse_order_book` (empty sides allowed) |
| P-14 | Market/side objects also carry genuine JSON **floats** (`orderPriceMinTickSize: 0.001`, `feeCoefficient: 0.06`). | OBSERVED | Captures. | The adapter **never reads these** — only string fields (`px.value`, `qty`, `endDate`, `description`, `slug`, `question`) reach the domain. |

### Real API calls made during verification (all unauthenticated)

| Method + path | HTTP status |
|---|---|
| `GET /v1/markets` | 200 |
| `GET /v1/markets?active=true&closed=false&limit=25` (and `limit=40`) | 200 |
| `GET /v1/markets?active=true&closed=false&limit=3` | 200 |
| `GET /v1/market/slug/tec-mlb-nlchamp-2026-09-27-mil` | 200 |
| `GET /v1/markets/tec-mlb-nlchamp-2026-09-27-mil/book` | 200 |
| `GET /v1/markets/tec-mlb-nlchamp-2026-09-27-mil/bbo` | 200 |
| `GET /v1/markets/tec-mlb-champ-2026-09-27-cin/book` | 200 (both sides empty) |
| `GET /v1/markets/{various ~40 slugs}/book` | 200 (survey for empty-side books) |
| `GET /v1/market/slug/this-market-does-not-exist-xyz` | 404 |
| `GET /v1/markets/this-market-does-not-exist-xyz/book` | 404 |

### Market / Contract / OrderBook mapping

| Polymarket US | Domain model |
|---|---|
| market object (`/v1/market/slug/{slug}`) | `Market(venue=polymarket_us, id=slug, title=question, close_time=parse(endDate))` |
| `marketSides[ long == true ]` (`description` e.g. `"Yes"`) | `Contract(market, id=f"{slug}:LONG", outcome=description)` — book side |
| `marketSides[ long == false ]` (`description` e.g. `"No"`) | `Contract(market, id=f"{slug}:SHORT", outcome=description)` — materialized for later pairing; no separate book exists |
| `book.marketData.bids` | `OrderBook.bids` (sorted desc, deduped) |
| `book.marketData.offers` | `OrderBook.asks` (sorted asc, deduped) |
| level `{px:{value},qty}` | `PriceLevel(price=Decimal(px.value), quantity=Decimal(qty))` |
| `book.marketData.transactTime` | `OrderBook.timestamp` (fallback: caller `observed_at`) |

One market → **one** `OrderBook`, on the `:LONG` contract. Unlike Kalshi (D-008),
there is **no `1 - x` implied-ask synthesis** — Polymarket US already returns both
book sides. The domain model represents the observed semantics with no distortion.

### Sanitized fixtures captured

Location: `tests/fixtures/polymarket_us/`. Public market data only — no
credentials, cookies, account identifiers, or auth headers. Sanitization:
recursively dropped bulky sports-media sub-objects (`team`, `*Icon`, `image`,
`logo`) and truncated `description` to ≤120 chars; every price / qty / timestamp
/ id / slug / `long` / side-`description` field is verbatim.

| File | Source call |
|---|---|
| `markets_list.json` | `GET /v1/markets?active=true&closed=false&limit=3` |
| `market_single.json` | `GET /v1/market/slug/tec-mlb-nlchamp-2026-09-27-mil` |
| `orderbook.json` | `GET /v1/markets/tec-mlb-nlchamp-2026-09-27-mil/book` |
| `orderbook_empty.json` | `GET /v1/markets/tec-mlb-champ-2026-09-27-cin/book` (both sides empty) |
| `bbo.json` | `GET /v1/markets/tec-mlb-nlchamp-2026-09-27-mil/bbo` |
| `error_not_found.json` | 404 body from `GET /v1/market/slug/this-market-does-not-exist-xyz` |

### Not verified / out of scope for M1.3

- WebSocket feed (M2.1).
- Non-binary / multi-outcome markets: none observed. The adapter **rejects** any
  market whose `marketSides` is not exactly one long + one short.
- Whether `question` vs `title` vs `subtitle` is the right label for every market
  type — the adapter uses `question`.
- `MarketState` / `state` enum handling (captured as an opaque string, not used).
- Pagination cursor semantics beyond `limit` / `offset`.
- Rate limits for unauthenticated requests.
- Demo/sandbox host (none found for Polymarket US).
- **A-013** (the single book is the long-side book) — price alignment was
  OBSERVED but no primary doc/SDK statement confirms it. Remains UNVERIFIED.
- **A-015** (slug-only traceability is enough for order routing / reconciliation)
  — untested. Remains UNVERIFIED.

**Live-execution gate:** M1.3 is market-data only. The unresolved market/book
semantics above (A-012, A-013, A-015, A-016) **must not be relied on for live
execution**. Real-money trading stays disabled (D-002; ROADMAP "Real-money
gate") until each is confirmed by primary evidence.

---

## Kalshi — WebSocket order book (M2.1)

Verification date: **2026-09-06** (docs read; **no live socket connection** —
the channel requires API-key auth in the handshake, which M2.1 does not do).

### Official sources consulted

| # | Source | URL |
|---|---|---|
| K-WS-S1 | Orderbook Updates (AsyncAPI) | https://docs.kalshi.com/websockets/orderbook-updates |
| K-WS-S2 | WebSocket Connection | https://docs.kalshi.com/websockets/websocket-connection |
| K-WS-S3 | Quick Start: WebSockets | https://docs.kalshi.com/getting_started/quick_start_websockets |
| K-WS-S4 | Connection Keep-Alive | https://docs.kalshi.com/websockets/connection-keep-alive |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| K-WS-01 | Production WebSocket host is `wss://external-api-ws.kalshi.com`; the connection requires API-key auth in the handshake (public channels included). | VERIFIED (docs) | K-WS-S1 `servers.production`; K-WS-S2. | Not connected in M2.1; recorded for the transport boundary. |
| K-WS-02 | The `orderbook_delta` channel sends one `orderbook_snapshot` then incremental `orderbook_delta` messages. Every message carries `sid` (subscription id) and `seq` (integer, per-subscription, sequential) — "checked ... to guarantee you received all the messages ... snapshot/delta consistency". | VERIFIED (docs) | K-WS-S1 AsyncAPI payload schemas + `seq` description. | `livebook/kalshi_ws.py`; `LiveBookFeed` sequence check. |
| K-WS-03 | `orderbook_snapshot.msg` = `{ market_ticker, market_id, yes_dollars_fp?, no_dollars_fp? }`; each side is an optional array of `[price_dollars, contract_count_fp]` **string** pairs — the **same** level shape and bids-only-per-side YES/NO semantics as the REST `orderbook_fp` payload (K-06/K-07/K-08). Absent side key = no offers on that side. | VERIFIED (docs) + reuses OBSERVED REST semantics | K-WS-S1 schema + example; K-06/K-08. | `decode_orderbook_snapshot` (reuses the `1 - opposite_bid` implied-ask rule). |
| K-WS-04 | `orderbook_delta.msg` = `{ market_ticker, market_id, price_dollars:str, delta_fp:str (signed, "2 decimals"), side:"yes"\|"no", ts_ms?:int (Unix ms), ts?:str (deprecated) }`. | VERIFIED (docs) | K-WS-S1 schema + example (`{"price_dollars":"0.960","delta_fp":"-54.00","side":"yes"}`). | `decode_orderbook_delta`. |
| K-WS-05 | `update_subscription` supports `add_markets` / `delete_markets` / `get_snapshot`; `get_snapshot` returns a fresh `orderbook_snapshot` **without** changing the subscription. | VERIFIED (docs) | K-WS-S1 requirements list. | The transport's resync primitive; `LiveBookFeed.begin_resync()` + the next `apply_snapshot()` model it. |
| K-WS-06 | Keep-alive: the server sends Ping frames every ~10s with body `heartbeat`; the client replies Pong. | VERIFIED (docs) | K-WS-S4. | Transport concern; not in M2.1 code. |

### Not verified / assumptions (M2.1)

- **A-028** — that `delta_fp` is applied **additively** to the aggregated
  contract count already at that `(side, price)` level (result 0 ⇒ level
  removed). The channel description ("incremental updates to maintain a live
  orderbook") plus a signed fixed-point value support no other reading, but the
  exact application rule is not spelled out and is **not OBSERVED** against a
  real feed. `livebook/state.py` implements additive application.
- No live frames captured (auth-gated handshake); no sanitized WS fixture.
- Market lifecycle / trading-state changes ride a **separate** channel
  (`market-and-event-lifecycle`), not decoded here (**A-029**) — the Kalshi live
  book carries no `market_state`.

---

## Kalshi — production live market-data observation (2026-09-09, Real-money gate #2)

A bounded, **unauthenticated, read-only** production session against
`https://external-api.kalshi.com/trade-api/v2` (K-01 / K-09: public REST market
data). Tool: `scripts/observe_kalshi_prod_market_data.py`; sanitised evidence in
`docs/evidence/kalshi-live/market-data/` (SUMMARY + a structure-only sample —
every price/size scalar → a type token). **No WebSocket** — Kalshi's production
market-data WS requires API-key auth in the handshake (K-WS-01) and no
production Kalshi credential exists in this environment.

| # | Claim | Status | Evidence | Gate impact |
|---|-------|--------|----------|-------------|
| K-MD-OBS-01 | **REST snapshot initialisation** against production works: `GET /markets/{ticker}/orderbook` → HTTP **200** with the documented `{ "orderbook_fp": { "yes_dollars": [...], "no_dollars": [...] } }` shape (K-05); level pairs are `[price_string, size_string]` (K-06). Sampled market `KXBTCD-26SEP0904-T84299.99` (a Bitcoin-daily binary), 28 `no_dollars` levels / 0 `yes_dollars` (one-sided near the threshold). | OBSERVED (production) | `market-data/01_rest_snapshot_shape.json` (200); `market-data/SUMMARY.json`. | Partial support for gate #2 "REST snapshot initialization" — REST path only. |
| K-MD-OBS-02 | **Sustained availability + a live book.** 44 polls of the same orderbook over **300.2 s wall** (6 s interval), session `2026-09-09T07:28:05Z … 07:33:05Z`: HTTP-status histogram **`{200: 44}`** (100 %), market `status` field `"active"` throughout, and **8 distinct book states / 7 changes** with a max gap of ~64 s between changes. This is a real sustained session (UTC start/end + 44 timed samples), not a one-message smoke test, and the book demonstrably updates. | OBSERVED (production) | `market-data/SUMMARY.json` (`polls`, `orderbook_status_histogram`, `distinct_book_states_observed`, `polls_with_book_change`, `session_start/end_utc`, `wall_elapsed_s`, `per_poll[]`). | Supports "the production market-data service is reachable and stable over minutes, and the book is live" — **for REST**, not the WS feed. |
| K-MD-OBS-03 | **Transport failure + recovery (REST analog only).** A GET to an unreachable host raised `URLError`; the next GET to the real endpoint returned **200**. This is *not* a WebSocket disconnect/resync — no stream, no `seq`, no `get_snapshot`, no `LiveBookFeed` state transition. | OBSERVED (production, REST) | `market-data/SUMMARY.json` (`transport_failure_probe`, `recovery_after_failure_status`). | Does **not** satisfy gate #8; recorded only to bound what REST can show. |
| K-MD-OBS-04 | **Not verified here** (blocked on a missing production Kalshi credential; creating one was out of scope): WebSocket connection success, real WS `orderbook_snapshot`/`orderbook_delta` receipt, per-subscription `seq` / snapshot-then-delta ordering (K-WS-02), stream disconnect detection, reconnect + `get_snapshot` resync (K-WS-05), and `LiveBookFeed` `HealthStatus` transitions across a real reconnect. **A-030** and **A-028** remain **UNVERIFIED**. **PARTLY SUPERSEDED 2026-09-09 by K-WS-OBS-01..08:** WS connect, snapshot + one delta receipt, per-subscription `seq` ordering (1→2), and clean disconnect → reconnect → resubscribe → fresh-snapshot resync are now OBSERVED against production; still not verified — a sustained feed, an unexpected disconnect + its detection, `LiveBookFeed`/`HealthStatus` transitions, and **A-028**. | UNKNOWN (state now partly changed) | — (no WS session at the time) | Gate #2 stays **unchecked**; #7 and #8 unchanged. |

**Real-money gate #2 verdict (updated 2026-09-09 after the WS session):**
*partially* supported. Now OBSERVED against production: REST snapshot init +
multi-minute service/book liveness (K-MD-OBS-01..02) **and** an authenticated WS
connect, `orderbook_snapshot` receipt on two connections, one `orderbook_delta`,
sequential per-subscription `seq` (1→2), and a clean disconnect → reconnect →
resubscribe → fresh-snapshot resync (K-WS-OBS-01..07). Still **not** verified —
the item's core wording, a **stable live feed**: the WS session was ~35 s with a
single delta (the first connection idle-timed-out after its snapshot), so
*sustained* `seq`-ordered updates over a meaningful window are unproven, and no
`LiveBookFeed`/`FeedHealth` state was tracked ("healthy state throughout" not
shown). **Item #2 remains unchecked.** Gate #7 (stale-data handling): **not**
advanced — no staleness event and no `LiveBookFeed` gating was exercised against
the live feed. Gate #8 (disconnect/reconnect): the resubscribe/resync
*mechanism* is now proven against prod, but the run used a **clean client-side
close**, not an unexpected drop, and captured **no** `HEALTHY → DISCONNECTED →
RESYNCING → HEALTHY` transition — so **#8 remains unchecked**.

> **SUPERSEDED 2026-09-09 by the live-book runtime observation
> (K-LB-OBS-01..12, section below).** A later same-day session run through the
> shipped `LiveBookConnection` / `LiveBookFeed` collected 30 sequential deltas
> over ~14 s of continuous consumption (0 desyncs, monotone `seq`, `HEALTHY`
> throughout) plus the `HEALTHY → STALE → DISCONNECTED → RESYNCING → HEALTHY`
> transitions. **Gate #2 is now CHECKED.** #7 and #8 stay unchecked (staleness
> and the disconnect were harness-induced). See that section's verdict.

### Kalshi — production authenticated WS: auth re-verified + observation path prepared (2026-09-09)

Docs re-checked against the official Kalshi sources (WS-A-S1 `quick_start_websockets`,
WS-A-S2 `quick_start_authenticated_requests`) on 2026-09-09. Every production
WebSocket auth fact already recorded (K-WS-AUTH-01..04) is **unchanged**:

- URL `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (prod).
- Handshake headers `KALSHI-ACCESS-KEY` / `KALSHI-ACCESS-TIMESTAMP` (Unix **ms**
  string) / `KALSHI-ACCESS-SIGNATURE` (base64).
- Signed message = `timestamp + "GET" + "/trade-api/ws/v2"`; RSA-PSS,
  MGF1-SHA256, salt length = `PSS.DIGEST_LENGTH` (= 32), over SHA-256.
- Subscribe: `{"id":<int>,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_ticker":"…"}}`
  (`market_tickers` array for many). Channel re-sends one `orderbook_snapshot`
  then incremental `orderbook_delta` (K-WS-02) — so **resubscribe on a new
  connection is a full resync**.
- "even channels that carry public market data still use the authenticated
  WebSocket session, but they do not impose additional per-channel authorization
  checks" — i.e. auth is required for the socket, not per channel (matches K-WS-01).

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| K-WS-AUTH-05 | **Production API-key requirement.** The production WS needs a Kalshi RSA API key. Current docs expose key scopes (K-TR-22), so the earlier 2026-09-09 statement that keys were unscoped is superseded. Private key material still downloads once and must remain secret. | VERIFIED (docs), corrected 2026-09-10 | WS-A-S1; WS-A-S2; K-TR-S18/S19. |
| K-WS-AUTH-06 | **One RSA-PSS implementation covers REST and WS signing, but authorization is separate.** The same key algorithm signs both surfaces; the signed message still includes the request method/path. Current key scopes can independently permit or deny endpoint groups, so signer correctness does not establish trading authorization. Read-only scripts also remain read-only by the requests they issue. | VERIFIED (docs) + design, corrected 2026-09-10 | WS-A-S2; K-TR-03; K-TR-22. |
| K-WS-AUTH-07 | **Reusable RSA-PSS signer now exists.** `scripts/kalshi_signer.py` — `OpensslRsaPssSigner` (implements `livebook.Signer`; `openssl dgst -sha256 -sign … -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:digest -binary`, keeping the repo's zero-crypto-dependency posture, same approach as `observe_kalshi_demo.py`) + `read_keychain_password`. Private key is read from a file path only — never env, never CLI, never logged; `repr` shows only the path. Offline tests (`tests/test_kalshi_signer.py`) generate a throwaway RSA key with `openssl` and round-trip verify with the matching public key, incl. through `kalshi_ws_handshake`. Partly resolves the "no `Signer` implementation in the repo" half of **A-030**. | TESTED (offline) — no live venue | `scripts/kalshi_signer.py`; `tests/test_kalshi_signer.py`. |
| K-WS-AUTH-08 | **Read-only WS observation path — EXECUTED 2026-09-09.** `scripts/observe_kalshi_prod_ws_market_data.py --observe` was run once by the operator with a manually-created production key (Keychain `pma-kalshi-prod-api-key-id` + `~/.config/pma/kalshi-prod-private-key.pem`). It built the handshake via `kalshi_ws_handshake` + `OpensslRsaPssSigner`, connected with `WebsocketsTransport`, subscribed one production market's `orderbook_delta`, recorded `seq` + a structure-only sanitised snapshot/delta, disconnected (clean client close), reconnected + resubscribed on a fresh connection, then disconnected. No `/portfolio` call, no order/balance/position/fill access, no `LIVE_TRADING` read, no Polymarket US. Results: K-WS-OBS-01..08 below. | OBSERVED (production) | `docs/evidence/kalshi-live/ws-market-data/SUMMARY.json`; `scripts/observe_kalshi_prod_ws_market_data.py`. |

### Kalshi — production authenticated WS session (OBSERVED 2026-09-09)

One session, `2026-09-09T15:29:36.952Z … 15:30:12.283Z` (~35 s wall, two
connections). Evidence: `docs/evidence/kalshi-live/ws-market-data/SUMMARY.json`
(sanitised — every price/size/ticker/id scalar → a type token; `seq`/`sid`
kept as `"<number>"`, counts and frame-type histogram kept verbatim).

| # | Claim | Status | Evidence | Gate impact |
|---|-------|--------|----------|-------------|
| K-WS-OBS-01 | **The authenticated production handshake is accepted by the real Kalshi server.** Both connections to `wss://external-api-ws.kalshi.com/trade-api/ws/v2` with the `KALSHI-ACCESS-KEY` / `-TIMESTAMP` (ms) / `-SIGNATURE` (base64 RSA-PSS/SHA-256, salt = digest length) headers built by `livebook.ws_auth.kalshi_ws_handshake` + `scripts.kalshi_signer.OpensslRsaPssSigner` opened successfully and received frames. | OBSERVED (production) | `SUMMARY.json` `ws_url`, `auth`, `first_connection`/`after_reconnect_resubscribe` both non-empty. | Confirms the **Kalshi half of A-030** (handshake + header names + sign string match the live venue). |
| K-WS-OBS-02 | **Subscribe command shape is accepted; the ack frame type is `subscribed`.** Each connection sent `{"id":<int>,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_tickers":["…"]}}` (K-WS-AUTH-04) and the server replied with one frame of type `subscribed` (not `ok`), then market-data frames. `livebook.transport.kalshi_frame_decoder` already routes any non-snapshot/delta frame to `[]`, so this ack needs no decoder change. | OBSERVED (production) | `SUMMARY.json` `frame_type_histogram` (`"subscribed": 1` per connection). | Confirms the subscribe body form against the live venue (A-030, Kalshi). New fact: ack type string is `subscribed`. |
| K-WS-OBS-03 | **`orderbook_snapshot` received and decoded on both connections.** Each connection got exactly 1 `orderbook_snapshot`; `livebook.kalshi_ws.decode_orderbook_snapshot` accepted the real frame without error. Observed `msg` = `{market_ticker, market_id, no_dollars_fp:[[price,count],…]}` with `yes_dollars_fp` **absent** (one-sided book — allowed by K-WS-03 "absent side key = no offers on that side"). Level pairs are `[string, string]` (K-WS-03 / K-06). | OBSERVED (production) | `SUMMARY.json` `first_snapshot_shape` (both sessions). | Confirms K-WS-03 snapshot shape against the live venue. |
| K-WS-OBS-04 | **`orderbook_delta` received and decoded (1 frame, reconnect session).** `livebook.kalshi_ws.decode_orderbook_delta` accepted the real frame. Observed `msg` = `{market_ticker, market_id, price_dollars:str, delta_fp:str, side:str, ts_ms:int, ts:str}` — **both** `ts_ms` (int) and the deprecated `ts` (string) are present (K-WS-04). | OBSERVED (production) | `SUMMARY.json` `after_reconnect_resubscribe.first_delta_shape`. | Confirms K-WS-04 delta shape against the live venue. Does **not** verify **A-028** (additive application): the delta was decoded, never applied to a book; values redacted. |
| K-WS-OBS-05 | **Per-subscription `seq` is sequential and starts at 1.** Reconnect session: snapshot `seq = 1`, then delta `seq = 2`; `seq_strictly_increasing = true`. First session: snapshot `seq = 1` only (no delta arrived). | OBSERVED (production) | `SUMMARY.json` `seq_values` (`[1]` and `[1,2]`), `seq_strictly_increasing`. | Confirms K-WS-02 snapshot-then-delta ordering with a sequential per-subscription counter — **for a single delta**. Not a sustained `seq`-ordered stream. |
| K-WS-OBS-06 | **`seq` resets to 1 for a new subscription on a new connection.** The reconnect session's fresh `subscribe` produced a new snapshot at `seq = 1` (not continuing from the first session). | OBSERVED (production) | `SUMMARY.json` `first_connection.seq_values` `[1]` vs `after_reconnect_resubscribe.seq_values` `[1,2]`. | Confirms `seq` is **per-subscription**, not per-connection or global (K-WS-02). |
| K-WS-OBS-07 | **Clean disconnect → reconnect → resubscribe → fresh snapshot works against production.** After `t1.close()` a second `WebsocketsTransport` connected with a fresh handshake, resubscribed, and the channel re-sent a full `orderbook_snapshot` (then a delta). This is the "resubscribe = full resync" path (K-WS-02) proven end-to-end against the live server. | OBSERVED (production) | `SUMMARY.json` `resync_delivered_fresh_snapshot = true`; `after_reconnect_resubscribe.snapshots = 1`. | The resync **mechanism** works against prod. **Not** an unexpected/server-initiated drop, and no `FeedHealth` state machine was involved (see K-WS-OBS-08). |
| K-WS-OBS-08 | **Not observed in this session:** a sustained multi-minute feed; more than one `orderbook_delta`; an unexpected/server-side disconnect and its detection; `livebook.state.LiveBookFeed` / `FeedHealth` `HEALTHY → DISCONNECTED → RESYNCING → HEALTHY` transitions (the script drove `WebsocketsTransport` + decoders directly, never `LiveBookFeed` / `LiveBookConnection`); staleness gating; **A-028** additive-delta application. | UNKNOWN | — (out of scope of this run) | Gate **#2 / #7 / #8 stay unchecked** — see the verdict below. |

**No `/portfolio` call, no order call, no balance/position/fill read, no
`LIVE_TRADING` read or set, no Polymarket US** (`SUMMARY.json` `notes`;
K-WS-AUTH-06). Credentials were read from the Keychain + PEM file at run time and
never printed, logged, persisted, or fixtured. **A-030 is now resolved for the
Kalshi half** (handshake / subscribe / snapshot / delta formats match the live
production server); the **Polymarket US half of A-030 stays UNVERIFIED**.
(K-WS-OBS-08's "not observed" list and the "gate #2/#7/#8 stay unchecked" note
are **partly superseded** by the runtime observation below — K-LB-OBS-01..12.)

### Kalshi — production live-book *runtime* observation (OBSERVED 2026-09-09, gate #2)

One bounded session through the **shipped runtime**
(`livebook.LiveBookConnection` + `livebook.LiveBookFeed` +
`livebook.ws_transport.WebsocketsTransport` + a REST `SnapshotSource` over
`KalshiMarketDataAdapter`), not the standalone WS script. Read-only market data
only. Tool: `scripts/observe_kalshi_livebook_runtime.py --observe 30 240`.
Session `2026-09-09T21:12:25.085Z … 21:13:32.948Z` (67.9 s wall), a BTC-daily
binary market (ticker redacted in evidence). Sanitised evidence:
`docs/evidence/kalshi-live/livebook-runtime/SUMMARY.json` — a phase timeline with
UTC timestamps + offsets, per-feed `HealthStatus` / `trading_enabled` /
`last_sequence`, `DeltaOutcome` tallies, per-subscription `seq` epochs, value-free
book fingerprints, and an additive-delta (A-028) relationship check. **No** raw
prices / sizes / tickers / ids; no `/portfolio`, order, balance/position/fill
access; `LIVE_TRADING` never read or set; no Polymarket US.

| # | Claim | Status | Evidence | Gate impact |
|---|-------|--------|----------|-------------|
| K-LB-OBS-01 | **Initial REST snapshot / live-book initialization.** `RestSnapshotSource.fetch` (public prod REST) → `LiveBookFeed.apply_snapshot` for the YES and NO contracts; both feeds `UNINITIALIZED → HEALTHY` (`trading_enabled` false → true) at t≈0.4 s. | OBSERVED (production) | `SUMMARY.json` timeline `A_init/rest_snapshot_applied` (`books`: YES 26 bid/13 ask, NO 13 bid/26 ask levels, initialized). | Part of #2 "REST snapshot initialization" — now via the real runtime, not a bespoke script. |
| K-LB-OBS-02 | **WS subscription success through the runtime.** `LiveBookConnection.connect_and_subscribe()` opened `wss://external-api-ws.kalshi.com/trade-api/ws/v2` with the RSA-PSS handshake and the K-WS-AUTH-04 subscribe body; delta frames began flowing immediately. | OBSERVED (production) | timeline `B_steady/ws_connect_and_subscribe` then `pumped_30_deltas`. | #2. |
| K-LB-OBS-03 | **Sustained applied deltas.** **30** `orderbook_delta` messages applied via `LiveBookFeed.apply_delta` over a **~14 s continuous consumption window** (t 0.7→14.5 s), `delta_outcomes = {applied: 30}` — **no** `DUPLICATE` / `STALE_SEQUENCE` / `SEQUENCE_GAP` / `NEGATIVE_QUANTITY` / `CROSSED_RESULT`. A further **17** buffered deltas applied cleanly during the phase-D drain (`last_sequence` 16→33). Both feeds `HEALTHY` throughout. | OBSERVED (production) | `applied_delta_count = 34` (30 in B + 4 in F), `delta_outcomes`, timeline health at `pumped_30_deltas` (`healthy`, seq 16); `buffered_frames_drained_before_detection = 17`. | #2 "stable live feed" — a real sustained `seq`-ordered stream through the runtime. |
| K-LB-OBS-04 | **Monotonic per-subscription `seq`.** `seq_monotonic_violations_within_subscription = 0`. Epoch 1 (first subscription) `seq` ran 2→16; epoch 2 (post-resubscribe) 2→3. `seq_reset_on_resubscribe = true` — the new subscription restarts the counter (matches K-WS-OBS-06 / K-WS-02). | OBSERVED (production) | `seq_monotonic_violations_within_subscription`, `seq_epochs_first_last = [[2,16],[2,3]]`, `seq_reset_on_resubscribe`. | #2. |
| K-LB-OBS-05 | **Book mutation from applied deltas.** A value-free digest of each feed's book changed **32** times across the applied deltas — the deltas move the book, they are not no-ops. | OBSERVED (production) | `book_fingerprint_changes = 32`. | #2. |
| K-LB-OBS-06 | **A-028 additive delta semantics hold on the live feed.** For every APPLIED delta the harness compared the feed's book immediately before and after: `qty_after == qty_before + delta_fp`, and the level was **removed when the sum reached 0** (`level_removed_on_zero = 6`). **34 / 34** checked deltas matched, **0** mismatches, **0** `NEGATIVE_QUANTITY` / `CROSSED` / `SEQUENCE_GAP`. Raw quantities never persisted. | OBSERVED (production) — one market, one session (~51 real deltas incl. 6 level removals) | `additive_delta_check` (`checked 34, matches 34, mismatches 0, level_removed_on_zero 6, desyncs 0`). | Moves **A-028** from UNVERIFIED to **OBSERVED** (narrow: one market/session). |
| K-LB-OBS-07 | **Staleness verdict from the runtime on a real feed.** After consumption was paused for 35 s (> the 30 s `max_staleness`), `LiveBookFeed.health()` returned `STALE` with `trading_enabled = false` for both feeds — computed from the real `_last_update` timestamp of the live feed. | OBSERVED (production), staleness **induced by pausing consumption** (not a naturally quiet market) | timeline `C_stale/health_after_pause` (`stale`, false, seq 16). | Supports #7 but does **not** complete it — see verdict. |
| K-LB-OBS-08 | **Disconnect detection.** The underlying socket was dropped abruptly (`socket.shutdown` + `close`, not a graceful WS close). The runtime handed back 17 buffered frames, then `LiveBookConnection.pump_one()` raised `TransportClosed` (`transport_closed_raised = true`). | OBSERVED (production), disconnect **induced by the harness** (not a server/network drop) | timeline `D_disconnect/socket_dropped` → `handle_disconnect` (`buffered_frames_drained_before_detection = 17`). | Supports #8 but does **not** complete it — see verdict. |
| K-LB-OBS-09 | **Unhealthy while disconnected.** `LiveBookConnection.handle_disconnect()` → both feeds `DISCONNECTED`, `trading_enabled = false`. | OBSERVED (production) | timeline `D_disconnect/handle_disconnect` (`disconnected`, false). | #8. |
| K-LB-OBS-10 | **Reconnect + resubscribe.** `LiveBookConnection.reconnect(sleep)` re-ran `connect_and_subscribe()` and succeeded on the **first attempt** (`reconnect_attempts = 0`). *(This required a fix to `WebsocketsTransport` — see K-LB-OBS-12.)* | OBSERVED (production) | timeline `E_recover/reconnected` (`reconnect_attempts: 0`). | #8. |
| K-LB-OBS-11 | **Fresh post-reconnect snapshot; healthy restored ONLY after resync.** Right after `reconnect()` both feeds were still `DISCONNECTED` (`healthy_before_resync = false`). `LiveBookConnection.resync()` then `begin_resync` (→ `RESYNCING`) → a fresh REST `apply_snapshot` → both feeds `HEALTHY`, `trading_enabled = true`. The fresh snapshot differs from the init snapshot (fingerprints changed on both feeds — the book moved during the outage). Full observed path: `UNINITIALIZED → HEALTHY → STALE → DISCONNECTED → (reconnect, still DISCONNECTED) → RESYNCING → HEALTHY`. | OBSERVED (production) | timeline `E_recover/resynced` (`healthy_before_resync: false`, `post_resync` both `healthy`, `books` fingerprints vs `A_init`); `health_statuses_seen`. | #8 recovery behaviour — fully observed; only the disconnect **trigger** was induced. |
| K-LB-OBS-12 | **Bug found + fixed: `WebsocketsTransport` did not release its connection handle when a connection surfaced as `TransportClosed`**, so `LiveBookConnection.reconnect()` → `connect()` raised `WebsocketsTransport.connect called while already connected`. Smallest fix (transport only, D-028): a new `_release()` clears `_conn`/`_cm`; `receive()` calls it on its `ConnectionClosed` and recv-`TimeoutError` paths, `send()` on its `ConnectionClosed` path, and `close()` delegates to it. No `OSError` broadening — a raw-socket-kill test confirms `websockets` `recv()` surfaces the drop as `ConnectionClosed`. Targeted tests: release-then-reconnect (pins the pre-fix failure gone), raw-socket-drop, and a full `LiveBookConnection` drop → reconnect → resync over the loopback server. | TESTED (offline) + exercised in this production run | `src/prediction_market_arbitrage/livebook/ws_transport.py`; `tests/test_livebook_ws_transport.py`; `docs/DECISIONS.md` D-028. | Without this, the runtime's reconnect path was broken against any real socket. |

**Real-money gate reassessment (2026-09-09, live-book runtime):**

- **#2 "Stable live market data" — NOW CHECKED.** The shipped runtime initialised
  from a REST snapshot, subscribed over the authenticated production WebSocket,
  and consumed **30 sequential `orderbook_delta` messages over ~14 s of
  continuous consumption** with **zero** non-`APPLIED` outcomes, **zero**
  desyncs, strictly monotone per-subscription `seq`, both feeds `HEALTHY`
  throughout, and the book demonstrably mutating (32 fingerprint changes,
  6 level removals; K-LB-OBS-01..06); a further 17 buffered deltas applied
  cleanly. This is a real, stable live market-data feed through the actual code
  path — the earlier "REST polling is not the feed" caveat is resolved.
- **#7 "Stale-data handling" — STAYS UNCHECKED.** `LiveBookFeed.health()`
  correctly returned `STALE` / `trading_enabled = false` from the live feed's
  real `_last_update` (K-LB-OBS-07), but the staleness was **induced by pausing
  consumption**, not by a naturally quiet market. What remains: observe a live
  market crossing `max_staleness` on its own, and the `STALE → HEALTHY` recovery
  when data resumes.
- **#8 "Disconnect/reconnect behavior" — STAYS UNCHECKED.** The full
  recovery cycle — detection (`TransportClosed`), `DISCONNECTED` + trading
  disabled, `reconnect()` (first attempt), `RESYNCING`, fresh REST snapshot,
  `HEALTHY` **only after** resync — is OBSERVED against production through the
  runtime (K-LB-OBS-08..11), and a real transport bug was fixed (K-LB-OBS-12).
  But the disconnect **trigger was induced by the harness** (socket dropped
  locally), not a server-side or network drop. What remains: the same cycle from
  an unplanned disconnect, ideally with `BackoffPolicy` retries > 0.
- **A-028** → **OBSERVED** (K-LB-OBS-06): additive `delta_fp` application matched
  the live feed for 34/34 checked deltas with 0 desyncs — narrow (one market,
  one session) but real. Still not `VERIFIED`.

---

### Kalshi — production live-book runtime: stale-data + disconnect/reconnect (2026-09-09, gates #7 / #8)

A follow-up pass targeting the two still-unchecked runtime gates. Same shipped
runtime; **the staleness probe no longer pauses consumption**. Two bounded modes
of `scripts/observe_kalshi_livebook_runtime.py`, run read-only against
production. Evidence:
`docs/evidence/kalshi-live/livebook-runtime/SUMMARY_RECONNECT.json` and
`…/SUMMARY_STALE.json` (the original `SUMMARY.json` from the gate-#2 pass is
retained unchanged). No `/portfolio`, order, balance/position/fill access;
`LIVE_TRADING` never read or set; no Polymarket US; no clock/timestamp
manipulation; no injected frames.

| # | Claim | Status | Evidence | Gate impact |
|---|-------|--------|----------|-------------|
| K-LB-OBS-13 | **Clean HEALTHY → DISCONNECTED transition on an induced drop.** `--observe` picks a liquid market, initialises from REST, subscribes over the authed prod WS, consumes to a stable `HEALTHY` `seq`-ordered stream (8 applied deltas, both feeds `HEALTHY`/seq 5), then confirms `all_healthy() == true` **immediately before** the drop. Unlike the gate-#2 pass (feeds were already `STALE` from the pause), the disconnect now hits genuinely healthy feeds. | OBSERVED (production), session `2026-09-09T…`, `SUMMARY_RECONNECT.json` `config.healthy_pre_drop = true`; timeline `C_confirm/feeds_healthy_pre_drop`. | #8 — the "healthy feed → connection loss" edge is now clean. |
| K-LB-OBS-14 | **One controlled drop → detection → unhealthy, through the runtime.** The underlying socket is abruptly closed (`shutdown(SHUT_RDWR)` + `close`); `LiveBookConnection.pump_one()` raises `TransportClosed` with **0** buffered frames this run; `handle_disconnect()` → both feeds `DISCONNECTED`, `trading_enabled = false`. | OBSERVED (production) | timeline `D_disconnect/socket_dropped` → `handle_disconnect` (`transport_closed_raised = true`, `buffered_frames_drained_before_detection = 0`). | #8 — detection + unhealthy state. |
| K-LB-OBS-15 | **Reconnect + authenticated resubscribe + REST resync; HEALTHY only after resync.** `LiveBookConnection.reconnect(time.sleep)` re-ran `connect_and_subscribe()` (fresh `kalshi_ws_handshake` RSA-PSS + K-WS-AUTH-04 subscribe body) — succeeded on attempt **0**. Immediately after reconnect both feeds still `DISCONNECTED` (`healthy_before_resync = false`); `resync()` → `begin_resync` (`RESYNCING`) → fresh REST `apply_snapshot` → both feeds `HEALTHY`. Then **4** further real `orderbook_delta` applied, new per-subscription `seq` epoch (2→3), `seq_reset_on_resubscribe = true`, `delta_outcomes = {applied: 12}`, 0 desyncs, 0 within-subscription `seq` violations. Full path `UNINITIALIZED → HEALTHY → DISCONNECTED → (reconnect, still DISCONNECTED) → HEALTHY(after resync)`. | OBSERVED (production) | `SUMMARY_RECONNECT.json` timeline `E_recover/reconnected` (`reconnect_attempts: 0`), `E_recover/resynced` (`healthy_before_resync: false`, `post_resync` both `healthy`), `F_resumed/pumped_4_deltas`; `seq_epochs_first_last = [[2,5],[2,3]]`. | #8 recovery path — OBSERVED end-to-end through the runtime. **Residual:** (a) the drop is **harness-induced**, not a spontaneous server/network drop; (b) `BackoffPolicy` delay/give-up was **not exercised** (`reconnect_attempts = 0`) — it stays TESTED-only (D-028 loopback + unit); (c) `RESYNCING` is transient and was not sampled as its own timeline row (TESTED in `test_healthy_restored_only_after_post_reconnect_resync`). |
| K-LB-OBS-16 | **Natural stale lifecycle NOT captured — bounded window, documented blocker.** `--observe-stale` consumes continuously (never pausing) and samples `LiveBookFeed.health()` + the fail-closed accessor `current_order_book(now, require_healthy=True)` between every `pump_one()`. Run 200 s cap: `pick_moderate_market` fell back to a liquid market (see K-LB-OBS-17), **400** deltas applied over ~90 s, `empty_pumps = 0`, `max_pump_gap_s = 6.685`, no feed aged past the 30 s `max_staleness` → **no stale interval existed to observe**; early-stopped as "market too active". `feeds_that_went_stale = []`, `lifecycle_observed = false`. | OBSERVED (production) — blocker | `SUMMARY_STALE.json` `result = "BLOCKED …"`, `stale_watch` (`empty_pumps: 0`, `delta_pumps: 199`, `max_pump_gap_s: 6.685`, `max_observed_stale_age_s: 0.0`). | #7 **stays unchecked.** |
| K-LB-OBS-17 | **Two independent reasons a natural stale lifecycle could not be observed in a bounded window.** (a) *Market availability:* Kalshi's public `GET /markets?status=open` (no series filter, 3 pages) returned **300** tickers, **all** empty-book `KXMVECROSSCATEGORY-SHARD1-*` markets (`two_sided = false`, depth 0); the only reliably two-sided markets found are the crypto hourly series, which update many times per second and never approach a 30 s gap. (b) *Architectural:* a continuously-consuming `LiveBookConnection.pump_one()` caller **blocks inside `WebsocketsTransport.receive()`** between qualifying `orderbook_delta` frames — on a quiet market there is no intervening traffic to return control, so the caller cannot sample `health()` during the stale interval; it regains control only when the next real delta arrives, which immediately restores `HEALTHY`. `WebsocketsTransport.recv_timeout` converts a quiet-but-alive socket into `TransportClosed` + full reconnect (quiet socket ≡ dead socket). See `docs/DECISIONS.md` D-029. | OBSERVED (probe) + design analysis | throwaway probe (not committed); `SUMMARY_STALE.json`; `src/prediction_market_arbitrage/livebook/ws_transport.py` `receive()`. | #7 blocker — resolving it needs either a curated quiet-market ticker whose inter-delta gap is 30–150 s, or a non-fatal idle/poll path on the transport, or a concurrent health sampler. All are out of scope for an observation milestone. |

**Real-money gate reassessment (2026-09-09, stale + reconnect pass):**

- **#7 "Stale-data handling" — STAYS UNCHECKED.** `LiveBookFeed.health()` returns
  `STALE` / `trading_enabled = false` correctly (deterministic tests; and
  K-LB-OBS-07 on the live feed), and the fail-closed accessor rejects a stale
  book — but a **natural** `HEALTHY → STALE → HEALTHY` lifecycle on a live feed,
  with recovery driven by a genuine new delta, was **not** captured. Blocker:
  K-LB-OBS-16 / K-LB-OBS-17 (no suitable market + `pump_one()` blocks between
  deltas). Not manufacturable within this milestone's constraints (no pause, no
  clock edit, no injected frames, no threshold weakening).
- **#8 "Disconnect/reconnect behavior" — STAYS UNCHECKED (materially strengthened).**
  The full recovery path is now OBSERVED against production through the runtime
  **from genuinely healthy feeds**, with a clean `HEALTHY → DISCONNECTED →
  reconnect → HEALTHY-after-resync` transition and post-resync deltas
  (K-LB-OBS-13..15) — an improvement on the gate-#2 pass, where feeds were
  already `STALE` at the drop. Remaining before a reviewer can check #8:
  (a) a spontaneous (server/network) disconnect rather than a harness-induced
  socket close; (b) `BackoffPolicy` retry/backoff exercised live
  (`reconnect_attempts` was 0). Both are explicitly listed in K-LB-OBS-15's
  residual.

---

## Polymarket US — WebSocket order book (M2.1)

Verification date: **2026-09-06** (docs read; **no live socket connection** —
the endpoint requires API-key auth in the handshake).

### Official sources consulted

| # | Source | URL |
|---|---|---|
| P-WS-S1 | Markets WebSocket | https://docs.polymarket.us/api-reference/websocket/markets |
| P-WS-S2 | Streaming semantics & best practices | https://docs.polymarket.us/trader-guide/streaming-apis |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| P-WS-01 | Markets WebSocket endpoint is `wss://api.polymarket.us/v1/ws/markets`; API-key auth is required in the handshake. | VERIFIED (docs) | P-WS-S1 "Endpoint" + "Authentication Required". | Not connected in M2.1; recorded for the transport boundary. |
| P-WS-02 | A `SUBSCRIPTION_TYPE_MARKET_DATA` message carries a **complete** `marketData` object each time: `{ marketSlug, bids[], offers[], state, stats, transactTime }` — the **same** schema as the REST `/v1/markets/{slug}/book` payload (P-06/P-07): levels are `{ px:{ value:<decimal string>, currency:"USD" }, qty:<decimal string> }`, "sorted best-to-worst". There is **no sequence number** and **no delta message** on this channel. | VERIFIED (docs) | P-WS-S1 "Market Data Response" example + "Order Book Depth"; P-06/P-07. | `livebook/polymarket_us_ws.py` (each frame → a full `BookSnapshot`). |
| P-WS-03 | `marketData.state` is one of `MARKET_STATE_{OPEN,PREOPEN,SUSPENDED,HALTED,EXPIRED,TERMINATED,MATCH_AND_CLOSE_AUCTION}`. | VERIFIED (docs) | P-WS-S1 "Market States". | `LiveBookFeed` treats only `MARKET_STATE_OPEN` as tradeable (fail-closed). |
| P-WS-04 | Streams "always start with a snapshot"; delivery is **at-least-once** (dedupe on message id); a single stream is ordered. | VERIFIED (docs) | P-WS-S2 "Snapshots and Deltas", "Delivery Guarantees", "Message Ordering". | `LiveBookFeed` drops a full snapshot whose `transactTime` is older than the last accepted one (reordered / repeated delivery). |

### Not verified / assumptions (M2.1)

- No live frames captured (auth-gated handshake); no sanitized WS fixture.
- The trader-guide "Streaming" page describes a **separate** gRPC/HTTP streaming
  system ("not WebSockets"); only the dedicated **Markets WebSocket** page
  (P-WS-S1) is decoded here. Which real-time system a production deployment uses
  is a later (transport) decision.
- `stats` (last trade, volume, OI, high/low) is **ignored** — not book state.
- Attribution of the single book to the `:LONG` contract carries A-013's
  UNVERIFIED caveat forward from M1.3.

**Live-execution gate:** M2.1 decodes documented WebSocket schemas and maintains
book state deterministically; it opens **no socket** and holds **no
credentials**. A-028 (Kalshi delta application) and A-029 (Kalshi market-state
source) are unresolved. Real-money trading stays disabled (D-002; ROADMAP
"Real-money gate").

---

## WebSocket authenticated-handshake / transport boundary (M2.1)

Verification date: **2026-09-06** (docs read). **No live socket, no credentials,
no networked transport implemented** — see the blocker below.

### Official sources consulted

| # | Source | URL |
|---|---|---|
| WS-A-S1 | Kalshi — Quick Start: WebSockets | https://docs.kalshi.com/getting_started/quick_start_websockets |
| WS-A-S2 | Kalshi — Quick Start: Authenticated Requests (request signing) | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests |
| WS-A-S3 | Kalshi — WebSocket Connection (AsyncAPI: `subscribe` command) | https://docs.kalshi.com/websockets/websocket-connection |
| WS-A-S4 | Polymarket US — WebSocket API Overview | https://docs.polymarket.us/api-reference/websocket/overview |
| WS-A-S5 | Polymarket US — Authentication | https://docs.polymarket.us/api-reference/authentication |
| WS-A-S6 | Polymarket US — Markets WebSocket (subscribe body) | https://docs.polymarket.us/api-reference/websocket/markets |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| K-WS-AUTH-01 | Kalshi WS URL is `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (prod) / `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (demo). | VERIFIED (docs) | WS-A-S1 "Connection URL". | `ws_auth.KALSHI_WS_URL_PROD/DEMO`. |
| K-WS-AUTH-02 | Handshake carries 3 headers: `KALSHI-ACCESS-KEY` (API key id), `KALSHI-ACCESS-TIMESTAMP` (Unix **ms** string), `KALSHI-ACCESS-SIGNATURE` (base64). | VERIFIED (docs) | WS-A-S1 "Required Headers"; WS-A-S2 table. | `ws_auth.kalshi_ws_handshake`. |
| K-WS-AUTH-03 | Signed message = `timestamp + "GET" + "/trade-api/ws/v2"`; signature = RSA-PSS (MGF1-SHA256, salt = digest length) over SHA-256, base64-encoded. | VERIFIED (docs) | WS-A-S1 "Signing the WebSocket Request"; WS-A-S2 `sign_request` code. | `ws_auth.kalshi_ws_sign_message`; the RSA-PSS step is an injected `Signer`. |
| K-WS-AUTH-04 | Subscribe command: `{"id": <int>, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_tickers": [...]}}` (`market_ticker` for one; mutually exclusive). | VERIFIED (docs) | WS-A-S3 AsyncAPI `subscribeCommand`. | `ws_auth.kalshi_subscribe_command`. |
| P-WS-AUTH-01 | Polymarket US Markets-WS URL is `wss://api.polymarket.us/v1/ws/markets`. | VERIFIED (docs) | WS-A-S4 "Connection". | `ws_auth.POLYMARKET_US_WS_MARKETS_URL`. |
| P-WS-AUTH-02 | Handshake carries 3 headers: `X-PM-Access-Key` (key id), `X-PM-Timestamp` (Unix **ms** string, within 30s of server time), `X-PM-Signature` (base64). Signed message = `timestamp + "GET" + "/v1/ws/markets"`; signature = Ed25519 over the message, base64-encoded. | VERIFIED (docs) | WS-A-S4 "Authentication"; WS-A-S5 raw-request signing (`message = f"{timestamp}{method}{path}"`, Ed25519). | `ws_auth.polymarket_us_ws_handshake` / `polymarket_us_ws_sign_message`; Ed25519 is an injected `Signer`. |
| P-WS-AUTH-03 | Markets-WS subscribe body: `{"subscribe": {"requestId": <str>, "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA", "marketSlugs": [...]}}`, ≤100 slugs. **Discrepancy:** WS-A-S4 (overview) shows snake_case keys (`request_id`, `subscription_type`) and an **int** enum (`1`), while WS-A-S6 (channel-specific) uses camelCase + the string enum. The code follows WS-A-S6. | VERIFIED (docs) with an unresolved casing/enum discrepancy between two doc pages | WS-A-S6 example; WS-A-S4 "Request Format". | `ws_auth.polymarket_us_subscribe_command`. |

### Transport implementation status (M2.1)

- **Networked transport: implemented.** `livebook.ws_transport.WebsocketsTransport`
  is a concrete `WebSocketTransport` over the `websockets` library (the client
  the Kalshi / Polymarket US docs use; now the project's sole runtime
  dependency, `websockets>=13`). `connect(handshake)` opens
  `websockets.sync.client.connect(url, additional_headers=headers)`; `send` /
  `receive` / `close` map to `recv` / `send` / context-manager exit;
  `ConnectionClosed` and recv-timeout both surface as `TransportClosed`, **and
  clear the connection handle** (`_release()`, added 2026-09-09 — K-LB-OBS-12 /
  D-028) so `LiveBookConnection.reconnect()` → `connect()` does not raise
  "already connected". Server Ping/Pong keepalive is handled by the library. It
  plugs into the unchanged `LiveBookConnection`.
- **RSA-PSS / Ed25519 signing is still injected** (`Signer`) — the framework
  imports no `cryptography`. A caller supplies the signer for a real connection.
  A reusable Kalshi signer now exists outside the package:
  `scripts/kalshi_signer.OpensslRsaPssSigner` (K-WS-AUTH-07). It was used for a
  real production Kalshi WS session on 2026-09-09 (K-WS-OBS-01..08).
- **Kalshi: live OBSERVED handshake + frames (2026-09-09).** A one-off
  `scripts/observe_kalshi_prod_ws_market_data.py --observe` run connected to
  `wss://external-api-ws.kalshi.com/trade-api/ws/v2`, was accepted by the real
  server, and received `subscribed` + `orderbook_snapshot` + one
  `orderbook_delta` whose decoded shapes match K-WS-03 / K-WS-04; per-subscription
  `seq` ran 1→2; a clean disconnect → reconnect → resubscribe delivered a fresh
  snapshot (K-WS-OBS-01..07). This ran the shipped `WebsocketsTransport` +
  `livebook.kalshi_ws` decoders directly — **not** `LiveBookConnection` /
  `LiveBookFeed`, so no `HealthStatus` transition was exercised (K-WS-OBS-08).
  **Kalshi half of A-030 resolved; Polymarket US half still not verified.**
- **Kalshi: full-runtime OBSERVED session (2026-09-09, K-LB-OBS-01..12).** A
  later run wired one production market through
  `LiveBookConnection` + `LiveBookFeed` + `WebsocketsTransport` + a REST
  `SnapshotSource`: REST-snapshot init → WS subscribe → 30 sequential deltas in
  ~10 s (0 desyncs, monotone `seq`, `HEALTHY` throughout, 34/34 additive-delta
  checks → **A-028 OBSERVED**) → induced staleness (`STALE`) → induced socket
  drop (`DISCONNECTED`, `TransportClosed` detected) → `reconnect()` →
  `RESYNCING` → fresh REST snapshot → `HEALTHY`. **Gate #2 CHECKED**; #7/#8
  unchecked (staleness and disconnect were harness-induced). Fixed a real
  reconnect bug in `WebsocketsTransport` (K-LB-OBS-12).
- **Polymarket US: still no live OBSERVED handshake or frame.** The transport is
  tested against a **local `websockets` server on loopback** (a real socket
  round-trip, but the local server accepts any headers). No authenticated
  connection to Polymarket US was made; no P-WS fixture was captured; its
  signing message strings / header names are unit-tested only against the docs.
  Whether the real Polymarket US server accepts the handshake is **not
  verified** — the open remainder of **A-030**.
- Kalshi `orderbook_delta` is described as a **private channel** (WS-A-S1) — it
  rides the authenticated session even though its payload is public market data.
- Polymarket US `X-PM-Signature` construction uses `path` with no documented
  query-strip rule (there are no query params on the WS path, so this does not
  bite here).

---

## Kalshi — REST trading API (research only; pre-M4, no code)

Verification date: **2026-09-08** (official docs read at `docs.kalshi.com`).
**No authenticated request was made**, no account, no API key, no signature
generated, no fixture captured. Every row below is **doc-only**: `VERIFIED
(docs)` means an official page states it; nothing here is `OBSERVED` or
`TESTED`. This section resolves **no** Real-money gate item — see the gate note
at the end. It exists to satisfy the *research* half of ROADMAP "Real-money
gate → Official API behavior"; the *observation* half remains open.

Purpose: primary-evidence survey for the first real-money blocker (official
trading API behavior) covering authentication/signing, submit order, cancel
order, order status, positions, idempotency / client order IDs, errors / rate
limits, and partial-fill reporting. **No adapter was implemented.**

### Official sources consulted

| # | Source | URL |
|---|---|---|
| K-TR-S1 | Quick Start: Authenticated Requests (request signing) | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests |
| K-TR-S2 | Create Order (V2) — API reference | https://docs.kalshi.com/api-reference/orders/create-order-v2 |
| K-TR-S3 | Quick Start: Create your first order | https://docs.kalshi.com/getting_started/quick_start_create_order |
| K-TR-S4 | Cancel Order (V2) — API reference | https://docs.kalshi.com/api-reference/orders/cancel-order-v2 |
| K-TR-S5 | Get Order — API reference | https://docs.kalshi.com/api-reference/orders/get-order |
| K-TR-S6 | Get Fills — API reference | https://docs.kalshi.com/api-reference/portfolio/get-fills |
| K-TR-S7 | Get Positions — API reference | https://docs.kalshi.com/api-reference/portfolio/get-positions |
| K-TR-S8 | Rate Limits and Tiers | https://docs.kalshi.com/getting_started/rate_limits |
| K-TR-S9 | API Changelog (legacy `/portfolio/orders` deprecation ≥ 2026-05-06; exchange-sharding rollout entries) | https://docs.kalshi.com/changelog |
| K-TR-S10 | Exchange Sharding (getting started) | https://docs.kalshi.com/getting_started/exchange_sharding |
| K-TR-S11 | Intra Account Transfer — API reference (`/portfolio/intra_exchange_instance_transfer`) | https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer |
| K-TR-S12 | Get Exchange Status — API reference (`/exchange/status`, `exchange_index_statuses`) | https://docs.kalshi.com/api-reference/exchange/get-exchange-status |
| K-TR-S13 | API Keys (self-service key creation, demo == prod process) | https://docs.kalshi.com/getting_started/api_keys |
| K-TR-S14 | Creating and using a demo account (Kalshi Help Center) | https://help.kalshi.com/account/demo-account |
| K-TR-S15 | Get Balance — API reference (`exchange_index` query param scopes balance/portfolio to one shard) | https://docs.kalshi.com/api-reference/portfolio/get-balance |
| K-TR-S16 | Set Target Balance Allocation — API reference (`POST /portfolio/target_balance_allocation`) | https://docs.kalshi.com/api-reference/portfolio/set-target-balance-allocation |
| K-TR-S17 | Get Intra Account Transfers — API reference (`GET /portfolio/intra_exchange_instance_transfers`, `GetIntraExchangeInstanceTransfersResponse`) | https://docs.kalshi.com/api-reference/portfolio/get-intra-account-transfers |
| K-TR-S18 | Generate API Key — API reference (`scopes`, subaccount restriction) | https://docs.kalshi.com/api-reference/api-keys/generate-api-key |
| K-TR-S19 | Get API Keys — API reference (`scopes`, region-attestation expiry) | https://docs.kalshi.com/api-reference/api-keys/get-api-keys |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| K-TR-01 | Authenticated REST base is the same host as market data: `https://external-api.kalshi.com/trade-api/v2` (prod) / `https://external-api.demo.kalshi.co/trade-api/v2` (demo). | VERIFIED (docs) | K-TR-S1 "Base URLs". | None — evidence only. |
| K-TR-02 | Auth uses three headers: `KALSHI-ACCESS-KEY` (API key id), `KALSHI-ACCESS-TIMESTAMP` (current time in **milliseconds**, integer string), `KALSHI-ACCESS-SIGNATURE` (base64). | VERIFIED (docs) | K-TR-S1 "Required Headers". Matches WS-A-S2 / K-WS-AUTH-02. | None. |
| K-TR-03 | Signed string = `timestamp + HTTP_METHOD + path`, path **excluding** query params (example `1703123456789GET/trade-api/v2/portfolio/balance`). Signature = RSA-PSS, MGF1-SHA256, `salt_length = PSS.DIGEST_LENGTH`, over SHA-256 of the message; result base64-encoded. | VERIFIED (docs) | K-TR-S1 "String to Sign" + "Signature Algorithm". Matches K-WS-AUTH-03. | None. |
| K-TR-04 | Submit order: **`POST /portfolio/events/orders`** (Create Order V2). The legacy `POST /portfolio/orders` is deprecated no earlier than 2026-05-06 (K-TR-S9). | VERIFIED (docs) | K-TR-S2 method+path; K-TR-S9. | None. |
| K-TR-05 | Create-order request body (V2): `ticker` (string, req), `side` (string, req — `bid`\|`ask`), `count` (fixed-point string, req, 0–2 dp, min 0.01), `price` (fixed-point **dollars** string, req, 2–4 dp), `time_in_force` (string, req — `fill_or_kill`\|`good_till_canceled`\|`immediate_or_cancel`), `self_trade_prevention_type` (string, req — `taker_at_cross`\|`maker`), `client_order_id` (string, opt), `expiration_time` (integer Unix seconds, opt), `post_only` (bool, opt), `cancel_order_on_pause` (bool, opt), `reduce_only` (bool, opt), `subaccount` (int ≥ 0, opt), `order_group_id` (string, opt), `exchange_index` (int, opt). | VERIFIED (docs) | K-TR-S2 request schema. Field set not cross-checked against `openapi.yaml` in this pass — see gaps. | None. |
| K-TR-06 | Create-order 201 response: `order_id` (string, always), `client_order_id` (string, if supplied), `fill_count` (string, always), `remaining_count` (string, always), `average_fill_price` (string, only when `fill_count` > 0), `average_fee_paid` (string, only when `fill_count` > 0), `ts_ms` (integer). No order-lifecycle `status` field on the create response. | VERIFIED (docs) | K-TR-S2 response schema; K-TR-S3 (create response shows `order_id` / `client_order_id` / `remaining_count`). | None. |
| K-TR-07 | Idempotency: `client_order_id` is a **server-enforced** dedupe key. Resubmitting the same `client_order_id` returns **`409 Conflict`** ("Order with this `client_order_id` already exists"); the field is optional but "strongly recommended". | VERIFIED (docs) | K-TR-S3 ("The API will reject duplicate submissions with the same `client_order_id`"; 409 listed). Not OBSERVED against a live account. | Informs `live_broker.IdempotencyGuard` design intent (local half only); no venue call. |
| K-TR-08 | Order status / partial fills: `GET /portfolio/orders/{order_id}` returns an order object with `status` ∈ {`resting`, `canceled`, `executed`} plus fixed-point `initial_count_fp`, `fill_count_fp`, `remaining_count_fp`, and cost/fee fields (`taker_fees_dollars`, `maker_fees_dollars`, `taker_fill_cost_dollars`, `maker_fill_cost_dollars`). A **partial fill** is represented as `status = resting` with `fill_count_fp` > 0 and `remaining_count_fp` > 0 — there is **no distinct `partially_filled` status**. No `average_fill_price` on this schema. | VERIFIED (docs) | K-TR-S5 response schema. | None. |
| K-TR-09 | Per-fill reporting: `GET /portfolio/fills` returns a `fills` array; each fill has `fill_id` (a.k.a. legacy `trade_id`), `order_id`, `ticker`/`market_ticker`, `outcome_side` (`yes`\|`no`), `book_side` (`bid`\|`ask`), `count_fp`, `yes_price_dollars`, `no_price_dollars`, `is_taker` (bool), `fee_cost`, `created_time`. One row per matched execution — the granular partial-fill record. | VERIFIED (docs) | K-TR-S6 response schema. | None. |
| K-TR-10 | Cancel order: **`DELETE /portfolio/events/orders/{order_id}`**. Cancellation is by **`order_id`** (path param); `client_order_id` is echoed in the response but cannot be used to cancel. Query params: `subaccount` (default 0), `exchange_index` (omit / `-1` = auto-route), `market_ticker` (**required when auto-routing**). Response: `order_id`, `client_order_id`, `reduced_by` (fixed-point string — contracts canceled), `ts_ms` (int). | VERIFIED (docs) + OBSERVED (K-TR-OBS-30 — an unrouted DELETE 404s for a sharded order; `?market_ticker=…` → 200). | K-TR-S4 method+path+response+query params. | Live-broker Kalshi cancel must pass `market_ticker` or `exchange_index`. |
| K-TR-11 | Positions: `GET /portfolio/positions`. Query: `cursor`, `limit` (1–1000, default 100), `count_filter`, `ticker`, `event_ticker`, `subaccount` (default 0), `exchange_index`. Response has `market_positions[]` (`ticker`, `exchange_index`, `total_traded_dollars`, `position_fp`, `market_exposure_dollars`, `realized_pnl_dollars`, `fees_paid_dollars`, `last_updated_ts`) and `event_positions[]` (`event_ticker`, `total_cost_dollars`, `total_cost_shares_fp`, `event_exposure_dollars`, `realized_pnl_dollars`, `fees_paid_dollars`). | VERIFIED (docs) | K-TR-S7 schema. `resting_orders_count` not present in the documented schema. | None. |
| K-TR-12 | Rate limits: token-bucket per API key; bucket refills continuously at the tier's per-second budget up to capacity; request allowed when the bucket covers its cost, else **`429 Too Many Requests`** with body `{"error": "too many requests"}`. 429 responses **do not** currently include `Retry-After` or `X-RateLimit-*` headers; no extra cooldown penalty. Default request cost 10 tokens; create order 10, cancel order 2; authoritative per-endpoint costs at `GET /account/endpoint_costs`. Basic tier: read budget 200, write budget 100 tokens/s; Basic write bucket holds ~1 s of budget. Higher tiers (Advanced … Prestige) via `GET /account/limits`. | VERIFIED (docs) | K-TR-S8. | None. |
| K-TR-13 | Documented HTTP error statuses on create order: 400, 401, 409, 429, 500 (no Kalshi-specific error-code enum listed on the V2 page beyond these). Cancel order lists 401, 404, 500. | VERIFIED (docs) | K-TR-S2, K-TR-S4. | None. |
| K-TR-14 | **Exchange sharding.** Kalshi is "distributing trading across multiple matching engines by category", phased through September 2026 (changelog: combos → shard 1; crypto/commodities → shard 2; select sports → shard 3; shard 0 is the catch-all default). `exchange_index` on create-order is **optional**: "If omitted, auto-routes when ticker is provided; otherwise defaults to 0." So a `…-SHARD1-…` market ticker auto-routes to `exchange_index = 1`. | VERIFIED (docs) | K-TR-S10; K-TR-S2 (`exchange_index` field note); K-TR-S9 (dated rollout entries, 2026-06-18 … 2026-09-10). | Explains why the M-lifecycle probe (`…SHARD1…` ticker, no `exchange_index`) routed to shard 1. |
| K-TR-15 | **Preallocating collateral is a prerequisite for sharded order entry.** "Programmatic traders must preallocate collateral on a given exchange shard before order placement." Funds are moved between shards by `POST /portfolio/intra_exchange_instance_transfer` (`source`/`destination` = `event_contract`\|`margined`, `amount` in centicents, `source_exchange_shard`/`destination_exchange_shard` 0–100 default 0). A target split can also be set via `POST`/`GET /portfolio/target_balance_allocation` "through the REST API and the clearing portal". Per-shard status: `GET /exchange/status` → `exchange_active`, `trading_active`, `intra_exchange_transfers_active`, `exchange_index_statuses[]`. Per-shard balance: `GET /portfolio/balance?exchange_index=N`. | VERIFIED (docs) | K-TR-S10; K-TR-S11; K-TR-S12; K-TR-S9 (2026-08-20 entries: cross-shard transfer, target-allocation endpoints, per-index exchange status). | None — informs A-038 remediation path only. |
| K-TR-16 | **SUPERSEDED 2026-09-10 by K-TR-22.** The 2026-09-08 review recorded API keys as self-service and unscoped. Current primary documentation now exposes explicit read/write scopes, so the former conclusion cannot rule out key permission as an order-rejection cause. | SUPERSEDED (documentation drift) | Historical K-TR-S13; current K-TR-S18/S19. | Do not use this historical row for current authorization claims. |
| K-TR-17 | **Demo accounts are not pre-funded.** "Your demo account won't have funds preloaded, so follow the tutorial to add mock funds using a test payment method" (test debit cards / Plaid sandbox / testnet crypto). Adding demo funds is self-service; no account-type gate or verification for demo trading is documented. | VERIFIED (docs) | K-TR-S14. | The provisioned demo key's account shows `portfolio_value = 0` / all breakdown balances `0.0000` (K-TR-OBS-10) — i.e. never funded. |
| K-TR-18 | **Documented self-service demo-funding flow.** Sign up / sign in at `demo.kalshi.co/sign-up` with mock details, open the deposit section, pick a test payment method: **debit card** (Visa `4000 0566 5566 5556`, Mastercard `5200 8282 8282 8210`; any future expiry, any 3-digit CVV) — recommended; **ACH via Plaid sandbox** (`user_good` / `pass_good`, phone `415-555-0010`, OTP `123456`); **Google Pay** test cards (processed as a debit card); **crypto** via a testnet faucet ("Do NOT send real cryptocurrency to demo wallet addresses"). No deposit-amount limit, and **no exchange-shard / collateral-allocation step**, is documented in the demo-funding flow itself — shard allocation is a separate programmatic step (K-TR-14/15, K-TR-19). | VERIFIED (docs) | K-TR-S14. | Remediation path for A-038: fund the demo account before any order-entry probe. |
| K-TR-19 | **Per-shard balance is read via a query param, not a separate endpoint.** `GET /portfolio/balance` takes optional `exchange_index` (integer, optional; "used to scope the balance and portfolio value. If omitted, both include all exchange indexes.") and optional `subaccount` (0–63, default 0). Response `GetBalanceResponse`: `balance` (int64 cents), `balance_dollars` (string), `portfolio_value` (int64 cents), `updated_ts` (int64), `balance_breakdown[]` (`exchange_index` int, `balance` fixed-point-dollar string; omitted for subaccount-restricted keys). | VERIFIED (docs) | K-TR-S15. Confirmed live on demo — K-TR-OBS-14. | Supersedes the shorthand `GET /portfolio/balance?exchange_index=N` note in K-TR-15 with the exact param semantics. |
| K-TR-20 | **Moving / allocating collateral to a shard (documented endpoints).** (a) One-off move: `POST /portfolio/intra_exchange_instance_transfer` — required `source`/`destination` ∈ {`event_contract`, `margined`}, `amount` (int64 **centicents**); optional `source_exchange_shard` / `destination_exchange_shard` (0–100, default 0), `source_subaccount` / `destination_subaccount` (default 0, event-contract↔event-contract only); 200 → `{ transfer_id }`. Cross-index transfers "run in up to three non-atomic steps" (partial-failure is not rolled back). (b) Standing split: `POST /portfolio/target_balance_allocation` — `allocations[]` (≤101 items, each `exchange_index` ≥0 + `percent` 0–100; percentages must total 100; empty array disables auto-rebalancing), optional `resting_margin_reservation` ∈ {`max`, `sum`} (default `sum`); 200 → `{}`. Auto-rebalancing then issues intra-exchange transfers ~every 10 s when balances drift. Subaccount routing: `Create Subaccount` and `Transfer Between Subaccounts` each take an `exchange_index`. | VERIFIED (docs) | K-TR-S10; K-TR-S11; K-TR-S16. | A-038 remediation path (documented), still unexecuted — no transfer or allocation call was made. |
| K-TR-21 | **Read-only endpoints for exchange-instance transfer state (API changelog 2026-08-27).** (a) `GET /portfolio/intra_exchange_instance_transfers` — transfer history; query `limit` (default 100, max 500), `cursor`; auth required. `GetIntraExchangeInstanceTransfersResponse` = `{ transfers[], cursor? }`; each `IntraExchangeInstanceTransfer` = `transfer_id` (string), `source` / `destination` ∈ {`event_contract`, `margined`}, `source_exchange_shard` (int), `destination_exchange_shard` (int), `amount` (fixed-point-dollar string), `status` ∈ {`pending`, `complete`}, `created_ts` (int ms). (b) `GET /portfolio/target_balance_allocation` — reads the current standing split; changelog lists it alongside the `POST`. **This supersedes K-TR-20's "no `GET` for the current target allocation is documented"** — the changelog documents the `GET`, and it was OBSERVED live on demo (K-TR-OBS-19). The changelog also mentions `GET /portfolio/intra_exchange_instance_transfers/{transfer_id}`, but the API-reference OpenAPI spec does **not** define a single-transfer `GET` (**doc inconsistency, UNKNOWN**). No documented error/status code maps to HTTP 503 / "Service unavailable" for the transfer `POST` (K-TR-20 error schema is generic `{code, message, details?}`), and no shard-activation / minimum-amount / destination-initialization precondition is stated. | VERIFIED (docs) | K-TR-S9 (2026-08-27 entry); K-TR-S17. | Read-only diagnosis path for A-038's transfer failure. |
| K-TR-22 | **API keys now have explicit scopes.** The generate-key schema accepts parent `read` / `write` scopes and child scopes including `write::trade`; omitted scopes default to full `read` + `write`. The get-keys response reports each key's current `scopes`. Therefore a successful authenticated GET proves a usable key/signature for that read, but not order-entry authorization. | VERIFIED (docs), not observed for the configured Demo key | K-TR-S18/S19. | A future rejection summary can distinguish HTTP/auth categories; this investigation made no authenticated scope read. |
| K-TR-23 | **Trading selected categories is location-attestation-sensitive.** `GET /api_keys` reports `api_key_region_expiration_ts`; after that timestamp API keys are not valid for trading Sports, Elections, and Entertainment markets. | VERIFIED (docs), configured Demo-key state UNKNOWN | K-TR-S9 (2026-08-16 changelog); K-TR-S19. | A successful generic portfolio GET does not establish that a sports create is currently authorized. |

### Not verified / gaps (pre-M4)

- **No live authenticated call, no capture, no fixture.** Nothing here is
  `OBSERVED` or `TESTED`. Signing-string bytes, header names, request/response
  field names, and the 409-on-duplicate behavior are doc-only.
- Create-order body/response **not cross-checked against `docs.kalshi.com/openapi.yaml`**
  in this pass; the V2 reference page was the sole source for K-TR-05 / K-TR-06.
- Path inconsistency in Kalshi's own docs: create/cancel V2 use
  `/portfolio/events/orders[...]`, while get-order/fills/positions use
  `/portfolio/orders/{id}`, `/portfolio/fills`, `/portfolio/positions`. Whether
  the V2 order object is also readable at `/portfolio/events/orders/{id}` is
  **UNKNOWN**.
- Exact semantics of `self_trade_prevention_type` (`taker_at_cross` vs `maker`),
  `reduce_only`, `order_group_id`, and subaccount routing — **UNKNOWN**, not read.
- Whether a `429` can occur mid-batch and how a partially-accepted batch is
  reported — **UNKNOWN** (batch endpoints not surveyed here).
- `average_fill_price` appears on the **create** response but not on the
  **get-order** schema; the field to use for realized average price on a resting
  partially-filled order is therefore **UNKNOWN** (likely derive from
  `/portfolio/fills`).
- No mapping to the project's domain models was designed (out of scope: "Do not
  implement adapters").
- **`404` / `user_not_found` / "Exchange user not found" on `POST
  /portfolio/events/orders` is UNDOCUMENTED** (K-TR-OBS-12). `404` is not in the
  create-order-v2 error list (K-TR-13); no official page defines the string
  `user_not_found` or "Exchange user not found". The nearest documented analog is
  FIX `OrdRejReason 15` "Unknown account" = "Subaccount or sub-trader does not
  exist" (K-TR-S9 family / FIX error-handling). The evidence-consistent reading —
  the demo account is unfunded (K-TR-17), so no collateral is allocated on shard
  1 (K-TR-14/15) and no per-shard "exchange user" exists there when the order
  auto-routes — is **inference, not verified**; Kalshi does not document that a
  missing shard allocation yields `404 user_not_found`. See A-038.

---

## Kalshi — demo authenticated read-only observation (2026-09-08)

Observation date: **2026-09-08** (UTC per server `date` header, e.g.
`Tue, 08 Sep 2026 06:37:02 GMT`). Environment: **Kalshi demo only**
(`https://external-api.demo.kalshi.co/trade-api/v2`). Every request was an
**authenticated GET** — no order was submitted, cancelled, or modified;
`LIVE_TRADING` unchanged; no Polymarket US call. Credentials were read at
runtime (demo API key id from macOS Keychain `pma-kalshi-demo-api-key-id`,
RSA private key from `~/.config/pma/kalshi-demo-private-key.pem`) and never
printed, logged, persisted, fixtured, or committed. The signature was produced
by shelling out to `openssl dgst -sha256 -sign … -sigopt rsa_padding_mode:pss
-sigopt rsa_pss_saltlen:digest` (no `cryptography` dependency added).

Tool: `scripts/observe_kalshi_demo.py` (not part of the shipped package).
Sanitised captures: `docs/evidence/kalshi-demo/*.json`. Sanitisation is
**structure-first / fail-safe**: object/array structure, every field name, the
request path, HTTP status and whitelisted headers are kept; **every** response-
body scalar is replaced with a type token (`<number>` / `<redacted>`) unless it
is on a short allowlist of fixed non-account API constants (empty cursor and
fixed `error.code` / `error.message` strings — `authentication_error`,
`invalid_UUID`, `deprecated_v1_order_endpoint`, `user_not_found`, …; never
`error.details`). Unknown / future fields are therefore redacted by default. The response-shape types recorded in
the K-TR-OBS rows below were observed at capture time; the committed fixtures no
longer carry per-scalar type detail. The demo account is **empty**, so array
element shapes (`market_positions[]`, `fills[]`, `orders[]` rows) were **not**
observed — only the response envelopes.

### Official sources consulted

Reuses K-TR-S1 (auth/signing), K-TR-S6 (fills), K-TR-S7 (positions). No new
source pages.

### Claims

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-01 | The demo REST base `https://external-api.demo.kalshi.co/trade-api/v2` (K-TR-01) serves authenticated portfolio reads. | OBSERVED | `GET /portfolio/balance`, `/portfolio/positions`, `/portfolio/fills`, `/portfolio/orders` each → HTTP 200 (`balance.json`, `positions.json`, `fills.json`, `orders.json`). | None — observation only. |
| K-TR-OBS-02 | The three `KALSHI-ACCESS-KEY` / `KALSHI-ACCESS-TIMESTAMP` (ms) / `KALSHI-ACCESS-SIGNATURE` (base64) headers (K-TR-02) authenticate a real demo request. Signed string = `timestamp_ms + "GET" + "/trade-api/v2" + path` **without** query params; RSA-PSS (MGF1-SHA256, salt = digest length) over SHA-256 (K-TR-03). | OBSERVED | With those headers + that signed string → 200; a deliberately wrong signed string → 401 `INCORRECT_API_KEY_SIGNATURE` (`auth_bad_signature.json`). | Confirms `livebook/ws_auth.kalshi_ws_sign_message` string form and the RSA-PSS `Signer` contract for a **REST** path. |
| K-TR-OBS-03 | Authentication failure → **HTTP 401**, body `{"error":{"code":"authentication_error","message":"We could not authenticate your request","details":<ENUM>}}`. `details` = `INCORRECT_API_KEY_SIGNATURE` for a bad signature; `INVALID_PARAMETER` for an unknown `KALSHI-ACCESS-KEY`. | OBSERVED | `auth_bad_signature.json` (401, `INCORRECT_API_KEY_SIGNATURE`); `auth_bad_key.json` (401, `INVALID_PARAMETER`). Doc K-TR-13 lists 401 but no body shape. | Informs `live_broker` error mapping when a REST trading path is later implemented (still unimplemented — A-037). |
| K-TR-OBS-04 | `GET /portfolio/positions` envelope: `{ "market_positions": [], "event_positions": [], "cursor": "" }`. Matches the K-TR-11 doc field names (`market_positions[]`, `event_positions[]`) and adds a top-level `cursor`. Per-row fields **not** observed (account empty). | OBSERVED (envelope only) | `positions.json` (200). | None. |
| K-TR-OBS-05 | `GET /portfolio/fills` envelope: `{ "fills": [], "cursor": "" }` (K-TR-09 doc names the `fills` array). Per-fill fields **not** observed (account empty). | OBSERVED (envelope only) | `fills.json` (200). | None. |
| K-TR-OBS-06 | The legacy `GET /portfolio/orders` list endpoint is **still live on demo** as of 2026-09-08 (K-TR-S9 deprecation date ≥ 2026-05-06 has not removed it). Envelope: `{ "orders": [], "cursor": "" }`. | OBSERVED | `orders.json` (200). | None. |
| K-TR-OBS-07 | `GET /portfolio/events/orders` (the V2 events collection path) → **HTTP 404** with a `text/plain` body (not JSON). The V2 `/portfolio/events/orders` path is not a readable collection; partially closes the doc-gap "whether the V2 order object is readable under `/portfolio/events/orders/…`". Reading a single order at `/portfolio/events/orders/{id}` was **not** probed. | OBSERVED | `orders_events.json` (404, `content-type: text/plain`). | None. |
| K-TR-OBS-08 | `GET /portfolio/orders/{order_id}` with a **non-UUID** `order_id` → **HTTP 400** `{"error":{"code":"invalid_UUID","message":"invalid UUID"}}` (not 404). Kalshi order ids are UUIDs; a malformed id is rejected before any lookup. A well-formed but unknown UUID was **not** probed, so the true not-found status/body for order-get stays **UNKNOWN**. | OBSERVED | `order_unknown.json` (400, `invalid_UUID`). | None. |
| K-TR-OBS-09 | No rate-limit headers (`X-RateLimit-*`, `RateLimit-*`) and no `Retry-After` appeared on any **2xx** response. Consistent with K-TR-12 ("429 responses do not include `Retry-After` or `X-RateLimit-*`"); extends it to successful responses. No 429 was triggered, so 429 body/headers stay doc-only. | OBSERVED | `content-type` + `date` were the only headers of interest present in every capture. | None. |
| K-TR-OBS-10 | Bonus (outside the K-TR rows): `GET /portfolio/balance` → 200 `{ "balance": <int cents>, "balance_dollars": <string>, "balance_breakdown": [ { "balance": <string>, "exchange_index": <int 0..3> } ], "portfolio_value": <int>, "updated_ts": <int unix s> }`. | OBSERVED | `balance.json` (values redacted). | None. |

#### 2026-09-08 (later) — controlled demo order-lifecycle attempt (blocked before any order)

A single minimal `DEMO` order (1 contract, `yes` bid @ $0.01, `post_only`, on a
market with an empty book — max notional $0.01) was attempted to move K-TR-06 /
K-TR-07 / K-TR-08 / K-TR-09 / K-TR-10 to OBSERVED. **No order was created:** the
demo API key is not provisioned for order entry. Portfolio reads still 200.
Tool: `scripts/observe_kalshi_demo_order_lifecycle.py`; fixtures in
`docs/evidence/kalshi-demo/lifecycle/*.json`.

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-11 | `POST /portfolio/orders` (legacy V1 create) on demo → **HTTP 410 Gone** `{"error":{"code":"deprecated_v1_order_endpoint","message":"Please switch to the V2 endpoints","details":<link to create-order-v2 docs>}}`. Confirms K-TR-04's "legacy `POST /portfolio/orders` is deprecated" — it is now fully retired for **writes** (while `GET /portfolio/orders` still returns 200, K-TR-OBS-06). | OBSERVED | `lifecycle/02_submit_legacy_orders.json` (410). | Live-broker Kalshi order submission must target the V2 path only. |
| K-TR-OBS-12 | `POST /portfolio/events/orders` (documented V2 create, K-TR-04) on demo with this key → **HTTP 404** `{"error":{"code":"user_not_found","message":"user not found","details":"Exchange user not found. For Predictions: reference … Exchange Sharding documentation."}}`. The 404 is an **account-provisioning** error, not path-not-found: the same key authenticates every portfolio **read** (K-TR-OBS-01) but is not resolvable as an "Exchange user" for order entry. **SUPERSEDED 2026-09-09 by K-TR-OBS-26:** once demo shard 1 was funded (K-TR-OBS-22), the identical `POST` returned **201**. The `404 user_not_found` was the *unfunded target shard* state — no "Exchange user" exists on a shard with no collateral. The `lifecycle/01…` fixture retains the original 404 capture. | OBSERVED (state now changed) | `lifecycle/01_submit_v2_events_orders.json` (404, pre-funding). | Was: blocked K-TR-06..10 OBSERVED evidence. Now resolved — see K-TR-OBS-26..33. |
| K-TR-OBS-13 | After both failed create attempts, `GET /portfolio/positions` and `GET /portfolio/fills` were **unchanged** (`{…: [], "cursor": ""}`). No order, position, or fill was created. Re-confirms K-TR-OBS-04 / K-TR-OBS-05 envelopes on a second same-day capture. | OBSERVED (envelope only) | `lifecycle/10_positions.json`, `lifecycle/11_fills.json` (200). | None. |

#### 2026-09-08 (later still) — demo shard-balance / exchange-status read-only probe

For A-038, a GET-only probe of the *inspection* half of the shard-funding path.
No funds were added, no collateral moved, no order touched. Tool:
`scripts/observe_kalshi_demo_shard_balance.py`; fixtures in
`docs/evidence/kalshi-demo/shard-balance/*.json` (account-scoped bodies redacted
by the D-024 sanitiser; the public `/exchange/status` body is kept verbatim).

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-14 | `GET /portfolio/balance?exchange_index=N` is live on demo for `N` ∈ {0,1,2,3} → each HTTP **200** with the same `GetBalanceResponse` schema as the unscoped call (`balance`, `balance_dollars`, `portfolio_value`, `updated_ts`, `balance_breakdown[]`). The scoped response still carries the **full 4-entry** `balance_breakdown` (one per `exchange_index` 0..3), not just the requested shard. Confirms the documented per-shard balance query param (K-TR-19). Values redacted — whether the scoped `balance` differs from the total was **not** recorded. | OBSERVED | `shard-balance/balance_all.json`, `shard-balance/balance_exchange_index_{0,1,2,3}.json` (all 200); `shard-balance/SUMMARY.json`. | None — observation only. |
| K-TR-OBS-15 | `GET /exchange/status` on demo, **unauthenticated** (`security: []`, K-TR-S12) → HTTP **200** `{ exchange_active, trading_active, intra_exchange_transfers_active, exchange_index_statuses[] }`. Observed **4** shard entries: `exchange_index` 0..3, each with `exchange_active = true`, `trading_active = true`, `intra_exchange_transfers_active = true`; `description` = `"Default"` (0), `"Demo shard 1"` (1), `"Demo shard 2"` (2), `""` (3). Top-level flags all `true`. So on demo, trading **and** intra-exchange transfers are active on every shard — the K-TR-20 remediation path is not gated by exchange status. | OBSERVED | `shard-balance/exchange_status.json` (200, body verbatim). | None. |
| K-TR-OBS-16 | This probe covers only the **inspection** endpoints (`GET /portfolio/balance[?exchange_index]`, `GET /exchange/status`). It did **not** add demo funds, call `POST /portfolio/intra_exchange_instance_transfer` or `POST /portfolio/target_balance_allocation`, or place an order. From the redacted fixtures it is **not** possible to confirm the demo account is funded or that any collateral is allocated on shard 1. Direct confirmation of demo shard funding / allocation remains **not done**. | OBSERVED (scope statement) | Absence of any write call in `scripts/observe_kalshi_demo_shard_balance.py`; `SUMMARY.json` lists GET probes only. | A-038 stays **blocking** (K-TR-OBS-12). |

#### 2026-09-08 (later still) — manual demo-UI shard transfer failed; GET-only diagnosis

**Manual evidence (operator, official Kalshi demo web UI — not scripted):**

- The demo account was **funded with $100 mock cash** (self-service, K-TR-18).
- Post-funding exchange balances shown in the UI: **Exchange 0 (Default) $100;
  Exchange 1 (Demo shard 1) $0; Exchange 2 $0; Exchange 3 $0.**
- A manual UI transfer **Exchange 0 → Exchange 1, amount $10** was attempted.
- The UI returned: **"Transfer failed: Service unavailable, please try again
  later."**
- The transfer was **not** retried. No order was placed.

**Cause is NOT known.** "Service unavailable" is not inferred to mean
insufficient funds, a provisioning failure, or any specific cause.

GET-only follow-up (`scripts/observe_kalshi_demo_shard_transfer.py`; fixtures in
`docs/evidence/kalshi-demo/shard-transfer/*.json`; account bodies redacted,
public `/exchange/status` verbatim). **No `POST` to any transfer / allocation
endpoint; no retry; no order.**

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-17 | Immediately after the failed UI transfer, `GET /portfolio/balance`, `GET /portfolio/balance?exchange_index=0`, and `GET /portfolio/balance?exchange_index=1` each returned **HTTP 200** with the full `GetBalanceResponse` (4-entry `balance_breakdown`). All monetary values are redacted in the fixtures, so the $100 / $0 split reported by the UI is **not** independently confirmed here. | OBSERVED (envelope only) | `shard-transfer/balance_all.json`, `shard-transfer/balance_exchange_index_{0,1}.json` (200). | None. |
| K-TR-OBS-18 | `GET /portfolio/intra_exchange_instance_transfers` (K-TR-21) on demo → **HTTP 200** `{"transfers": []}`. The failed UI transfer left **no transfer record** in the history list at probe time. This is consistent with the request being rejected before a record was created, but does **not** establish why. | OBSERVED | `shard-transfer/intra_exchange_instance_transfers.json` (200). | None. |
| K-TR-OBS-19 | `GET /portfolio/target_balance_allocation` on demo → **HTTP 200** `{"allocations": []}`. Confirms the changelog-documented `GET` exists (supersedes K-TR-20's "no GET documented", K-TR-21) and that **no standing allocation split is configured** (empty ⇒ auto-rebalancing disabled, K-TR-20). | OBSERVED | `shard-transfer/target_balance_allocation.json` (200). | None. |
| K-TR-OBS-20 | `GET /exchange/status` (unauth) at the same time → **HTTP 200**; **all four** demo shards (`exchange_index` 0..3) and the top-level object report `exchange_active = true`, `trading_active = true`, `intra_exchange_transfers_active = true`. So **Exchange 1 reports both `trading_active` and `intra_exchange_transfers_active` true** — the only transfer precondition exposed by a documented read-only endpoint (K-TR-20 / K-TR-S12) was **satisfied** when the UI transfer failed. Re-confirms K-TR-OBS-15 on a later capture. | OBSERVED | `shard-transfer/exchange_status.json` (200, body verbatim). | None. |
| K-TR-OBS-21 | **Documented-requirements comparison.** Kalshi's intra-exchange-instance-transfer docs (K-TR-20 / K-TR-S11) state **no** precondition this probe found violated: shard/transfer flags are all `true` (K-TR-OBS-20); no minimum amount, destination "initialization", or shard-activation requirement is documented; and **no documented error/status code maps to HTTP 503 / "Service unavailable"** (the error schema is a generic `{code, message, details?}`). The observed state is therefore **consistent with the documented happy path**, yet the UI transfer failed — the failure is **UNDOCUMENTED** and its cause is **UNKNOWN**. Not inferred to be funding, provisioning, or capacity. | OBSERVED + docs gap | K-TR-OBS-17..20; K-TR-20; K-TR-S9/S11/S17. | A-038 stays **blocking**; shard collateral still cannot be allocated on demo. |

#### 2026-09-08 (later still) — manual demo-UI shard transfer **succeeded**; GET-only confirmation

**Manual evidence (operator, official Kalshi demo web UI):** the operator
**re-attempted** the `Exchange 0 → Exchange 1` transfer of **$10** and it
**succeeded**; the UI then showed **Exchange 0 = $90, Exchange 1 = $10**. No
order was placed; the transfer was not repeated again.

GET-only confirmation (`scripts/observe_kalshi_demo_shard_transfer.py shard-funded`;
fixtures `docs/evidence/kalshi-demo/shard-funded/*.json`; account bodies redacted,
public `/exchange/status` verbatim). **No `POST`; no order.**

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-22 | `GET /portfolio/intra_exchange_instance_transfers` now returns **one** transfer record (was `{"transfers": []}` at K-TR-OBS-18). Fields present: `transfer_id`, `source` = `"event_contract"`, `destination` = `"event_contract"`, `source_exchange_shard`, `destination_exchange_shard`, `amount`, `status` = **`"complete"`**, `created_ts`. `amount` / `transfer_id` / `created_ts` / both shard indices are **redacted** in the fixture; `source`/`destination`/`status` are fixed enum constants and survive. So per Kalshi's own transfer history the retried cross-shard transfer **settled successfully** (`status = complete`), and the earlier "Service unavailable" (K-TR-OBS-17..21) was **not persistent**. | OBSERVED | `shard-funded/intra_exchange_instance_transfers.json` (200). | None. |
| K-TR-OBS-23 | `GET /portfolio/balance`, `?exchange_index=0`, `?exchange_index=1` each still → **HTTP 200** with the full `GetBalanceResponse` (4-entry `balance_breakdown`). All monetary values are redacted, so the operator-reported **$90 / $10** split is **not** independently confirmed from these fixtures — only that the endpoints answer and the schema is unchanged post-transfer. | OBSERVED (envelope only) | `shard-funded/balance_all.json`, `shard-funded/balance_exchange_index_{0,1}.json` (200). | None. |
| K-TR-OBS-24 | `GET /portfolio/target_balance_allocation` → **HTTP 200** `{"allocations": []}` — unchanged (K-TR-OBS-19). A one-off `intra_exchange_instance_transfer` does **not** create a standing allocation split. | OBSERVED | `shard-funded/target_balance_allocation.json` (200). | None. |
| K-TR-OBS-25 | `GET /exchange/status` (unauth) → **HTTP 200**; all four demo shards + top-level still report `exchange_active` / `trading_active` / `intra_exchange_transfers_active` = `true`. Re-confirms K-TR-OBS-15 / K-TR-OBS-20. | OBSERVED | `shard-funded/exchange_status.json` (200, verbatim). | None. |

**A-038 stays blocking.** What is now OBSERVED: a Kalshi **demo** cross-shard
`intra_exchange_instance_transfer` can **complete** (K-TR-OBS-22), and the
demo-funding + shard-transfer remediation steps work end-to-end up to *funded
shard 1*. What is **still not tested**: whether an order on the now-funded
shard 1 is accepted — `POST /portfolio/events/orders` was **not** re-attempted
(K-TR-OBS-12's `404 user_not_found` is unretested). A-038's core blocker
(OBSERVED create-order / cancel / status / fills, K-TR-05..10) is unresolved.

#### 2026-09-09 — funded-shard order lifecycle (submit → cancel round-trip)

After demo shard 1 was funded (K-TR-OBS-22), one **1-contract `yes` bid @
$0.01, `post_only`, GTC** order was placed on the verified shard-1 demo market
`KXMVECROSSCATEGORY-SHARD1-…` (`status = active`, **empty order book** — a
$0.01 bid cannot cross; `post_only` is the second guard) and immediately
cancelled. Max notional at risk: $0.01 of demo funny-money; no deliberate
fill; quantity never increased. Tool:
`scripts/observe_kalshi_demo_order_lifecycle.py lifecycle-funded`; fixtures
`docs/evidence/kalshi-demo/lifecycle-funded/*.json` (D-024 sanitiser; the
server `order_id` is scrubbed to `{order_id}` in every persisted path).

| # | Claim | Status | Evidence | Code impact |
|---|-------|--------|----------|-------------|
| K-TR-OBS-26 | **The `404 user_not_found` (K-TR-OBS-12) is resolved once the target shard is funded.** `POST /portfolio/events/orders` on demo with the same key → **HTTP 201**, body `{ client_order_id, fill_count, order_id, remaining_count, ts_ms }` — exactly the K-TR-06 documented create-order response key set; no lifecycle `status` on the create response (matches K-TR-06). Order body sent: the K-TR-05 field set (`ticker, side=bid, count="1", price="0.01", time_in_force=good_till_canceled, self_trade_prevention_type=maker, post_only=true`) with no `exchange_index` → auto-routed to shard 1 by the `…-SHARD1-…` ticker (K-TR-14). | OBSERVED | `lifecycle-funded/01_submit_v2_events_orders.json` (201). | Live-broker Kalshi create-order targets `POST /portfolio/events/orders`; the create response has no order status. |
| K-TR-OBS-27 | Immediately after submit, `GET /portfolio/orders` → 200 with the resting order present; the order row shape (`GetOrder` / list element) is OBSERVED to carry: `action, book_side, client_order_id, created_time, exchange_index, fill_count_fp, initial_count_fp, last_update_time, maker_fees_dollars, maker_fill_cost_dollars, no_price_dollars, order_id, outcome_side, remaining_count_fp, self_trade_prevention_type, side, status, subaccount_number, taker_fees_dollars, taker_fill_cost_dollars, ticker, type, user_id, yes_price_dollars`. This is a **superset** of K-TR-08's documented field list (adds `action, book_side, type, created_time, last_update_time, user_id, subaccount_number, yes_price_dollars, no_price_dollars`). All per-order **values** are redacted by the sanitiser. | OBSERVED (field names only) | `lifecycle-funded/03_orders_after_submit.json`, `lifecycle-funded/04_get_order.json` (200). | Informs a future Kalshi order-status mapping; field values still doc-only. |
| K-TR-OBS-28 | Single-order read `GET /portfolio/orders/{order_id}` on demo **404s for a sharded order unless it is shard-routed** — the same routing rule the cancel needs (K-TR-OBS-30). With `?market_ticker=…SHARD1…` it returns 200 and the K-TR-OBS-27 row shape. | OBSERVED | `lifecycle-funded/04_get_order.json` (200, path shows the `market_ticker` query); an earlier unrouted attempt returned 404. | Live-broker order-status reads for a sharded venue must pass `market_ticker` / `exchange_index`. |
| K-TR-OBS-29 | Idempotency: re-`POST` of the **identical `client_order_id`** while the order rests → **HTTP 409**, body `{ error: { code, message } }` (values redacted). Confirms K-TR-07's server-enforced dedupe; no second order was created (K-TR-OBS-32). | OBSERVED (envelope only) | `lifecycle-funded/05_submit_duplicate_client_order_id.json` (409). | Confirms `live_broker.IdempotencyGuard` design intent has a venue-side counterpart. |
| K-TR-OBS-30 | **Cancel requires shard routing.** `DELETE /portfolio/events/orders/{order_id}` with **no** `market_ticker` / `exchange_index` query → **HTTP 404** `not_found`; the legacy `DELETE /portfolio/orders/{order_id}` → **410** `deprecated_v1_order_endpoint`. `DELETE /portfolio/events/orders/{order_id}?market_ticker=…SHARD1…` → **HTTP 200**, body `{ order_id, reduced_by, ts_ms }` — the K-TR-10 documented cancel response; `reduced_by` was the full order size. The cancel-order-v2 reference lists `subaccount`, `exchange_index` (omit / `-1` = auto-route) and `market_ticker` (required for auto-route) query params — a body-less DELETE has no ticker to auto-route from, so one of these is mandatory for a sharded order. | OBSERVED | `lifecycle-funded/06_cancel_v2_events_orders.json` (200, `market_ticker` query in the record); earlier unrouted attempts 404 / 410. | Live-broker Kalshi cancel: `DELETE /portfolio/events/orders/{id}?market_ticker=…` (or `exchange_index=`). |
| K-TR-OBS-31 | Post-cancel: `GET /portfolio/orders/{order_id}?market_ticker=…` → 200 (row shape as K-TR-OBS-27; `status` value redacted). `GET /portfolio/orders?status=resting` → **`{"orders": [], "cursor": ""}`** — the order left the resting book. (An out-of-band read confirmed `status = "canceled"`, `remaining_count_fp = 0` — raw value not persisted.) | OBSERVED | `lifecycle-funded/08_get_order_after_cancel.json`, `lifecycle-funded/09b_orders_resting_after_cancel.json` (200). | None. |
| K-TR-OBS-32 | After submit + cancel, `GET /portfolio/positions` → `{market_positions: [], event_positions: [], cursor: ""}` and `GET /portfolio/fills` → `{fills: [], cursor: ""}`. **No fill, no position** — the resting $0.01 bid never matched (empty book + `post_only`). `GET /portfolio/orders` (unfiltered) lists the order with a terminal status; `?status=resting` is empty (K-TR-OBS-31). | OBSERVED (envelope only) | `lifecycle-funded/10_positions.json`, `lifecycle-funded/11_fills.json` (200). | Confirms K-TR-OBS-04 / K-TR-OBS-05 envelopes on an account that has now had order activity; per-row shapes still not observed (no fill / position rows). |
| K-TR-OBS-33 | Safety: after the run, an independent GET showed **0 resting orders**, **0 fills**, **0 positions**; every demo order created across A-038 (5 total) is `canceled` with `remaining_count_fp = 0`. Nothing left open; `LIVE_TRADING` never read or set; production Kalshi never called. | OBSERVED | Out-of-band `GET /portfolio/orders?status=resting` / `/fills` / `/positions` (not fixtured — values redacted anyway). | None. |

### Not verified / still open

- **Order-row / fill / position field _values_** — the `GET /portfolio/orders`
  row shape (field _names_) is now OBSERVED (K-TR-OBS-27), but every value is
  redacted by the D-024 sanitiser, so `status` enum values (`resting` /
  `canceled` / `executed`), fixed-point formats, and fee/cost semantics are
  still doc-only (K-TR-08). `fills[]` / `market_positions[]` / `event_positions[]`
  **rows** were never populated (the probe order never filled and holds no
  position) — K-TR-09 / K-TR-11 element fields stay doc-only.
- Order-get not-found behavior for a **well-formed unknown UUID**, and single
  order read at `/portfolio/events/orders/{id}`. (New: an unrouted
  `GET /portfolio/orders/{id}` for a _real_ sharded order can 404 —
  K-TR-OBS-28.)
- **Create-order (K-TR-05/06 → K-TR-OBS-26), idempotency 409 (K-TR-07 →
  K-TR-OBS-29), single-order read (K-TR-08 → K-TR-OBS-27/28), cancel (K-TR-10 →
  K-TR-OBS-30) are now OBSERVED on demo shard 1.** Still doc-only: partial-fill
  reporting (K-TR-08 `fill_count_fp` > 0 with `status = resting`), `GET
  /portfolio/fills` per-fill rows (K-TR-09) — no fill was produced.
- `429` body and headers (K-TR-12) — not triggered.
- Whether an `exchange_index`-scoped `GET /portfolio/balance` returns a
  **different** `balance` / `portfolio_value` than the unscoped call — the
  scoped values are redacted in the fixtures (K-TR-OBS-14).
- Order entry on the funded demo shard 1 is now **OBSERVED** working
  (K-TR-OBS-26..33): a `post_only` $0.01 bid submitted (201), listed, read,
  duplicate-rejected (409), cancelled (200), and left no fill / position.
  A-038's demo-observation blocker is cleared; the remaining live-use blocker
  is the real-money gate + the unimplemented `live_broker` (A-037 / D-023),
  not demo provisioning.
- The earlier "Service unavailable" on the first demo-UI transfer
  (K-TR-OBS-17..21) was **transient** — a later identical transfer completed
  (K-TR-OBS-22). Its root cause is still undiagnosed but is no longer a
  standing blocker for the transfer step itself. No `POST` was issued by this
  project in either capture.
- Single-transfer `GET /portfolio/intra_exchange_instance_transfers/{transfer_id}`
  — mentioned in the 2026-08-27 changelog but absent from the API-reference
  OpenAPI spec (K-TR-21). Not probed.
- Nothing here promotes a Real-money gate item. "Position/order reconciliation"
  still needs element-level shapes plus a live round-trip; A-037 / D-023 stand.

---

## Polymarket US — REST trading API (research only; pre-M4, no code)

Verification date: **2026-09-08** (official docs read at `docs.polymarket.us`).
**No authenticated request was made**, no key, no signature, no fixture.
Every row is **doc-only** (`VERIFIED (docs)`); nothing is `OBSERVED` or
`TESTED`. International (non-US) Polymarket behavior was **not** used as
evidence — no official page establishing US/international equivalence was found,
so none is assumed (carries A-013's caveat forward). Resolves **no** Real-money
gate item.

### Official sources consulted

| # | Source | URL |
|---|---|---|
| P-TR-S1 | Authentication | https://docs.polymarket.us/api-reference/authentication |
| P-TR-S2 | Orders API Overview | https://docs.polymarket.us/api-reference/orders/overview |
| P-TR-S3 | Create Order — API reference | https://docs.polymarket.us/api-reference/orders/create-order |
| P-TR-S4 | Cancel Order — API reference | https://docs.polymarket.us/api-reference/orders/cancel-order |
| P-TR-S5 | Get Order — API reference | https://docs.polymarket.us/api-reference/orders/get-order |
| P-TR-S6 | Get User Positions — API reference | https://docs.polymarket.us/api-reference/portfolio/get-user-positions |
| P-TR-S7 | Error Handling (trader guide) | https://docs.polymarket.us/trader-guide/error-handling |
| P-TR-S8 | Partners — Reconciliation / funded-order idempotency (EP3) | https://docs.polymarket.us/partners/reconciliation |

### Claims

| ID | Claim | Evidence status | Source / observation | Used in code |
|---|---|---|---|---|
| P-TR-01 | Authenticated REST base is `https://api.polymarket.us/v1` (example: `GET https://api.polymarket.us/v1/portfolio/positions`). This differs from the market-data host `gateway.polymarket.us` (P-01). | VERIFIED (docs) | P-TR-S1 example. Whether market data is also served from `api.polymarket.us` (or trading from `gateway.`) is not stated — **UNKNOWN**. | None — evidence only. |
| P-TR-02 | Auth headers: `X-PM-Access-Key` (Key ID), `X-PM-Timestamp` (current time in **milliseconds**), `X-PM-Signature` (base64). Signed message = `"{timestamp}{method}{path}"` in that order, **body not included**. Signature = **Ed25519** over the message, base64-encoded. Timestamp must be within **30 s** of server time. | VERIFIED (docs) | P-TR-S1. Matches WS-A-S5 / P-WS-AUTH-02. Query-string handling in `path` not specified — **UNKNOWN**. | None. |
| P-TR-03 | Submit order: **`POST /v1/orders`** (single); `POST /v1/orders/batched` (≤ 20). Async by default; `synchronousExecution: true` blocks up to ~10 s for final state and is **discouraged** in favor of async submit + poll `GET /v1/order/{orderId}`. | VERIFIED (docs) | P-TR-S2 endpoint list; P-TR-S2 execution guidance. | None. |
| P-TR-04 | Create-order request body: `marketSlug` (string, **req**); `type` (`ORDER_TYPE_LIMIT`\|`ORDER_TYPE_MARKET`); `price` (Amount `{value: decimal-string, currency}` — required for limit); `quantity` (double, contracts); `tif` (`TIME_IN_FORCE_DAY`\|`GOOD_TILL_CANCEL`\|`GOOD_TILL_DATE`\|`IMMEDIATE_OR_CANCEL`\|`FILL_OR_KILL`); `goodTillTime` (date-time, GTD); `intent` (`ORDER_INTENT_BUY_LONG`\|`SELL_LONG`\|`BUY_SHORT`\|`SELL_SHORT`); `outcomeSide` (`OUTCOME_SIDE_YES`\|`OUTCOME_SIDE_NO`); `action` (`ORDER_ACTION_BUY`\|`ORDER_ACTION_SELL`); `participateDontInitiate` (bool, maker-only); `cashOrderQty` (Amount, market orders); `manualOrderIndicator`; `synchronousExecution` (bool); `maxBlockTime` (int64 string, s); `slippageTolerance` (`{currentPrice, bips, ticks}`). All fields **except `marketSlug` are marked optional** in the schema (server-side conditional requirements not fully documented). | VERIFIED (docs) | P-TR-S3 request schema. The `intent` vs `action`+`outcomeSide` precedence is **UNKNOWN**. | None. |
| P-TR-05 | Create-order response `CreateOrderResponse`: `id` (string — exchange-assigned order id), `executions[]` (present only if `synchronousExecution` was requested). Each `Execution`: `id`, `tradeId`, `type` (ExecutionType), `order` (full Order), `lastShares`, `lastPx` (Amount), `orderRejectReason` (OrdRejectReason if rejected), `transactTime`, `aggressor` (bool), `commissionNotionalCollected` (Amount). | VERIFIED (docs) | P-TR-S3 response schema. | None. |
| P-TR-06 | Order object / status: `state` (OrderState) ∈ {`ORDER_STATE_NEW`, `PENDING_NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REPLACED`, `REJECTED`, `EXPIRED`, `PENDING_REPLACE`, `PENDING_CANCEL`, `PENDING_RISK`}. Quantities: `quantity` (original), `cumQuantity` (cumulative filled), `leavesQuantity` (remaining unfilled) — all doubles; `avgPx` (Amount — average fill price). Timestamps `createTime`, `insertTime`. **Explicit `ORDER_STATE_PARTIALLY_FILLED`** — unlike Kalshi. | VERIFIED (docs) | P-TR-S3, P-TR-S5 schemas. | None. |
| P-TR-07 | Order status read: `GET /v1/order/{orderId}` returns the Order object above. The get-order schema has **no `executions`/`fills` array** — partial-fill detail is only `cumQuantity` / `leavesQuantity` / `avgPx`, or the Private WebSocket stream (fills/cancels), or an `activities`/trades endpoint (not surveyed). List open orders: `GET /v1/orders/open`. | VERIFIED (docs) | P-TR-S5; P-TR-S2 (recommends Private WS for real-time fills). | None. |
| P-TR-08 | Cancel order: **`POST /v1/order/{orderId}/cancel`** (single); also `POST /v1/orders/batched/cancel` (≤ 20) and `POST /v1/orders/open/cancel` (all, optional market filter) per P-TR-S2. Single-cancel request body: `marketSlug` (string). Response `CancelOrderResponse` is **empty on success** (no fields). Cancellation is by **exchange `orderId` only**. | VERIFIED (docs) | P-TR-S4 (single); P-TR-S2 (batch/all). P-TR-S4 page itself showed only the single endpoint — batch/all come from the overview. | None. |
| P-TR-09 | Positions: **`GET /v1/portfolio/positions`**. Query: `market` (slug filter), `limit` (default 100), `cursor`. Response `GetUserPositionsResponse`: `positions` (object keyed by market slug → `UserPosition`), `nextCursor` (string), `eof` (bool), `availablePositions[]` (deprecated). `UserPosition`: `netPositionDecimal`, `qtyBoughtDecimal`, `qtySoldDecimal`, `bodPositionDecimal`, `qtyAvailableDecimal` (nullable) — all decimal strings; `cost` (Amount — total cost basis), `realized` (Amount — realized PnL), `cashValue` (Amount — labeled "Unrealized PnL for the position"), `marketMetadata`, `expired` (bool), `updateTime` (date-time). | VERIFIED (docs) | P-TR-S6 schema. The `cashValue` label ("Unrealized PnL") vs name (suggests market value) is **ambiguous — UNKNOWN**. | None. |
| P-TR-10 | Idempotency / client order id on the **standard** `POST /v1/orders`: **no request-body field for a client order id / idempotency key is documented** (P-TR-S2 overview and P-TR-S3 schema have none). However P-TR-S7 (error handling) lists a `409 Conflict` cause "Duplicate order with same **ClOrdID**", implying a `ClOrdID` exists somewhere in the order path. This is a **documentation conflict — UNKNOWN** how a retail REST caller sets `ClOrdID`. | VERIFIED (docs, conflicting) | P-TR-S2 + P-TR-S3 (absent) vs P-TR-S7 (409 "same ClOrdID"). | Motivates keeping `live_broker.IdempotencyGuard` as **local-only** for this venue. |
| P-TR-11 | Idempotency in the **partner / funded-order (EP3)** flow only: `CreateFundedOrder` takes `idempotency_key` **and** `clord_id`; retrying with the same pair "can never double-fund or double-place"; changing `clord_id` under the same key is rejected as an idempotency conflict; `clord_id` is echoed as `clOrdID` on Drop Copy / FIX drop-copy execution reports. This is a **separate API surface** from `POST /v1/orders`; do not assume it applies to the retail REST endpoint. | VERIFIED (docs) | P-TR-S8. | None. |
| P-TR-12 | Rate limits: **global 20 requests/second per API key across all endpoints**; over-limit → `429 Too Many Requests`. P-TR-S7 says "for 429 errors, use the `Retry-After` header value"; P-TR-S2 does **not** mention a `Retry-After` header or a 429 body shape — **partial conflict; presence of `Retry-After` UNKNOWN**. Recommended retry: exponential backoff on 429/500/502/503/504, 3–5 attempts. | VERIFIED (docs, partially conflicting) | P-TR-S2 (20 rps, 429) + P-TR-S7 (Retry-After, backoff). | None. |
| P-TR-13 | Documented HTTP error statuses on create/cancel: 400, 401, 500 (P-TR-S3/S4). `OrdRejectReason` enum: `ORD_REJECT_REASON_{EXCHANGE_OPTION, UNKNOWN_MARKET, EXCHANGE_CLOSED, INCORRECT_QUANTITY, INVALID_PRICE_INCREMENT, INCORRECT_ORDER_TYPE, PRICE_OUT_OF_BOUNDS, NO_LIQUIDITY}` (returned on a rejected execution, not as an HTTP status). 409 Conflict documented only in the trader-guide (P-TR-S7), not on the reference pages. | VERIFIED (docs) | P-TR-S3, P-TR-S7. | None. |

### Not verified / gaps (pre-M4)

- **No live authenticated call, no capture, no fixture.** Nothing is `OBSERVED`
  or `TESTED`.
- **International Polymarket was not used as evidence.** No official page
  establishing US ↔ international trading-API equivalence was located; the
  CLOB/EIP-712 signing scheme of international Polymarket is **not** assumed here.
- Retail client-order-id mechanism (P-TR-10) is a genuine documentation
  conflict — `ClOrdID` is referenced for 409 handling but has no documented
  request field. **Blocking-level UNKNOWN** for "Duplicate-order prevention".
- `Retry-After` header presence on 429 (P-TR-12) is contradicted between two
  doc pages — **UNKNOWN**.
- `cashValue` semantics on `UserPosition` (P-TR-09) — name vs description
  disagree — **UNKNOWN**.
- `intent` vs `action` + `outcomeSide` precedence, and which of
  `quantity`/`cashOrderQty`/`cashOrderQty` applies per order type — **UNKNOWN**.
- The `activities` / trades endpoint and Private WebSocket stream schemas
  (real-time fill reporting) were **not** surveyed.
- No `openapi.yaml` / SDK-source cross-check for Polymarket US trading in this
  pass — reference pages only.
- No mapping to the project's domain models (out of scope).

---

## Real-money gate status after this research pass (2026-09-08)

ROADMAP "Real-money gate → **Official API behavior**" has two halves:

1. **Research the documented behavior** — done for both venues above
   (authentication/signing, submit, cancel, order status, positions,
   idempotency, errors/rate limits, partial fills). Recorded as `VERIFIED
   (docs)` with explicit `UNKNOWN` gaps.
2. **Confirm it against a real venue** (`OBSERVED` + a `TESTED` offline pin) —
   **partly done, DEMO only** (added 2026-09-09 by the real-money-gate audit):
   Kalshi **demo** trading endpoints are now OBSERVED — authenticated
   `POST /portfolio/events/orders` (201), duplicate-`client_order_id` `409`,
   `DELETE …?market_ticker=` (200), and the portfolio reads (K-TR-OBS-26..33,
   `docs/evidence/kalshi-demo/lifecycle-funded/`). **Still NOT done:**
   production Kalshi (zero evidence); **Polymarket US trading** (zero
   authenticated calls — all P-TR-* rows are `VERIFIED (docs)` with open
   `UNKNOWN`s); any OBSERVED **fill** on either venue (the demo round-trip
   produced none).

Therefore the gate item stays **unchecked** — demo evidence does not satisfy
"Real money remains locked until all are verified." Blocking `UNKNOWN`s that
must close before live use: production-Kalshi authenticated capture; Polymarket
US retail client-order-id / `ClOrdID` mechanism (P-TR-10) and `Retry-After`
behavior (P-TR-12); an OBSERVED partial fill. Real-money trading stays disabled
(D-002; `live_broker` still raises `UnsupportedLiveOperationError`, A-037). No
adapter was implemented and `LIVE_TRADING` remains `False`.

### #2 "Stable live market data" — partial, 2026-09-09

A bounded production session was run (K-MD-OBS-01..04, above): production
**REST** market data — snapshot init, a 5-minute 44-poll window at 100 % HTTP
200 with a demonstrably live book, and a REST transport-failure/recovery — is
now **OBSERVED**. The item's core (a **stable live WebSocket feed**: connect,
`seq`-ordered snapshot→delta updates, disconnect → reconnect → resync) is
**NOT** verified: Kalshi's production market-data WS requires an authenticated
handshake (K-WS-01) and no production Kalshi credential exists here, so no WS
session was opened. **A-030 / A-028 stay UNVERIFIED.** Item #2 stays
**unchecked**; #7 and #8 are **not** advanced. Smallest next action: a
production Kalshi API key + an RSA-PSS signer, then one authenticated
`wss://external-api-ws.kalshi.com/trade-api/ws/v2` session capturing a
snapshot + deltas + a reconnect.
