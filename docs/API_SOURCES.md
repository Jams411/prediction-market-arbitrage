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
  `ConnectionClosed` and recv-timeout both surface as `TransportClosed`. Server
  Ping/Pong keepalive is handled by the library. It plugs into the unchanged
  `LiveBookConnection`.
- **RSA-PSS / Ed25519 signing is still injected** (`Signer`) — the framework
  imports no `cryptography`. A caller supplies the signer for a real connection.
- **No live OBSERVED handshake or frame against a real venue.** The transport is
  tested against a **local `websockets` server on loopback** (a real socket
  round-trip, but the local server accepts any headers). No authenticated
  connection to Kalshi / Polymarket US was made; no WS fixture was captured; the
  signing message strings / header names are unit-tested only against the docs.
  Whether a real venue server accepts the handshake is **not verified** —
  recorded as **A-030**.
- Kalshi `orderbook_delta` is described as a **private channel** (WS-A-S1) — it
  rides the authenticated session even though its payload is public market data.
- Polymarket US `X-PM-Signature` construction uses `path` with no documented
  query-strip rule (there are no query params on the WS path, so this does not
  bite here).
