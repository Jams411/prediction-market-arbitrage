# Single-contract payout conservation — local audit, 2026-09-12

Agent: Codex
Model: GPT-6
Reviewer: pending
Classification: **INCONCLUSIVE**

Representative: `KXCPI-26SEP-T0.2` only. Reuse the prior OBSERVED contract
inventory; no current market-status claim or metadata refresh. YES means the
September 2026 signed one-month, one-decimal seasonally adjusted BLS CPI-U change
exceeds 0.2%; equality is NO. Notional settlement value is $1.

## Primary sources

- [CPI terms](https://assets.kalshi.com/contract_terms/CPI.pdf), pp. 1–2:
  Underlying, Payout Criterion, fallback and Contingencies. Previously downloaded
  PDF hash remains `2317b1d8e823082b409f6ff3415fb135804d9682681f9f92f640b3681b29a872`.
- [Joint exchange/clearing rulebook filing, May 2, 2025](https://www.cftc.gov/sites/default/files/filings/orgrules/25/05/rules05022520607.pdf):
  exchange v1.17 and Klear v1.2 redlined filing; historical primary evidence,
  not verified current consolidated rules. Exchange 5.10, 5.11, 6.1(d), 6.3,
  7.1–7.2; Klear 6.1(F), 6.2(C–E), 6.9 (PDF pp. 46–47, 53–56, 121–122, 125).
- [Current settlement documentation](https://docs.kalshi.com/getting_started/market_settlement)
  and [settlement rounding](https://docs.kalshi.com/getting_started/fee_rounding),
  accessed 2026-09-12. Documentation only; no account endpoint was called.

The regulatory page exposed no rulebook links through web extraction; a direct
public-page download returned HTTP 429. The earlier consolidated-rulebook
retrieval limitation remains. No claim that every current amendment was reviewed.
The CPI PDF's old contingency numbering must not be silently mapped onto newer
numbering as proof of current legal precedence.

## Definitions and state matrix

Y,N denote gross contractual entitlements for one unit on each side, before fees,
not two separately held positions in the same account. C denotes posted cash.

| State | Gross identity / finding |
|---|---|
| Ordinary X > 0.2% | Y=1, N=0; sum=1. |
| Ordinary X <= 0.2%, including equality | Y=0, N=1; sum=1. |
| Missing monthly release, computable CPI formula fallback | A scalar X is substituted; the same binary split sums to 1. |
| Delayed/source-replaced resolution producing a determinate scalar | Same algebra, conditional on final binary treatment. |
| Post-expiration BLS revision | Excluded by CPI terms; ordinary split unchanged. |
| Complementary fair-value allocation q and 1-q | Sum=1 algebraically; exchange example supports this treatment. Universal constraint unproved. |
| Underlying and fallback cannot determine a value; committee allocation | Fair allocation authorized; no exhaustive current-rule proof that every allocation must sum to 1. |
| Unfilled-order cancellation | No acquired contract; identity inapplicable. |
| Clearing rejection | Void from inception under exchange 6.1(d); not a zero-paying valid contract. |
| Trade cancellation/adjustment | Exchange 5.10 permits cancellation/adjustment; 5.11 reverses specified invalid trades at their original price. No fixed unit refund inferred. |
| Review/correction | Review can change determination; Klear 6.9 allows error corrections after transfers. Reconciled final entitlement, not cumulative provisional credits, is relevant. |
| Netting/offset | Klear permits offset and collateral release; current docs settle net positions only. Do not count released collateral again. |
| Sub-cent scalar settlement | Gross identity and posted cash differ; rounding fees can reduce cash. |

For ordinary states, Y=1[X>0.2], N=1-1[X>0.2], hence Y+N=1.
For a stipulated complementary allocation, q+(1-q)=1. That mathematical identity
does not supply missing legal conditions. Neither discretion nor a voided trade
proves a counterexample for a valid contract's gross entitlements. Conversely,
collateralization and the example alone do not establish every-state conservation.

Current rounding documentation explicitly rounds posted settlement cash down to
cents and records the remainder as a fee. As a synthetic accounting illustration,
gross q=0.597 and 1-q=0.403 on separately posted one-unit entitlements gives
0.59+0.40=0.99 cash and 0.01 combined fees. This is not an observed CPI settlement
or a claim both sides remain open in one account. Gross cash plus fees conserves
the stipulated dollar; cash alone does not. No market price was fetched or used.

## Classification and structural implication

**INCONCLUSIVE** for unconditional gross conservation across every requested state.
The precise blocker is unresolvable-data discretionary allocation plus unverified
current cancellation/correction constraints. Ordinary conservation is supported;
no authorized gross payout vector with sum different from one was established.
An unconditional statement about net posted cash is additionally contradicted by
documented rounding. No deterministic all-state primitive is approved by this audit.

Next structural direction: **same-contract immediate offset/collateral-release
accounting**, independent of waiting for event settlement. One bounded rules-only
audit should determine whether opposite filled interests extinguish exposure and
create an irrevocable, exactly quantified credit after fees and trade-bust rules.
Use this same representative only; no prices, orders or implementation. Stop if
current primary clearing/offset rules cannot be established rather than assuming
another settlement identity.

## Validation and local scope

Synthetic Decimal checks verify ordinary and stipulated complementary algebra and
rounding arithmetic only. Source locators inspected; `git diff --check` passed.
No production tests for documentation only. Prior local work preserved; no commit,
push or PR. No authentication, books/prices, orders, execution, registry/policy/risk,
Demo-cap or LIVE_TRADING changes. No comparison with other contracts or events.
