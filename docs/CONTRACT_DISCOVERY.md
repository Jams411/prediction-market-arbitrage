# Contract-equivalence discovery

`scripts/discover_contract_pairs.py` is a bounded, deterministic triage tool for
finding plausible Kalshi / Polymarket US contract pairs. It reads only public
market metadata and rules through the repository's existing GET-only clients.
It does not request credentials, fetch account data, inspect prices, or execute
orders.

Run a one-page observation with:

```bash
.venv/bin/python scripts/discover_contract_pairs.py \
  --kalshi-pages 1 --polymarket-pages 1 --page-size 100 --top 20
```

Page counts are capped at 10 and page size at 100. Output is compact JSON. Raw
API responses are not emitted or persisted.

## What the ranking means

`verification_priority` is deterministic review triage, not an equivalence
probability or approval score. Candidate generation uses normalized lexical
overlap only as an initial signal. Priority then rewards exact matches and
strongly penalizes material mismatches across:

- underlying event/entity and proposition;
- participant/outcome and YES/NO mapping;
- threshold, inclusivity, and measurement unit;
- event window, close conditions, and settlement backstop;
- resolution source;
- cancellation/postponement, multiple-winner, and void/refund/fair-market
  treatment.

Each field is reported as `MATCH`, `MISMATCH`, `UNKNOWN`, or
`NOT_APPLICABLE`. Missing evidence remains `UNKNOWN`; it is never promoted to a
match. Exact `Decimal` values are used for thresholds.

## Hard boundary

Every result states:

> UNVERIFIED — human/primary-source verification required

Discovery results are a separate model, are not registry records, and are not
written to `registry/data/market_pairs.toml`. Only a human-authored registry
record that satisfies the full checklist in `docs/MARKET_PAIRING.md` can become
strategy-eligible. Discovery output must never be passed to arbitrage or
execution code as a substitute for that gate.
