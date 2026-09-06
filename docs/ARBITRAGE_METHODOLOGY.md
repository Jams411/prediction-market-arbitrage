# Arbitrage Methodology

How the deterministic engine (Milestone M1.5,
`src/prediction_market_arbitrage/arbitrage/`) decides whether a verified pair
represents a locked-in edge — and the many things a positive number here does
**not** guarantee.

---

## 0. Scope of M1.5

The engine implements **one** arbitrage model: the **complementary-outcome
buy/buy**. It only evaluates registry records whose `relation` is
`COMPLEMENTARY` — buy one unit of each side, let the $1 settlement cover the
combined cost.

`IDENTICAL` pairs (the same contract, priced differently on the two venues) are
also a real arbitrage in principle — but capturing it means *selling* / shorting
the richer venue's contract, which requires position and execution semantics
this buy/buy calculator does not have. The engine therefore returns **no
opportunity** for `IDENTICAL` records, with a reason. This is a limitation of
the current engine, **not** a claim that identical contracts cannot be
arbitraged; support is deferred to execution/broker work.

Also **not** in M1.5: same-market complete-set arbitrage (the registry's
`MarketPairRecord` is cross-venue by construction), live trading, order
submission, positions, and any use of wall-clock time.

## 1. Why buying complementary outcomes below total payout is arbitrage

Two contracts are **complementary** when, together, they pay exactly **1 unit**
at settlement regardless of how the event resolves: exactly one of them settles
to 1, the other to 0. (The registry records this as
`relation = "COMPLEMENTARY"`; see `docs/MARKET_PAIRING.md`.)

If you can *buy* one unit of each side for a combined cost below 1, you hold a
position that is worth exactly 1 at settlement no matter what happens. The
difference is locked in the moment both fills complete:

    gross_edge_per_unit = 1 - (ask_price_leg_A + ask_price_leg_B)

Example: leg A asks 0.45, leg B asks 0.52. Combined cost 0.97, settlement value
1.00, gross edge 0.03 per matched set. This is direction-free: you are not
betting on the event, only on the two prices summing to less than the payout.

## 2. Gross edge vs. net edge

Gross edge ignores the frictions of actually acquiring the position. The engine
subtracts two **explicit** costs:

    net_edge_per_unit
      = 1
        - acquisition_cost_leg_A      (depth-weighted, per unit)
        - acquisition_cost_leg_B      (depth-weighted, per unit)
        - fees_per_unit               (from the injected FeeModel)
        - execution_buffer_per_unit   (an explicit Decimal input)

    expected_total_profit = net_edge_per_unit * executable_quantity

An opportunity exists **only if `net_edge > 0`**. Exact break-even
(`net_edge == 0`) is *not* an opportunity — there is no margin to absorb
anything that goes wrong. Every value is an exact `Decimal`; the engine does not
round internally.

## 3. Why depth matters

An order book is a stack of price levels, each with a limited quantity. The
first level's price only applies to the first slice of your order; once you want
more than that level holds, you "walk" up the book and pay worse prices.

    Venue A asks:  0.40 x 5,  0.42 x 10
    Venue B asks:  0.50 x 8,  0.51 x 10

Buying 8 units on A costs `5*0.40 + 3*0.42 = 3.26`, not `8*0.40 = 3.20`. The
engine walks every level it needs and reports each slice, so the acquisition
cost reflects what you would actually pay.

The **maximum executable quantity** is limited by the smallest of: leg A ask
depth, leg B ask depth, any configured `max_quantity`, and the caller's
requested quantity. The engine then evaluates net economics **at that size**. It
does not search for a smaller partial fill that might still be profitable —
without a verified venue tick/lot size the "largest profitable quantity" is an
open bound, and choosing an arbitrary smaller size would be inventing an
execution policy. Partial-fill sizing is deferred to the paper broker (M2.4).

## 4. Why fees matter

Fees are subtracted per unit and can flip a thin edge negative. Example: gross
edge 0.03, a synthetic 0.01/unit fee on each leg (0.02 total) plus a 0.01/unit
execution buffer → net edge 0.00 → no opportunity.

The engine **never hardcodes a real venue fee schedule.** Kalshi and Polymarket
US fee formulas are a separate evidence task (A-022). M1.5 takes an injected
`FeeModel`; the shipped models are `ZeroFeeModel` (baseline) and
`FixedPerUnitFeeModel` (synthetic, for tests). Using a wrong fee number would
produce confident, wrong edges — so the number must come from verified evidence,
supplied by the caller.

## 5. Why top-of-book can be misleading

Quoting only the best ask makes a market look deeper and cheaper than it is. A
0.03 edge on the first 2 units can be a 0.00 edge once you size up to 50. Any
sizing or profit figure computed from top-of-book alone is unreliable; the
engine always walks real depth for the quantity it evaluates.

## 6. Why contract equivalence is a separate prerequisite

The engine assumes the two books it is given are genuinely the two sides of one
proposition. It does **not** check that — deciding equivalence is the M1.4
registry's job, done by a human against both venues' primary settlement rules.

The engine will only evaluate a `MarketPairRecord` whose status is `VERIFIED`
(reached through `MarketPairRegistry.eligible()` or a direct status check that
cannot be bypassed). A `DRAFT` / `REVIEW_REQUIRED` / `REJECTED` / `SUSPENDED`
pair raises. If the equivalence is wrong, a "locked" position is actually a
leveraged directional bet — the arithmetic being correct does not save you.

## 7. Positive theoretical edge ≠ guaranteed realized profit

A positive `net_edge` from this engine is a **necessary, not sufficient**
condition for profit. It is computed from a point-in-time snapshot under
assumptions that real execution can violate:

- **Leg risk / one-sided fills.** You might fill leg A and then fail to fill leg
  B (price moved, liquidity vanished), leaving an unhedged directional position.
- **Latency and staleness.** By the time an order reaches a venue the quoted
  depth may be gone. The engine's optional freshness checks (`max_book_age`,
  `max_cross_book_skew`, against an **injected** evaluation time) reject
  obviously stale inputs but cannot model in-flight decay.
- **Fees not yet verified.** See §4 / A-022.
- **Settlement edge cases.** Even a `VERIFIED` pair can hit a rare void/tie path
  a reviewer judged immaterial.
- **Withdrawals, halts, order rejections, partial fills, minimum sizes** — all
  execution concerns.

Modelling those belongs to the **paper broker and risk work (M2.4 / M2.5)**, not
to this pure calculator. **No result from this engine, and no synthetic test in
this repository, is a claim of real-world profitability.**

## 8. Why the engine is isolated

The engine is deliberately separated from four neighbours (D-012):

| Separated from | Why |
|---|---|
| **Venue adapters** | The engine takes already-normalized `OrderBook`s. It never calls a venue API, so its behaviour does not depend on network, auth, or a venue being up. Adapter bugs stay in the adapter layer. |
| **Market-pair verification** | Equivalence is a human risk judgement (M1.4). Keeping it out of the engine means a code change to the math can never quietly loosen which pairs are considered "the same bet". |
| **Execution / broker logic** | The engine computes; it does not place, size-to-fill, hedge, or hold positions. Leg risk and fill realism live where they can be simulated (M2.4). |
| **Fee-source verification** | Fee formulas are evidence, gathered and verified separately (A-022). Injecting the `FeeModel` means the engine is correct regardless of which venue's schedule is (or isn't) known yet. |

The payoff: the engine is a **pure function** of (verified record, two books,
config, evaluation time). Given the same inputs it always returns the same
`OpportunityEvaluation`. That makes it deterministic, replayable against recorded
books, and exhaustively testable with exact `Decimal` cases — none of which is
possible if strategy math is entangled with I/O, human review, or execution.
