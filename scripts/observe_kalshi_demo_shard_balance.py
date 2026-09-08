"""Authenticated **read-only** observation of Kalshi *demo* balance, scoped
**per exchange shard**, plus the public per-shard exchange status.

Purpose: for A-038, directly confirm (OBSERVED, not docs-only) how a
programmatic trader inspects (a) total demo balance, (b) balance scoped to one
``exchange_index`` via the documented ``?exchange_index=N`` query parameter
(K-TR-15 / Get Balance API reference), and (c) per-shard trading / transfer
status via ``GET /exchange/status``. GET-only. Nothing here can fund an
account, move collateral, or submit / cancel / modify an order.

Not part of the shipped package. Run manually:

    python scripts/observe_kalshi_demo_shard_balance.py

Credentials, signing and body sanitisation are reused verbatim from
:mod:`observe_kalshi_demo` (Keychain ``pma-kalshi-demo-api-key-id`` +
``~/.config/pma/kalshi-demo-private-key.pem``; RSA-PSS over
``timestamp_ms + METHOD + path`` with the **query string excluded** from the
signed message; D-024 fail-safe allowlist for the response body).

``GET /exchange/status`` is a public, unauthenticated endpoint returning only
non-account exchange-wide state (shard active / trading / transfer flags and
their public descriptions); its body is recorded verbatim so the shard-index →
status mapping is usable as evidence. Every account-scoped balance response is
still run through :func:`observe_kalshi_demo.sanitise_body`, so no balance,
portfolio value, id or timestamp is persisted.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

import observe_kalshi_demo as obs

DEMO_BASE_URL = obs.DEMO_BASE_URL
SIGN_PATH_PREFIX = obs.SIGN_PATH_PREFIX
OUT_DIR = obs.OUT_DIR / "shard-balance"
TIMEOUT = obs.TIMEOUT
USER_AGENT = (
    "prediction-market-arbitrage/0.1 "
    "(read-only DEMO shard-balance observation; +https://github.com/Jams411)"
)

# Shard indexes to scope the balance query to. 0 = catch-all default; 1 =
# Exotics/Combos, the shard the `…-SHARD1-…` demo probe market auto-routes to
# (K-TR-14); 2 = Crypto/Commodities; 3 = select Sports. Range per the API
# reference is the same 0..100 as the transfer endpoints.
SHARD_INDEXES = (0, 1, 2, 3)


def _request(path: str, query: dict[str, Any] | None, key_id: str | None) -> dict[str, Any]:
    """One GET. ``query`` is sent on the URL but **excluded** from the signed
    message (Kalshi signs the path only). ``key_id=None`` sends no auth headers
    (for the public ``/exchange/status`` endpoint).
    """
    qs = f"?{urlencode(query)}" if query else ""
    url = f"{DEMO_BASE_URL}{path}{qs}"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if key_id is not None:
        ts = str(int(time.time() * 1000))
        signature = obs.sign(f"{ts}GET{SIGN_PATH_PREFIX}{path}")
        headers |= {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status, resp_headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        status, resp_headers, raw = exc.code, exc.headers, exc.read()

    body: Any
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = {"<non-json-body-bytes>": len(raw)}

    return {
        "request": {"method": "GET", "path": path, "query": query or {}},
        "status": status,
        "headers": {
            k.lower(): v
            for k, v in resp_headers.items()
            if k.lower() in obs.HEADERS_OF_INTEREST
        },
        "body": body,
    }


def observe() -> int:
    key_id = obs.keychain_key_id()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    probes: list[tuple[str, dict[str, Any], bool]] = []

    # 1. Public per-shard exchange status (no auth). Body kept verbatim.
    probes.append(("exchange_status", _request("/exchange/status", None, None), True))

    # 2. Total balance (no scope) — includes `balance_breakdown[]` per shard.
    probes.append(("balance_all", _request("/portfolio/balance", None, key_id), False))

    # 3. Balance scoped to each shard via the documented `?exchange_index=N`.
    for idx in SHARD_INDEXES:
        probes.append(
            (
                f"balance_exchange_index_{idx}",
                _request("/portfolio/balance", {"exchange_index": idx}, key_id),
                False,
            )
        )

    summary: list[dict[str, Any]] = []
    for name, result, verbatim_body in probes:
        body = result["body"] if verbatim_body else obs.sanitise_body(result["body"])
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
        q = clean["request"]["query"]
        print(f"  {name:28s} {result['status']:>3}  {clean['request']['path']} {q or ''}")

    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {len(probes)} fixtures + SUMMARY.json to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(observe())
