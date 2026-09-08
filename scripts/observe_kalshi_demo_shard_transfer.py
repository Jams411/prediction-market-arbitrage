"""Authenticated **read-only** inspection of Kalshi *demo* exchange-instance
transfer state, run after a **manual demo-UI** ``Exchange 0 -> Exchange 1``
transfer of $10 failed with "Transfer failed: Service unavailable, please try
again later." (see ``docs/API_SOURCES.md`` / A-038).

GET-only. This script **cannot** initiate a transfer, allocate collateral, or
place an order. It does not call ``POST /portfolio/intra_exchange_instance_transfer``
or ``POST /portfolio/target_balance_allocation``.

Probes (all GET):
- ``/portfolio/balance``                          — total portfolio balance
- ``/portfolio/balance?exchange_index=0``         — Default shard
- ``/portfolio/balance?exchange_index=1``         — Demo shard 1 (transfer dest)
- ``/exchange/status``                            — public; per-index active /
  trading_active / intra_exchange_transfers_active flags
- ``/portfolio/intra_exchange_instance_transfers`` — documented transfer-history
  list (API changelog 2026-08-27); shows whether the failed UI attempt left any
  record and, if so, its ``status`` (``pending`` | ``complete``)
- ``/portfolio/target_balance_allocation``        — documented GET for the
  current standing allocation split (API changelog 2026-08-27)

Credentials, signing, and body sanitisation are reused from
:mod:`observe_kalshi_demo`; the GET helper is reused from
:mod:`observe_kalshi_demo_shard_balance` (signs the path only, query stays on
the URL). Account-scoped bodies pass through :func:`observe_kalshi_demo.sanitise_body`
(D-024 fail-safe allowlist); the public ``/exchange/status`` body is kept
verbatim (non-account exchange-wide state only).

Run manually:  ``python scripts/observe_kalshi_demo_shard_transfer.py``
"""

from __future__ import annotations

import json
import sys
from typing import Any

import observe_kalshi_demo as obs
import observe_kalshi_demo_shard_balance as shbal

OUT_DIR = obs.OUT_DIR / "shard-transfer"


def observe() -> int:
    key_id = obs.keychain_key_id()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # (name, path, query, key_id_or_None, keep_body_verbatim)
    plan: list[tuple[str, str, dict[str, Any] | None, str | None, bool]] = [
        ("exchange_status", "/exchange/status", None, None, True),
        ("balance_all", "/portfolio/balance", None, key_id, False),
        ("balance_exchange_index_0", "/portfolio/balance", {"exchange_index": 0}, key_id, False),
        ("balance_exchange_index_1", "/portfolio/balance", {"exchange_index": 1}, key_id, False),
        (
            "intra_exchange_instance_transfers",
            "/portfolio/intra_exchange_instance_transfers",
            None,
            key_id,
            False,
        ),
        (
            "target_balance_allocation",
            "/portfolio/target_balance_allocation",
            None,
            key_id,
            False,
        ),
    ]

    summary: list[dict[str, Any]] = []
    for name, path, query, kid, verbatim in plan:
        result = shbal._request(path, query, kid)
        body = result["body"] if verbatim else obs.sanitise_body(result["body"])
        clean = {
            "request": result["request"],
            "status": result["status"],
            "headers": result["headers"],
            "body": body,
        }
        (OUT_DIR / f"{name}.json").write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")
        shape = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
        summary.append(
            {
                "name": name,
                "path": clean["request"]["path"],
                "query": clean["request"]["query"],
                "status": clean["status"],
                "body_keys": shape,
            }
        )
        print(f"  {name:34s} {result['status']:>3}  {clean['request']['path']} {query or ''}")

    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {len(plan)} fixtures + SUMMARY.json to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(observe())
