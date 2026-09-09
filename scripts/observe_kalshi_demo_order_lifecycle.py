"""Controlled **Kalshi DEMO** order-lifecycle observation (real-money-readiness).

Purpose: move the Kalshi trading rows in ``docs/API_SOURCES.md`` (K-TR-06 /
K-TR-07 / K-TR-08 / K-TR-09 / K-TR-10) from ``VERIFIED (docs)`` to ``OBSERVED``
by exercising **one** minimal order against the Kalshi **demo** environment and
capturing the real submit / status / open-order / cancel / positions / fills
response shapes.

Everything here is DEMO:

- Base URL is hard-pinned to ``external-api.demo.kalshi.co`` (asserted at run).
- Demo API key id from macOS Keychain ``pma-kalshi-demo-api-key-id``; demo RSA
  key from ``~/.config/pma/kalshi-demo-private-key.pem`` — same access pattern
  as :mod:`observe_kalshi_demo`. Never printed, logged, persisted, or committed.
- Production Kalshi is never called. No Polymarket US. ``LIVE_TRADING`` is not
  read or set.

Safety design:

- The order is a **1-contract** ``yes`` bid at **$0.01** with ``post_only`` on a
  market whose order book is **empty** — it cannot cross, so it rests and is
  then cancelled. Max notional at risk: $0.01 of demo funny-money.
- The script always tries to cancel any ``order_id`` it received, even on error
  (shard-routed ``DELETE`` with ``market_ticker``), and reports loudly if an
  order is left resting.
- At most two create attempts (documented V2 path, then legacy path). It does
  **not** iterate on schema guesses — an unexpected rejection is captured and
  the run stops.
- No deliberate fill. Order size is never increased.

Sanitisation: responses go through :func:`observe_kalshi_demo.sanitise_body`
(D-024 fail-safe allowlist). Request bodies are persisted with only the known
non-sensitive schema fields kept and ``client_order_id`` replaced by a
placeholder.

Run manually:  ``python scripts/observe_kalshi_demo_order_lifecycle.py [SUBDIR]``
(``SUBDIR`` = evidence subdirectory under ``docs/evidence/kalshi-demo/``;
default ``lifecycle``).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import observe_kalshi_demo as obs

DEMO_BASE_URL = obs.DEMO_BASE_URL
SIGN_PATH_PREFIX = obs.SIGN_PATH_PREFIX
OUT_DIR = obs.OUT_DIR / "lifecycle"
TIMEOUT = obs.TIMEOUT
USER_AGENT = "prediction-market-arbitrage/0.1 (DEMO order-lifecycle observation; +https://github.com/Jams411)"

# The demo market to rest the probe order on. Selected via the verified
# read-only market-data client (KalshiClient, demo base): an ``active`` binary
# market with a completely empty order book, so a $0.01 bid cannot match.
MARKET_TICKER = "KXMVECROSSCATEGORY-SHARD1-S2026030E5B5B57A-4D92EB7E9AA"

# K-TR-05 documented create-order body. `side: bid` = buy YES. 1 contract, 1 cent.
_ORDER_BODY: dict[str, Any] = {
    "ticker": MARKET_TICKER,
    "side": "bid",
    "count": "1",
    "price": "0.01",
    "time_in_force": "good_till_canceled",
    "self_trade_prevention_type": "maker",
    "post_only": True,
}

# Request-body fields safe to persist verbatim (public schema / public ticker).
_REQUEST_KEEP = frozenset(_ORDER_BODY) | {"order_id"}


def _sanitise_request_body(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in body.items():
        if k == "client_order_id":
            out[k] = "<demo-synthetic-client-order-id>"
        elif k in _REQUEST_KEEP:
            out[k] = v
        else:
            out[k] = obs.sanitise_body(v)
    return out


def request(
    method: str, path: str, key_id: str, query: dict[str, str] | None = None
) -> dict[str, Any]:
    """One signed, body-less DEMO request (GET / DELETE). Returns a sanitised
    ``{request,status,headers,body}`` record.

    ``query`` is appended to the URL but **excluded** from the signed message
    (Kalshi signs the path only). The V2 cancel endpoint
    ``DELETE /portfolio/events/orders/{order_id}`` needs ``market_ticker`` (or
    ``exchange_index``) here to route to the order's exchange shard — without it
    a sharded order's cancel returns 404.
    """
    ts = str(int(time.time() * 1000))
    signature = obs.sign(f"{ts}{method}{SIGN_PATH_PREFIX}{path}")
    qs = f"?{urlencode(query)}" if query else ""
    req = urllib.request.Request(
        f"{DEMO_BASE_URL}{path}{qs}",
        method=method,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": signature,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status, resp_headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        status, resp_headers, raw = exc.code, exc.headers, exc.read()

    parsed: Any
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = {"<non-json-body-bytes>": len(raw)}

    req_record: dict[str, Any] = {"method": method, "path": path}
    if query:
        # `market_ticker` is the public probe ticker; `exchange_index` an int —
        # neither is account-sensitive, so record verbatim for traceability.
        req_record["query"] = dict(query)
    return {
        "request": req_record,
        "status": status,
        "headers": {
            k.lower(): v
            for k, v in resp_headers.items()
            if k.lower() in obs.HEADERS_OF_INTEREST
        },
        "body": obs.sanitise_body(parsed),
    }


def _post_order(
    path: str, key_id: str, client_order_id: str
) -> tuple[dict[str, Any], str | None]:
    """POST one create-order attempt. Returns (sanitised record, raw order_id)."""
    ts = str(int(time.time() * 1000))
    signature = obs.sign(f"{ts}POST{SIGN_PATH_PREFIX}{path}")
    payload = {**_ORDER_BODY, "client_order_id": client_order_id}
    raw_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DEMO_BASE_URL}{path}",
        data=raw_body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": signature,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status, resp_headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        status, resp_headers, raw = exc.code, exc.headers, exc.read()

    parsed: Any
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = {"<non-json-body-bytes>": len(raw)}

    order_id: str | None = None
    if isinstance(parsed, dict):
        for key in ("order_id", "id"):
            if isinstance(parsed.get(key), str) and parsed[key]:
                order_id = str(parsed[key])
        order = parsed.get("order")
        if order_id is None and isinstance(order, dict) and isinstance(order.get("order_id"), str):
            order_id = str(order["order_id"])

    record: dict[str, Any] = {
        "request": {
            "method": "POST",
            "path": path,
            "body": _sanitise_request_body(payload),
        },
        "status": status,
        "headers": {
            k.lower(): v
            for k, v in resp_headers.items()
            if k.lower() in obs.HEADERS_OF_INTEREST
        },
        "body": obs.sanitise_body(parsed),
    }
    return record, order_id


def _redact_order_id_in_paths(
    steps: list[tuple[str, dict[str, Any]]], order_id: str | None
) -> None:
    """Replace the real ``order_id`` with ``{order_id}`` in every persisted
    ``request.path`` (in place). No-op when no order was created."""
    if order_id is None:
        return
    for _name, record in steps:
        path = record["request"]["path"]
        if order_id in path:
            record["request"]["path"] = path.replace(order_id, "{order_id}")


def _write(out_dir: Path, name: str, record: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    body = record["body"]
    shape = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
    print(f"  {name:24s} {record['status']:>3}  {record['request']['path']}  keys={shape}")


def observe(out_dir: Path | None = None) -> int:
    target = out_dir if out_dir is not None else OUT_DIR
    if "demo" not in DEMO_BASE_URL:
        raise SystemExit(f"refusing to run: base URL is not demo: {DEMO_BASE_URL}")
    print(f"DEMO base = {DEMO_BASE_URL}")
    key_id = obs.keychain_key_id()

    run_id = str(int(time.time()))
    client_order_id = f"pma-demo-lc-{run_id}"
    print(f"DEMO market  = {MARKET_TICKER}")
    print(f"DEMO client_order_id = {client_order_id} (synthetic)")

    steps: list[tuple[str, dict[str, Any]]] = []
    order_id: str | None = None
    left_resting = False

    try:
        # Pre-state.
        steps.append(("00_orders_before", request("GET", "/portfolio/orders", key_id)))

        # 1. Submit — documented V2 events path first, then legacy path.
        rec, order_id = _post_order("/portfolio/events/orders", key_id, client_order_id)
        steps.append(("01_submit_v2_events_orders", rec))
        if order_id is None and rec["status"] in (400, 404, 405):
            rec2, order_id = _post_order("/portfolio/orders", key_id, client_order_id)
            steps.append(("02_submit_legacy_orders", rec2))

        if order_id is None:
            print("\nno order_id returned by either create path — stopping after capture.")
        else:
            print("  (order_id captured in-memory; not persisted)")
            # Give the new order a moment to propagate onto the shard book /
            # portfolio views before reading it back.
            time.sleep(2)
            # 3. Open-order list shape (now non-empty).
            steps.append(("03_orders_after_submit", request("GET", "/portfolio/orders", key_id)))
            # 4. Single-order status shape. Shard-routed (`market_ticker`), same
            #    as cancel — an unrouted get-order for a sharded order can 404.
            steps.append(
                (
                    "04_get_order",
                    request(
                        "GET",
                        f"/portfolio/orders/{order_id}",
                        key_id,
                        query={"market_ticker": MARKET_TICKER},
                    ),
                )
            )
            # 5. Idempotency: resubmit identical client_order_id (no new order on 409).
            dup, _ = _post_order("/portfolio/events/orders", key_id, client_order_id)
            steps.append(("05_submit_duplicate_client_order_id", dup))

            # 6. Cancel — documented V2 path. The body-less DELETE must carry
            #    `market_ticker` (or `exchange_index`) so it routes to the
            #    order's exchange shard; without it a sharded order's cancel
            #    404s (K-TR-10 / cancel-order-v2 query params).
            cancel = request(
                "DELETE",
                f"/portfolio/events/orders/{order_id}",
                key_id,
                query={"market_ticker": MARKET_TICKER},
            )
            steps.append(("06_cancel_v2_events_orders", cancel))
            cancelled_ok = 200 <= cancel["status"] < 300
            if cancelled_ok:
                # Let the cancel propagate off the shard book before re-reading.
                time.sleep(3)

            # 8. Post-cancel order status + list (shard-routed get-order).
            get_order_path = f"/portfolio/orders/{order_id}"
            steps.append(
                (
                    "08_get_order_after_cancel",
                    request(
                        "GET", get_order_path, key_id, query={"market_ticker": MARKET_TICKER}
                    ),
                )
            )
            steps.append(("09_orders_after_cancel", request("GET", "/portfolio/orders", key_id)))
            steps.append(
                (
                    "09b_orders_resting_after_cancel",
                    request("GET", "/portfolio/orders", key_id, query={"status": "resting"}),
                )
            )

            if not cancelled_ok:
                left_resting = _order_still_open(key_id, order_id)
    finally:
        # Best-effort safety net: if an order id exists, try one more shard-routed
        # cancel. A 404 here is expected (already cancelled).
        if order_id is not None:
            try:
                request(
                    "DELETE",
                    f"/portfolio/events/orders/{order_id}",
                    key_id,
                    query={"market_ticker": MARKET_TICKER},
                )
            except Exception:  # noqa: BLE001 - cleanup must not mask the real result
                pass

    # 10. Portfolio reads — expect still empty (no fill).
    steps.append(("10_positions", request("GET", "/portfolio/positions", key_id)))
    steps.append(("11_fills", request("GET", "/portfolio/fills", key_id)))

    # The server-assigned order id is account activity — never persist it. It
    # appears only in `request.path` (response bodies are already sanitised);
    # collapse it to a placeholder before writing.
    _redact_order_id_in_paths(steps, order_id)

    summary: list[dict[str, Any]] = []
    for name, record in steps:
        _write(target, name, record)
        body = record["body"]
        summary.append(
            {
                "name": name,
                "method": record["request"]["method"],
                "path": record["request"]["path"],
                "status": record["status"],
                "body_keys": sorted(body.keys())
                if isinstance(body, dict)
                else type(body).__name__,
            }
        )
    (target / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {len(steps)} sanitised fixtures + SUMMARY.json to {target}")

    if left_resting:
        print("\n*** WARNING: a demo order may still be resting — check manually. ***")
        return 1
    return 0


def _order_still_open(key_id: str, order_id: str) -> bool:
    check = request("GET", f"/portfolio/orders/{order_id}", key_id)
    body = check["body"]
    if isinstance(body, dict):
        order = body.get("order") if isinstance(body.get("order"), dict) else body
        status = order.get("status") if isinstance(order, dict) else None
        return status not in ("canceled", "cancelled", "executed", "<redacted>")
    return bool(check["status"] == 200)


if __name__ == "__main__":
    _sub = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(observe(obs.OUT_DIR / _sub if _sub else None))
