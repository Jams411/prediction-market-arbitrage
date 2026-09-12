# Same-contract immediate offset audit — 2026-09-12

Agent: Codex
Model: GPT-6
Reviewer: pending
Classification: **NO_STRUCTURAL_ARBITRAGE**

Scope: the proposed immediate same-contract two-sided acquisition primitive on
Kalshi's normally functioning continuous order book. This is not a claim that
profitable round trips, market making, or all other strategies are impossible.
Retain `KXCPI-26SEP-T0.2` as representative; no new contract or market-data request.

## Mechanics and primary evidence

[Official orderbook explanation](https://docs.kalshi.com/getting_started/orderbook_responses):
YES bid B_Y is NO ask 1-B_Y; NO bid B_N is YES ask 1-B_N, with the same size.
These are reciprocal quotes, not independent outcome markets. Buying both asks
costs 2-B_Y-B_N per unit, not B_Y+B_N. In particular, two bids summing below one
are not two available purchase prices.

[Official buying/selling equivalence](https://help.kalshi.com/en/articles/13823806-buying-yes-vs-selling-no)
states that buying NO and selling YES are equivalent backend actions. Equal
opposite fills close/net exposure; no separately exercised token-merge operation
is established or needed. Unequal fills leave a residual position.
[V2 order documentation](https://docs.kalshi.com/api-reference/orders/create-order-v2)
uses YES-side prices for both bid and ask. Convert that convention before applying
the equations here, which use each outcome's acquisition cost.

[Joint exchange/Klear filing](https://www.cftc.gov/sites/default/files/filings/orgrules/25/05/rules05022520607.pdf),
historical May 2025 primary evidence: exchange 5.8–5.9 match by price/time and
execute marketable orders against opposite offers. Klear 6.1(F) permits offset
of identical terms, 6.2(E) releases decreased committed collateral. Exchange 5.10
permits trade cancellation/adjustment; 5.11 reverses specified invalid trades.
Klear 6.9 permits error corrections. Thus completed offset removes event exposure,
but receipts are not an unconditional trade-bust-proof guarantee. Current
consolidated rulebook coverage remains unverified, as recorded in the prior audit.

## Exact profitability condition

For equal filled quantity Q, outcome acquisition prices y_j and n_k, define
C_Y=sum(Q_j*y_j), C_N=sum(Q_k*n_k). Let F_Y,F_N be actual net trading charges,
including rounding minus earned rebates; H is any additional applicable charge.
For valid fully offset fills:

    profit = Q - C_Y - C_N - F_Y - F_N - H
    profit > 0 iff C_Y + C_N + F_Y + F_N + H < Q

For flat fill prices: y+n+(F_Y+F_N+H)/Q < 1.
The Q is an accounting identity for closing the exposure, not another settlement
credit on top of released collateral. Final outcome does not enter this equation
once both equal quantities are validly filled and remain effective.

For immediate best-quote taker fills, let A_Y=1-B_N. Then:

    y+n = A_Y + (1-B_Y) = 1 + (A_Y-B_Y)
    profit = -Q*(A_Y-B_Y) - F_Y - F_N - H

On an uncrossed book A_Y>=B_Y. Nonnegative charges preclude positive profit.
Depth worsens acquisition costs. A locked book yields at best zero before fees.
A putative crossed snapshot is not proof of two simultaneously executable fills:
normal matching consumes crossings; stale/asynchronous data or market constraints
must be resolved. Self-matching is not a profit source.

## Fees, rounding and execution

[July 7, 2026 fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
Trading Fees/Maker Fees and KXCPI row: raw taker fee is M*0.07*Q*p*(1-p);
maker fee is M*0.0175*Q*p*(1-p). KXCPI lists M=1 for both. Both filled legs
incur their applicable charges; closing is not a fee exemption. Unfilled resting
order cancellation has no fee. FCM charges may differ. No target override was
queried; these are published schedule parameters, not account-specific verification.

[Current rounding documentation](https://docs.kalshi.com/getting_started/fee_rounding)
specifies six-decimal model-fee ceiling, balance-grid rounding and per-order
accumulated rebates. Direct-member grid is 0.0001 dollars; non-direct grid is 0.01.
Net fee is nonnegative. Use actual applicable precision and fill/order accounting,
not an unconditional cent ceiling or a rebate assumed in advance. The PDF's
centicent shorthand and example tables do not fully specify every account path;
an exact account-level fee implementation would require separate reconciliation.

Maker fills may eventually satisfy the inequality, but queues, adverse selection,
partial fills and price movement make completion uncertain. Single-order FOK/IOC
options in V2 do not establish atomic execution of two independent orders.
One-leg cancellation/bust can restore directional exposure or reverse profit.
No guaranteed positive-profit condition exists before execution merely from
posting complementary orders. Conditional realized profit is not deterministic
ex-ante structural arbitrage.

## Conclusion and next milestone

NO_STRUCTURAL_ARBITRAGE for the proposed primitive: the blocker is one reciprocal
book, nonnegative spread/fees and non-atomic completion, not final settlement.
No arbitrage detector is warranted by this audit. No observable-input specification
is promoted to an implementation requirement.

Recommend **reassessing project direction**, not another same-venue identity search.
One local decision memo should use existing evidence to choose between retaining
the project as market-data/replay infrastructure and explicitly undertaking a
non-guaranteed market-making research project with measured inventory/adverse-
selection risk. No implementation, new market scan or risk-policy change implied.

Validation: synthetic Decimal identities and nonpositive immediate-round-trip
profit checked; `git diff --check` passed. No live books/prices, authentication,
orders, execution, registry/policy/risk, Demo-cap or LIVE_TRADING changes.
Prior local work preserved; no commit, push or PR. Documentation only.
