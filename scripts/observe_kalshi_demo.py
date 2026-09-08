"""Authenticated **read-only** observation of the Kalshi *demo* environment.

Purpose: capture OBSERVED evidence for the trading-API rows in
``docs/API_SOURCES.md`` (K-TR-*) that are currently ``VERIFIED (docs)`` only —
auth/signing behavior and the response *shapes* of the portfolio read endpoints
(balance, positions, fills, orders). GET-only. Nothing here can submit, cancel,
or modify an order.

Not part of the shipped package. Run manually:

    python scripts/observe_kalshi_demo.py

Credentials (never printed, logged, persisted, fixtured, or committed):
- API key id: macOS Keychain, ``security find-generic-password -a "$USER"
  -s pma-kalshi-demo-api-key-id -w``.
- RSA private key: ``~/.config/pma/kalshi-demo-private-key.pem``.

Signing (K-TR-03): message = ``timestamp_ms + METHOD + path`` (path without
query); RSA-PSS, MGF1-SHA256, salt length = digest length, over SHA-256;
base64. Done by shelling out to ``openssl`` so this repo keeps its
zero-runtime-dependency posture (no ``cryptography`` import).

Sanitisation: every captured fixture is passed through :func:`sanitise`, which
drops account-identifying scalars (ids, emails, names) and numeric monetary
balances but keeps the JSON structure. The API key id and signature are never
written anywhere.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEMO_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
SIGN_PATH_PREFIX = "/trade-api/v2"
PEM_PATH = Path.home() / ".config" / "pma" / "kalshi-demo-private-key.pem"
KEYCHAIN_SERVICE = "pma-kalshi-demo-api-key-id"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "kalshi-demo"
TIMEOUT = 15.0
USER_AGENT = (
    "prediction-market-arbitrage/0.1 (read-only demo observation; +https://github.com/Jams411)"
)

# Response header names worth recording (lower-cased). Everything else is dropped.
HEADERS_OF_INTEREST = (
    "content-type",
    "date",
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
)

# Keys whose *values* identify the account/holder — replaced with "<redacted>".
_REDACT_KEYS = {
    "member_id",
    "user_id",
    "account_id",
    "subaccount_id",
    "email",
    "name",
    "first_name",
    "last_name",
    "username",
    "api_key_id",
    "access_key",
}


def _whoami() -> str:
    return subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()


def keychain_key_id() -> str:
    out = subprocess.run(
        ["security", "find-generic-password", "-a", _whoami(), "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=True,
    )
    value = out.stdout.strip()
    if not value:
        raise SystemExit("empty Keychain entry for " + KEYCHAIN_SERVICE)
    return value


def sign(message: str) -> str:
    """RSA-PSS(SHA-256, MGF1-SHA256, salt=digest len) over ``message``, base64."""
    if not PEM_PATH.is_file():
        raise SystemExit(f"private key not found: {PEM_PATH}")
    proc = subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(PEM_PATH),
            "-sigopt",
            "rsa_padding_mode:pss",
            "-sigopt",
            "rsa_pss_saltlen:digest",
            "-binary",
        ],
        input=message.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return base64.b64encode(proc.stdout).decode("ascii")


def _http_get(path: str, key_id: str, signature: str, ts: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{DEMO_BASE_URL}{path}",
        method="GET",
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
            status, headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        status, headers, raw = exc.code, exc.headers, exc.read()

    body: Any
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = {"<non-json-body-bytes>": len(raw)}

    return {
        "request": {"method": "GET", "path": path},
        "status": status,
        "headers": {k.lower(): v for k, v in headers.items() if k.lower() in HEADERS_OF_INTEREST},
        "body": body,
    }


def get(
    path: str,
    key_id: str,
    *,
    sign_string: str | None = None,
    send_key: str | None = None,
) -> dict[str, Any]:
    """One authenticated GET.

    ``sign_string`` overrides the signed message (to probe a bad signature);
    ``send_key`` overrides the ``KALSHI-ACCESS-KEY`` header (to probe an unknown
    key). Defaults produce a correctly signed request.
    """
    ts = str(int(time.time() * 1000))
    message = sign_string if sign_string is not None else f"{ts}GET{SIGN_PATH_PREFIX}{path}"
    return _http_get(path, send_key if send_key is not None else key_id, sign(message), ts)


def _is_money_key(key: str) -> bool:
    key = key.lower()
    return key == "balance" or key.endswith(("_dollars", "_cents", "_pnl"))


def sanitise(value: Any) -> Any:
    """Recursively replace account-identifying scalars with ``"<redacted>"`` and
    numeric monetary balances with ``"<number>"``; keep all structure."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in _REDACT_KEYS and isinstance(v, (str, int, float)):
                out[k] = "<redacted>"
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and _is_money_key(k):
                out[k] = "<number>"
            else:
                out[k] = sanitise(v)
        return out
    if isinstance(value, list):
        return [sanitise(v) for v in value]
    return value


def observe() -> int:
    key_id = keychain_key_id()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    probes: list[tuple[str, dict[str, Any]]] = []

    # 1. Portfolio reads — the endpoints the real-money gate's "position/order
    #    reconciliation" item depends on. All GET, all read-only.
    for name, path in (
        ("balance", "/portfolio/balance"),
        ("positions", "/portfolio/positions"),
        ("fills", "/portfolio/fills"),
        ("orders", "/portfolio/orders"),
        ("orders_events", "/portfolio/events/orders"),
    ):
        probes.append((name, get(path, key_id)))

    # 2. Unknown order id → observe the 404 shape (no order is created).
    probes.append(
        ("order_unknown", get("/portfolio/orders/PMA-OBS-DOES-NOT-EXIST", key_id))
    )

    # 3. Auth-failure probe: valid headers, deliberately wrong signed string.
    probes.append(
        ("auth_bad_signature", get("/portfolio/balance", key_id, sign_string="wrong-signed-string"))
    )

    # 4. Auth-failure probe: unknown API key id (signature valid for its message).
    probes.append(
        ("auth_bad_key", get("/portfolio/balance", key_id, send_key="pma-observation-not-a-key"))
    )

    summary: list[dict[str, Any]] = []
    for name, result in probes:
        clean = sanitise(result)
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(clean, indent=2, sort_keys=True) + "\n"
        )
        body = clean["body"]
        shape = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
        summary.append(
            {
                "name": name,
                "path": clean["request"]["path"],
                "status": clean["status"],
                "body_keys": shape,
            }
        )
        print(f"  {name:20s} {result['status']:>3}  {clean['request']['path']}")

    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {len(probes)} sanitised fixtures + SUMMARY.json to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(observe())
