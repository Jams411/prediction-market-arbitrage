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
| A-027 | The M2.1 live book layer holds **no credentials in the framework** and does its network I/O only through the injected `WebSocketTransport` seam. `livebook.transport.LiveBookConnection` is the deterministic manager (connect → subscribe → pump → `mark_disconnected` → backoff reconnect → REST `resync` → `HEALTHY`); `livebook.ws_transport.WebsocketsTransport` is a concrete transport over the `websockets` library; `livebook.ws_auth` builds the docs-verified handshake message + headers + subscribe command (RSA-PSS / Ed25519 via an injected `Signer` — no `cryptography` import); `livebook.credentials` holds redacted, config-injected keys. | ACCEPTED (scope) + IMPLEMENTED — the whole boundary, backoff, reconnect/resync flow, and a real `websockets` transport are code; tested with fakes and a local loopback server. What remains is a real authenticated connection to a venue (A-030). | Yes |
| A-028 | Kalshi `orderbook_delta.delta_fp` is applied **additively** to the aggregated contract count already resting at that `(side, price_dollars)` level; a level reaching exactly zero is removed; a result below zero is a desync. | UNVERIFIED — the channel wording ("incremental updates to maintain a live orderbook") and the signed fixed-point value support no other reading, but the exact rule is not stated and is **not OBSERVED** against a real feed (auth-gated). `livebook/state.py` implements additive application; a real capture must confirm before live use. | Yes |
| A-029 | The Kalshi live book carries **no market tradability state** — `orderbook_delta` frames have no `state` field; lifecycle/halt information is on a separate channel (`market-and-event-lifecycle`) not decoded in M2.1. So `LiveBookFeed.health()` gates on market state **only** for feeds that report one (Polymarket US `MARKET_STATE_*`); a Kalshi feed can read `HEALTHY` during a halt this layer cannot see. | VERIFIED (docs) that the field is absent; the **consequence** (no halt gating for Kalshi) is an accepted M2.1 gap — the lifecycle channel is future work. | Yes |
| A-030 | The authenticated WebSocket handshake, subscribe body, and frame formats built by `livebook.ws_auth` and carried by `livebook.ws_transport.WebsocketsTransport` match what the real Kalshi / Polymarket US servers require. | **UNVERIFIED — docs-only, no live OBSERVED handshake against a venue.** Every claim (URLs, header names, `timestamp + "GET" + path` sign strings, subscribe shapes) is transcribed from official docs (WS-A-S1..S6) and unit-tested; the concrete `websockets` transport is exercised against a **local loopback server** (real socket, but it accepts any headers). No authenticated connection to Kalshi / Polymarket US was made and no WS fixture was captured — the framework holds no credentials and no signer implementation. A real connect (with credentials + a `Signer`) + one captured `orderbook_delta` / `MARKET_DATA` frame is required before live use, and resolves A-028 at the same time. Also unresolved: the Polymarket US subscribe casing/enum discrepancy between two doc pages (P-WS-AUTH-03). | Yes |
| A-031 | The M2.2 recorder normalizes every timezone-aware timestamp to a naive-UTC `TIMESTAMP` (microsecond precision) and stores every `Decimal` as exact `str(Decimal)` text; this loses no fidelity the pipeline actually carries. | ACCEPTED (design) — domain timestamps are already UTC and microsecond-truncated (naive `TIMESTAMP` preserves the instant; a reader re-attaches UTC), and string-Decimal round-trips exactly at any scale (no fixed-scale `DECIMAL` column). The original `tzinfo` object and sub-microsecond precision are not preserved; neither exists upstream. No sub-µs or non-UTC timestamp reaches the recorder in the current pipeline — revisit if that changes. M2.3 `replay._read.to_utc` performs the reattach (`.replace(tzinfo=UTC)`). | No |
| A-032 | An order book reconstructed by the M2.3 replay adapter is faithful for every field strategy / engine code uses (`Contract.id`, `outcome`, `venue.id`, `market.id`, exact `Decimal` prices / quantities, level ordering, UTC book timestamp), but `Venue.name` and `Market.title` are synthesized from the ids because the recorder never stored display names. | ACCEPTED (design) — the M1.5 engine and M2.1 book layer join on `Contract.id` (A-020) and never read `Venue.name` / `Market.title`; the recorder schema (M2.2) deliberately holds identifiers only. `replay._read.rebuild_contract` sets `name = id`, `title = market_id`. A consumer that needs true display names must join against a market catalogue outside the recording. | No |
| A-033 | The M2.4 paper broker models **taker** execution only: every fill crosses the resting book (`liquidity = "taker"`), the executed price of each level slice is `SlippageModel.adjust(...)` clamped into `[0.0001, 0.9999]`, one `Fill` is emitted per book level with its fee from the injected `FeeModel`, and latency / cancellation are resolved by comparing injected `timedelta`s (a fill that lands before a cancel's effective time wins). | ACCEPTED (design) — resting-order / maker-fill simulation, queue-position modelling, iceberg/hidden size, and a verified minimum price tick are deferred; there is no evidence for venue tick size (A-004 family) so the clamp bounds are a chosen epsilon, not a venue rule. Deterministic given (requests, injected books, injected times, config); no wall-clock, no RNG. Positive simulated fills are **not** proof of realized fills — leg risk, real latency, and venue rejection semantics stay unproven until a live path exists. | Yes |
| A-034 | The M2.5 risk manager fails **closed**: a limit that is set but whose required input is missing (`positions`, `opportunity`, `health`, `leg`) or unhealthy (`FeedHealth.trading_enabled == False`, future-dated health timestamp) produces `allowed = False` with a reason, never a skipped check. `RiskManager.evaluate_order` / `observe_leg_risk` update the per-pair "unhedged since" timer as a deliberate side effect (it must remember when a pair first went unhedged); portfolio exposure is valued at each contract's `PositionRow.avg_price` (cost basis) only as a deterministic fallback approximation when no explicit `marks` are supplied. | ACCEPTED (design) — deterministic given (limits, injected `now`, the supplied inputs, and `RiskState`); no wall-clock, no RNG. The manager only vetoes — it emits no orders and contains no strategy logic. Explicit current `marks` are the preferred exposure valuation. Cost basis is **not** a conservative bound: it can understate current exposure after an adverse price move, so for live-use semantics `max_exposure` must not be treated as safely enforced when exposure is valued from cost-basis / stale inputs alone — a live caller must supply current `marks`. (The check still fails closed when a contract cannot be valued at all.) Kill switch, error streak, daily-PnL ledger, and unhedged timers are the only state it owns. | Yes |
| A-035 | The M3.1 operational dashboard is a **read-only, deterministic projection**: `build_dashboard(*, now, ...)` inspects the objects the pipeline already produces (M1.4 registry, M1.5 `OpportunityEvaluation`, M2.1 `LiveBookFeed` / `FeedHealth`, M2.4 `Order` / `Fill` / `PositionRow` / `LegRiskSnapshot`, M2.2 `PnlRow`, M2.5 `RiskManager`) and returns an immutable `DashboardView`; it mutates nothing, reads no wall-clock, opens no socket, and does not read the recorder DuckDB. "WebSocket state" is **derived from `FeedHealth.status`** (livebook exposes no separate socket-state accessor). Alert severity: `ALERT` = kill switch / a hard-unhealthy feed / any stale feed; `WARN` = resyncing or market-not-open feed, consecutive errors, realized daily loss, unhedged pair/leg, rejected paper order, stale opportunity/position, rejected last `RiskDecision`. Dashboard exposure reuses the A-034 mark fallback (explicit `marks` → cost basis → none) and cost-basis exposure is labelled approximate. | ACCEPTED (design) — deterministic given (`now`, supplied objects); no wall-clock, no RNG, no I/O. Display-only: no alert is escalated, paged, or emailed anywhere. The dashboard is a strict observer and cannot perturb the pipeline. Real-money trading stays disabled (D-002). See `docs/DECISIONS.md` D-020. | No |
| A-036 | The M3.3 paper-performance report (`prediction_market_arbitrage.perf_report.build_report`) is a **pure read-only projection of one recording**, read through the M2.3 `ReplaySession` (no DuckDB access, no wall-clock, no writes). **Opportunity duration is derived, not recorded**: the recorder stores discrete `OpportunityEvaluation` rows, so an "episode" is a maximal run of consecutive positive-edge evaluations for one `pair_id` (time-ordered) and its duration is `last_eval_time − first_eval_time`; a single-observation episode has no duration and is counted separately, never as `0`. **Leg-risk events are not persisted** (the M2.2 schema has no leg-risk table) and are reported as unavailable, not as `0` events. Every numeric aggregate is `None` (rendered `n/a`, with the reason listed in `PerfReport.unavailable`) when the recording does not support it — kept distinct from a real `0`. | ACCEPTED (design) — deterministic given the recording; no wall-clock, no RNG, no I/O beyond the read-only replay connection. Report describes **paper** results only; positive paper PnL is not proof of realised profit. Drawdown is computed on recorded PnL samples, not a continuous curve; an episode still open at end-of-recording is measured only to its last positive eval. Real-money trading stays disabled (D-002). See `docs/DECISIONS.md` D-022. | No |
| A-037 | The M3.4 `prediction_market_arbitrage.live_broker` package is an **interface boundary only**. There is **no primary evidence** in `docs/API_SOURCES.md` for any order-placement, cancellation, order-status, or positions endpoint on Kalshi or Polymarket US (every K-* / P-* entry is market-data), so `KalshiLiveBroker` / `PolymarketUsLiveBroker` implement **no** operation — each raises `UnsupportedLiveOperationError` naming the evidence gap, even with an armed gate and credentials present. Nothing signs or sends a request. `LIVE_TRADING` is `False` by default and can only be armed with the exact literal phrase `I_UNDERSTAND_THIS_PLACES_REAL_ORDERS` (frozen `LiveTradingGate`; `PMA_LIVE_TRADING=1` / `true` do nothing). The `IdempotencyGuard` is the **local** (process-memory) half of duplicate-order prevention only — venue-side idempotency behaviour is unverified. Trading credentials are isolated from the M2.1 market-data credentials (separate types + `KALSHI_TRADING_*` / `POLYMARKET_US_TRADING_*` env vars) and redacted in `repr`. | ACCEPTED (design) — deterministic; no network, no venue, no real order. This does **not** resolve any Real-money gate item; "Live mode cannot activate accidentally", "Duplicate-order prevention", "Credential isolation", and "Position/order reconciliation" all still require a captured trading API and a live run. Real-money trading stays disabled (D-002). See `docs/DECISIONS.md` D-023. | Yes |
| A-038 | The provisioned Kalshi **demo** API key (`pma-kalshi-demo-api-key-id`) could not place a minimal controlled demo order (1 contract, `yes` bid @ $0.01, `post_only`, empty-book market): `POST /portfolio/events/orders` → **404 `user_not_found`** ("Exchange user not found … Exchange Sharding"), while every `GET /portfolio/*` on the same key returns 200. The legacy `POST /portfolio/orders` path is separately retired (**410 `deprecated_v1_order_endpoint`**). **Docs-only research 2026-09-08 (K-TR-14..17; official Kalshi sources):** (a) the probe market ticker was `…-SHARD1-…`, and `exchange_index` omitted → the order auto-routed to exchange shard 1 (K-TR-14). (b) "Programmatic traders must preallocate collateral on a given exchange shard before order placement" (K-TR-15). (c) demo accounts are **not** pre-funded — mock funds are added self-service via a test payment method (K-TR-17) — and this key's account shows `portfolio_value = 0` / all-zero balance breakdown (K-TR-OBS-10), i.e. never funded. (d) Kalshi API keys are self-service from Profile Settings, identical for demo and prod, with **no permission scopes / roles and no approval or support step** (K-TR-16) — so this is **not** an API-key-permission problem. (e) The remediation path is self-service and documented: fund the demo account, then either route to shard 0 or preallocate collateral to the target shard via `POST /portfolio/intra_exchange_instance_transfer` / `POST /portfolio/target_balance_allocation`, checking `GET /exchange/status` (K-TR-15). **UNKNOWN (official evidence insufficient):** `404` / `user_not_found` / "Exchange user not found" is **undocumented** for create-order-v2 (K-TR-13 lists only 400/401/409/429/500); whether the 404 is specifically caused by "unfunded / no shard collateral" versus some other account-setup gap is **not stated by Kalshi** and is inference only; whether a *different demo account* (as opposed to the same account, funded) is required is **not documented** (no account-type gate for demo API trading was found). **Read-only follow-up 2026-09-08 (K-TR-18..20 docs; K-TR-OBS-14..16 probe):** the documented self-service demo-funding flow (test debit card / Plaid sandbox / Google Pay / testnet crypto at `demo.kalshi.co/sign-up`) is captured (K-TR-18); per-shard balance is read via `GET /portfolio/balance?exchange_index=N` — confirmed live on demo for N=0..3 (K-TR-OBS-14); `GET /exchange/status` (public) shows all 4 demo shards `trading_active` and `intra_exchange_transfers_active` = true (K-TR-OBS-15); collateral is moved with `POST /portfolio/intra_exchange_instance_transfer` (centicents) or split with `POST /portfolio/target_balance_allocation` (no GET for the current split — corrects earlier K-TR-15 wording) (K-TR-20). **Still not done:** no demo funds were added and no transfer/allocation call was made by this project; the redacted fixtures cannot confirm the account is funded or that shard-1 collateral exists (K-TR-OBS-16). **Manual demo-UI shard transfer failed 2026-09-08 (operator, official Kalshi demo web UI; K-TR-OBS-17..21):** the operator funded the demo account with $100 mock cash (UI showed Exchange 0 $100 / Exchange 1–3 $0), then a manual UI transfer **Exchange 0 → Exchange 1, $10** returned **"Transfer failed: Service unavailable, please try again later."** GET-only diagnosis at that time: `GET /portfolio/intra_exchange_instance_transfers` → `{"transfers": []}` (no record left); `GET /portfolio/target_balance_allocation` → `{"allocations": []}` (endpoint exists — supersedes the "no GET" note above; no standing split); `GET /exchange/status` → all 4 demo shards + top-level `trading_active` and `intra_exchange_transfers_active` = true, i.e. **Exchange 1 reports trading and transfers active**. Every documented, read-only-observable transfer precondition was satisfied; Kalshi documents no 503 / "Service unavailable" case for the transfer `POST`. **Cause is UNKNOWN** — not inferred to be insufficient funds, a provisioning failure, demo-service capacity, or any specific cause; the transfer was not retried and no `POST` to a transfer/allocation endpoint was issued by this project. **Manual demo-UI shard transfer SUCCEEDED 2026-09-08 (operator; K-TR-OBS-22..25):** the operator re-attempted the same `Exchange 0 → Exchange 1` $10 transfer and it completed (UI then showed Exchange 0 $90 / Exchange 1 $10). GET-only confirmation: `GET /portfolio/intra_exchange_instance_transfers` now returns **one** record with `status = "complete"` (was `[]`), `source`/`destination` both `event_contract`; the amount / id / timestamp / shard indices are redacted in the fixture, so the $90/$10 split rests on operator UI evidence only. `GET /exchange/status` and `GET /portfolio/target_balance_allocation` unchanged. So the earlier "Service unavailable" was **transient**, and a demo cross-shard `intra_exchange_instance_transfer` can **complete**. **Still untested:** whether an order on the now-funded shard 1 is accepted — `POST /portfolio/events/orders` was **not** re-attempted, so K-TR-OBS-12's `404 user_not_found` is unretested. | OBSERVED 2026-09-08 (K-TR-OBS-11 / K-TR-OBS-12; `docs/evidence/kalshi-demo/lifecycle/`) + read-only inspection probes (K-TR-OBS-14..16, `docs/evidence/kalshi-demo/shard-balance/`; K-TR-OBS-17..21, `docs/evidence/kalshi-demo/shard-transfer/`; K-TR-OBS-22..25, `docs/evidence/kalshi-demo/shard-funded/`) + manual demo-UI operator evidence + docs research (K-TR-14..21). Consequence: OBSERVED evidence for create-order request/response (K-TR-05/06), idempotency 409 (K-TR-07), order status (K-TR-08), fills (K-TR-09) and cancel (K-TR-10) stays **blocked** — the demo-funding + cross-shard-transfer remediation steps now work end-to-end up to *funded shard 1* (K-TR-OBS-22), but no order round-trip has been OBSERVED and the create-order `404` has not been re-probed since funding. A-038 remains blocking. No order, position, or fill was created. Extends, does not resolve, A-037 / D-023. | Yes |

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

## M2.1 notes (live book state)

- Work lives on `feat/live-book-state`, branched from `origin/main` (includes
  M1.6). See `docs/DECISIONS.md` D-014 and `docs/API_SOURCES.md` (K-WS-*,
  P-WS-*).
- A-027 (transport boundary + reconnect/resync manager implemented; networked
  socket still out), A-028 (Kalshi additive delta application — UNVERIFIED, not
  OBSERVED), A-029 (Kalshi feed has no market-state gate), A-030 (WS
  handshake/subscribe/frame formats are docs-only, no live OBSERVED handshake)
  were introduced here.
- `livebook.ws_auth` builds the handshake sign-string (`timestamp + "GET" +
  path`), the 3 auth headers, and the subscribe command for each venue
  (RSA-PSS/Ed25519 via an injected `Signer`); `livebook.credentials` holds
  redacted, env/config-injected keys (`KALSHI_API_KEY_ID` /
  `KALSHI_API_PRIVATE_KEY_PEM`, `POLYMARKET_US_KEY_ID` /
  `POLYMARKET_US_SECRET_KEY`); `livebook.transport.LiveBookConnection` drives
  feeds through connect → subscribe → pump → `mark_disconnected` →
  `BackoffPolicy` reconnect → REST `resync` → `HEALTHY`, all over injected
  `WebSocketTransport` / `SnapshotSource` / `clock` / `sleep`.
- `livebook.ws_transport.WebsocketsTransport` is the concrete transport over the
  `websockets` library — the project's **sole runtime dependency**
  (`websockets>=13`; pure Python, no transitive deps). It is the only module
  that does real network I/O or imports a third-party package. Tested against a
  local `websockets` loopback server; still **no authenticated connection to a
  real venue** (A-030) and **no `Signer` implementation** in the repo (the crypto
  step stays the caller's, keeping `cryptography` out of the tree).
- `LiveBookFeed.health()` is **fail-closed**: `trading_enabled` is `True` only
  for `HealthStatus.HEALTHY`. Uninitialized, stale (vs an injected `now`),
  disconnected, resyncing, desynced (sequence gap / negative-quantity delta /
  crossed-book result), and not-open all disable it, and
  `current_order_book(now)` returns `None` unless healthy.
- Kalshi `seq` gaps → `DESYNCED` until a fresh snapshot (`begin_resync()` then
  `apply_snapshot()`); duplicate/old `seq` are ignored. Polymarket US has no
  sequence — each `MARKET_DATA` frame is a full snapshot that replaces state,
  and a frame whose `transactTime` predates the last accepted one is dropped
  (at-least-once delivery, P-WS-04).
- The layer is pure/offline like the M1.5 engine: no wall-clock, exact
  `Decimal`, domain invariants enforced by building a real `OrderBook`. It does
  **not** resolve A-013 (which Polymarket book side) or the live-execution gate.

## M2.2 notes (persistent recorder)

- Work lives on `feat/live-book-state` (continues M2.1's branch); see
  `docs/DECISIONS.md` D-016.
- A-031 introduced here (naive-UTC-µs `TIMESTAMP` + string-`Decimal` storage).
- `prediction_market_arbitrage.recorder` is **write-only and append-only** —
  `Recorder` has record methods and no update/delete; DuckDB per-table
  `SEQUENCE` ids make ordered inserts deterministic. `session_id` and all
  timestamps are injected; no wall-clock, no random id.
- `duckdb>=1.0` is the second runtime dependency (after `websockets`).
- Order / fill / position / PnL have no domain model (M2.4 / M2.5), so the
  recorder owns `OrderEventRow` / `FillRow` / `PositionRow` / `PnlRow`. It
  records `OpportunityEvaluation` (M1.5) and `FeedHealth` (M2.1) directly and
  imports none of their behaviour; nothing in strategy/execution imports the
  recorder.
- No replay/query API, no paper broker, no risk manager, no UI — deferred
  (M2.3+). Real-money trading stays disabled.

## M2.3 notes (replay adapter)

- Work lives on `feat/replay-adapter` (branched from `origin/main` after M2.1
  and M2.2 merged); see `docs/DECISIONS.md` D-017.
- A-032 introduced here (replay synthesizes `Venue.name` / `Market.title` from
  ids; every strategy-relevant field is exact).
- `prediction_market_arbitrage.replay.ReplaySession` is **read-only** — no
  `record_*` / write / update / delete surface; `.open(path, read_only=True)` by
  default. It adds **no runtime dependency** (`duckdb` already present from
  M2.2).
- Determinism: every stream query is `ORDER BY` the recorder's monotonic `id`;
  `timeline()` merges streams on `(recorded_at, kind_rank, row_id)` — a fixed
  total order. Two identical recordings replay byte-identically (test).
- Timing is injected: `play(sleep=..., speed=...)` defaults to `no_sleep`
  (deterministic); `realtime(speed)` reproduces recorded wall-gaps.
- Live-book compatibility: `feed_book_snapshots({contract_id: LiveBookFeed})`
  hands a replayed book to `LiveBookFeed.apply_snapshot` unchanged
  (`sequence` / `market_state` are `None` — the recorder did not store them).
- Not implemented: paper broker, risk manager, dashboard/UI, live execution,
  new recorder features. Real-money trading stays disabled.

## M2.4 notes (deterministic paper broker)

- Work lives on `feat/paper-broker` (branched from `origin/main` after M2.3
  merged); see `docs/DECISIONS.md` D-018.
- A-033 introduced here (taker-only execution, `[0.0001, 0.9999]` slippage
  clamp, latency/cancel resolved by injected `timedelta`s).
- `prediction_market_arbitrage.paper_broker.PaperBroker` is **pure and
  deterministic** — no wall-clock, no RNG. The caller drives `advance(at=...,
  books=...)`; injected `fee_model` (reuses `arbitrage.FeeModel`), `slippage`
  (`NoSlippage` / `FixedOffsetSlippage` / `PerLevelSlippage`), latencies, min
  size, market TTL. Simulated time is monotonic non-decreasing (enforced).
- Covers every M2.4 ROADMAP item: latency, partial fills, available depth,
  rejections, slippage, cancellation, leg-risk simulation
  (`PaperBroker.leg_risk`).
- **Recorder integration, no redesign:** `Order.event_rows()` →
  `list[recorder.OrderEventRow]`, `Fill.to_row()` → `recorder.FillRow`,
  `PaperBroker.position(...)` → `recorder.PositionRow`. The broker imports those
  row types only; it does not import `Recorder`, and nothing in the recorder /
  replay imports the broker.
- Not implemented: live broker/API orders, risk manager, dashboard/UI,
  production live trading, automatic market pairing. Real-money stays disabled.

## M2.5 notes (deterministic risk manager)

- Work lives on `feat/risk-manager` (branched from `origin/main` after M2.4
  merged); see `docs/DECISIONS.md` D-019. **No new runtime dependency.**
- A-034 introduced here (fail-closed policy + `evaluate_order`'s unhedged-timer
  side effect + cost-basis exposure valuation as a deterministic fallback
  approximation, not a safe live bound).
- `prediction_market_arbitrage.risk.RiskManager` enforces `RiskLimits`
  (config-injected, Decimal/timedelta, `None` disables a check): max position,
  max exposure, max order size, min net edge/unit, max data age, max unhedged
  time, consecutive-error limit, max daily loss, kill switch. Returns a
  `RiskDecision(allowed, reasons, checks_run, as_of)` — **all** failing reasons,
  not just the first.
- Consumes the earlier milestones' objects unchanged: M1.5
  `OpportunityEvaluation`, M2.1 `FeedHealth`, M2.4 `OrderRequest` /
  `LegRiskSnapshot` / `recorder.PositionRow`. Imports those types only; no
  strategy / execution code imports the risk manager.
- Deterministic: every method takes an injected tz-aware `now`; the only mutable
  state (kill switch, error streak, per-UTC-day realized-PnL ledger, unhedged
  timers) lives in `RiskState`. Naive datetime → `RiskError`.
- Not implemented: live broker/API orders, dashboard/UI, live execution, new
  strategy logic. Real-money trading stays disabled.

## M3.1 notes (operational dashboard)

- Work lives on `feat/dashboard` (branched from `origin/main` after M2.5
  merged, PR #13); see `docs/DECISIONS.md` D-020. **No new runtime dependency.**
- A-035 introduced here (read-only deterministic projection; WS state derived
  from `FeedHealth.status`; alert severity policy; A-034 mark fallback reused
  for displayed exposure).
- `prediction_market_arbitrage.dashboard.build_dashboard(*, now, feeds?,
  registry?, opportunities?, orders?, positions?, marks?, pnl?, leg_risk?,
  risk?, last_risk_decision?, max_data_age?)` → immutable `DashboardView`
  (`feeds`, `pairs`, `opportunities`, `orders`, `fills`, `positions`, `pnl`,
  `leg_risk`, `risk`, `alerts`, `worst_data_age`, `.healthy`).
  `render_text(view)` → deterministic sectioned plain text, unhealthy / stale
  rows tokenised `[ALERT]` / `[WARN]` / `[STALE]`.
- Consumes earlier milestones' objects unchanged; imports those types only;
  nothing imports `dashboard`. No wall-clock (naive `now` → `DashboardError`),
  no socket, no recorder / DuckDB read, no order submission.
- Not implemented: live-updating TUI / web server, alert escalation / paging,
  persistence read-back, live broker, live execution, strategy changes,
  failure testing (M3.2), performance report (M3.3). Real-money disabled.

## M3.2 notes (deterministic failure testing)

- Work lives on `feat/failure-testing` (branched from `origin/main` after M3.1
  #14 merged); see `docs/DECISIONS.md` D-021. **Tests only — no production
  change, no new dependency.**
- `tests/test_failure_scenarios.py` covers all nine `docs/ROADMAP.md` M3.2
  categories by driving existing injected-effect seams with modelled failures
  and asserting fail-closed behaviour + designed recovery. No new assumption is
  introduced.
- **No real defect was discovered.** Every fail-closed and recovery path
  behaved as designed under the modelled inputs. If a later run surfaces a real
  defect it must be recorded here as a defect entry, separately from the
  modelled scenario.
- These scenarios are **not** evidence about real venue behaviour. Live venue
  semantics remain unverified and continue to block real-money use: A-001 /
  A-002 / A-003 (equivalence, settlement, fees), A-012 / A-013 / A-015 / A-016
  (Polymarket US book side, routing identifiers, titles), A-028 / A-030
  (WebSocket auth + frame formats, never run against a live venue), A-004 family
  (price tick / fee schedule). The disconnect/reconnect scenario exercises the
  M2.1 manager only — no concrete networked `WebSocketTransport` exists.

## M3.3 notes (paper-performance report)

- Work lives on `feat/paper-performance-report` (branched from `origin/main`
  after M3.2 #15 merged); see `docs/DECISIONS.md` D-022. **No new runtime
  dependency.**
- A-036 introduced here (pure read-only projection via `ReplaySession`; derived
  opportunity duration; leg-risk not persisted → unavailable; missing metric =
  `None`, never `0`).
- `prediction_market_arbitrage.perf_report.build_report(session, *,
  pnl_scope="portfolio", pnl_scope_id=None)` → immutable `PerfReport`
  (`opportunities`, `opportunity_duration`, `trades`, `depth`, `pnl`,
  `leg_risk`, `stream_counts`, `unavailable`). `render_text(report)` →
  deterministic sectioned plain text that prints `n/a` (+ reason) vs a real
  number.
- Consumes the M2.3 replay `Recorded*` value objects unchanged; imports the
  replay / recorder types only; nothing imports `perf_report`. `pnl_scope` bad
  value → `PerfReportError`.
- Not implemented: leg-risk persistence + reporting (no recorder table),
  live broker, dashboard changes, strategy changes, real-money activation.
  Report covers **paper** results only.

## M3.4 notes (live-broker interface boundary)

- Work lives on `feat/live-broker-interface` (branched from `origin/main` after
  M3.3 #16 merged); see `docs/DECISIONS.md` D-023. **No new runtime
  dependency.**
- A-037 introduced here (interface boundary only; both venues explicitly
  unsupported for lack of primary evidence; `LIVE_TRADING` off by default and
  phrase-armed; local-only idempotency; isolated redacted trading credentials).
- `prediction_market_arbitrage.live_broker`: `LiveBroker` ABC (`submit_order` /
  `cancel_order` / `get_order` / `get_positions`) over venue-neutral value
  objects; `LiveTradingGate` (frozen, default disabled, arm phrase
  `I_UNDERSTAND_THIS_PLACES_REAL_ORDERS`, `PMA_LIVE_TRADING` env); constant
  `LIVE_TRADING_ENABLED = False`; `IdempotencyGuard`;
  `Kalshi/PolymarketUsTradingCredentials` (+ `*_from_env`);
  `KalshiLiveBroker` / `PolymarketUsLiveBroker` — every op raises
  `UnsupportedLiveOperationError`.
- Every public `LiveBroker` method enforces, in order: validation + tz-aware
  `now` + venue match → gate check → (submit only) idempotency register →
  subclass `_do_*` hook. The gate / dedupe cannot be bypassed by a subclass.
- No venue request is built or sent — no guessed endpoint, path, body, or field
  name. Kalshi trading and Polymarket US trading (incl. A-015 slug routing)
  stay UNVERIFIED and block real-money use.
- Not implemented: real venue calls, automatic activation, strategy / dashboard
  / risk changes, real-money order submission (including in tests).

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
