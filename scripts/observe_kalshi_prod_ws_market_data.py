"""Authenticated **read-only** observation of the Kalshi **production**
market-data WebSocket — *prepared, not yet run*.

Purpose: capture the OBSERVED evidence that the unauthenticated REST session
(``scripts/observe_kalshi_prod_market_data.py``) explicitly could not — a real
authenticated handshake, one ``orderbook_snapshot`` + ``orderbook_delta`` on the
``orderbook_delta`` channel, per-subscription ``seq`` behaviour, and a
disconnect → reconnect → resubscribe → fresh-snapshot resync. This resolves
assumptions **A-030** (handshake/subscribe/frame formats match the live venue)
and **A-028** (additive ``delta_fp`` application) for Kalshi.

Hard limits — this script:
- opens the market-data WebSocket only; sends only ``subscribe`` frames;
- never calls any ``/portfolio`` endpoint and never touches balances,
  positions, fills, or orders (it has no code path to);
- never submits / cancels / modifies an order;
- never reads or sets ``LIVE_TRADING``; adds no execution wiring;
- does not touch Polymarket US.
It resolves **no** Real-money gate item by itself: gate #2 ("Stable live market
data"), #7 ("Stale-data handling"), and #8 ("Disconnect/reconnect behaviour")
stay unchecked. It only removes the "no authenticated WS session was possible"
blocker recorded under those items.

Run modes::

    python scripts/observe_kalshi_prod_ws_market_data.py            # --check (default)
    python scripts/observe_kalshi_prod_ws_market_data.py --check    # preflight only, no socket
    PMA_KALSHI_PROD_WS_OBSERVE=1 \
        python scripts/observe_kalshi_prod_ws_market_data.py --observe   # the real session

``--check`` never opens a socket. ``--observe`` refuses unless the
``PMA_KALSHI_PROD_WS_OBSERVE=1`` env guard is set *and* the credential preflight
passes.

Credentials (never printed, logged, persisted, fixtured, or committed):
- API key id: macOS Keychain — ``security find-generic-password -a "$USER"
  -s pma-kalshi-prod-api-key-id -w``.
- RSA private key: ``~/.config/pma/kalshi-prod-private-key.pem`` (mode 600).
  Read from that file only; never from an env var or the command line.

Signing is RSA-PSS/SHA-256 (salt = digest length) over
``timestamp_ms + "GET" + "/trade-api/ws/v2"`` — built by
``livebook.ws_auth.kalshi_ws_handshake`` and performed by
``scripts.kalshi_signer.OpensslRsaPssSigner`` (``openssl`` subprocess; no
cryptography dependency).

Evidence is written **sanitised** to ``docs/evidence/kalshi-live/ws-market-data/``:
frame counts, ``seq`` values and monotonicity, and one structure-only sample of
a snapshot and a delta frame (every scalar leaf replaced by a type token). No
raw prices or sizes; there is no account data to redact (market-data channel).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from kalshi_signer import OpensslRsaPssSigner, SignerError, read_keychain_password

from prediction_market_arbitrage.livebook import (
    KalshiCredentials,
    TransportClosed,
    WebsocketsTransport,
    kalshi_subscribe_command,
    kalshi_ws,
    kalshi_ws_handshake,
)
from prediction_market_arbitrage.livebook.ws_auth import KALSHI_WS_URL_PROD

PROD_WS_URL = KALSHI_WS_URL_PROD  # wss://external-api-ws.kalshi.com/trade-api/ws/v2
PUBLIC_REST_BASE = "https://external-api.kalshi.com/trade-api/v2"  # public, GET-only (K-09)

KEYCHAIN_SERVICE = "pma-kalshi-prod-api-key-id"
PEM_PATH = Path.home() / ".config" / "pma" / "kalshi-prod-private-key.pem"
RUN_ENV_GUARD = "PMA_KALSHI_PROD_WS_OBSERVE"

OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "evidence"
    / "kalshi-live"
    / "ws-market-data"
)
TIMEOUT = 15.0
USER_AGENT = (
    "prediction-market-arbitrage/0.1 "
    "(read-only PROD WS market-data observation; +https://github.com/Jams411)"
)

# Series whose books move often enough to see a delta quickly (mirrors the REST
# observation script). Tickers roll daily, so we resolve open markets at runtime.
_ACTIVE_SERIES = ("KXBTCD", "KXBTC", "KXETHD", "KXETH")

# Belt-and-braces: no substring of an account / order endpoint may appear in this
# file. A unit test asserts this list stays absent from the source.
_FORBIDDEN_PATH_MARKERS = ("/portfolio", "events/orders", "/orders/", "target_balance")

# The manual step the operator must take (no automation) — printed by --check.
CREATE_KEY_STEPS = (
    "Create a PRODUCTION Kalshi API key manually (not automated by this repo):\n"
    "  1. Log in to your Kalshi account at https://kalshi.com (production).\n"
    "  2. Open  Account & security  ->  API Keys  ->  Create Key.\n"
    "     (Older UI wording: Profile Settings -> API Keys -> Create New API Key.)\n"
    "  3. Download the private key file once (PEM / .key). Kalshi keeps only the\n"
    "     public half; the private key cannot be re-downloaded.\n"
    "     Kalshi API keys are self-service and unscoped: there is no read-only vs\n"
    "     trading key type and no approval step. Use a key dedicated to this\n"
    "     read-only observation.\n"
    "  4. Store the key id in the macOS Keychain:\n"
    f"       security add-generic-password -a \"$USER\" -s {KEYCHAIN_SERVICE} -w\n"
    f"  5. Move the private key to {PEM_PATH} and  chmod 600  it.\n"
    "  6. Re-run this script with:\n"
    f"       {RUN_ENV_GUARD}=1 python scripts/observe_kalshi_prod_ws_market_data.py --observe\n"
)


# --------------------------------------------------------------------------- #
# Preflight (no network, no socket)
# --------------------------------------------------------------------------- #


def preflight() -> dict[str, Any]:
    """Check local prerequisites without opening a socket or reading key bytes
    beyond ``is_file``. Returns a report; ``ready`` is True only if all pass."""
    openssl_ok = _which("openssl") is not None
    pem_ok = PEM_PATH.is_file()
    try:
        _ = read_keychain_password(KEYCHAIN_SERVICE)
        keychain_ok = True
        keychain_detail = "present"
    except SignerError as exc:
        keychain_ok = False
        keychain_detail = str(exc)
    return {
        "openssl_on_path": openssl_ok,
        "private_key_file_present": pem_ok,
        "private_key_path": str(PEM_PATH),
        "keychain_key_id": keychain_detail,
        "env_guard_set": os.environ.get(RUN_ENV_GUARD) == "1",
        "ready": openssl_ok and pem_ok and keychain_ok,
    }


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


# --------------------------------------------------------------------------- #
# Public, unauthenticated market pick (GET-only)
# --------------------------------------------------------------------------- #


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def pick_liquid_market() -> str:
    """Pick one open production market with two-sided book depth, via public
    REST. GET-only, unauthenticated (K-09)."""
    candidates: list[str] = []
    for series in _ACTIVE_SERIES:
        page = _get_json(
            f"{PUBLIC_REST_BASE}/markets?limit=100&status=open&series_ticker={series}"
        )
        markets = page.get("markets", []) if isinstance(page.get("markets"), list) else []
        candidates += [
            m["ticker"]
            for m in markets
            if isinstance(m, dict) and m.get("market_type") == "binary" and m.get("ticker")
        ]
        if len(candidates) >= 40:
            break
    if not candidates:
        raise SystemExit("no open markets returned for the active production series")

    best_ticker, best_depth = "", -1
    for ticker in candidates[:40]:
        ob = _get_json(f"{PUBLIC_REST_BASE}/markets/{ticker}/orderbook")
        book = ob.get("orderbook_fp", {}) if isinstance(ob.get("orderbook_fp"), dict) else {}
        depth = min(len(book.get("yes_dollars") or []), len(book.get("no_dollars") or []))
        if depth > best_depth:
            best_depth, best_ticker = depth, ticker
    return best_ticker or candidates[0]


# --------------------------------------------------------------------------- #
# Stream consumption (socket-agnostic — driven by a Transport)
# --------------------------------------------------------------------------- #


class _Transport(Protocol):
    def send(self, text: str) -> None: ...
    def receive(self) -> str: ...
    def close(self) -> None: ...


def consume_book_stream(
    transport: _Transport,
    *,
    command_id: int,
    market_ticker: str,
    want_deltas: int,
    max_frames: int,
) -> dict[str, Any]:
    """Subscribe to ``orderbook_delta`` for one market and read frames until
    ``want_deltas`` deltas have arrived (or ``max_frames`` frames seen / the
    socket closes). Returns a sanitised, structure-only observation."""
    transport.send(
        json.dumps(kalshi_subscribe_command(command_id=command_id, market_tickers=[market_ticker]))
    )

    snapshots = 0
    deltas = 0
    seqs: list[int] = []
    frame_types: dict[str, int] = {}
    first_snapshot_shape: Any = None
    first_delta_shape: Any = None

    for _ in range(max_frames):
        try:
            raw = transport.receive()
        except TransportClosed:
            break
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            frame_types["<non-json>"] = frame_types.get("<non-json>", 0) + 1
            continue
        if not isinstance(frame, dict):
            continue
        ftype = str(frame.get("type", "<none>"))
        frame_types[ftype] = frame_types.get(ftype, 0) + 1

        if ftype == "orderbook_snapshot":
            snapshots += 1
            kalshi_ws.decode_orderbook_snapshot(frame)  # validates shape
            if isinstance(frame.get("seq"), int):
                seqs.append(frame["seq"])
            if first_snapshot_shape is None:
                first_snapshot_shape = sanitise(frame)
        elif ftype == "orderbook_delta":
            deltas += 1
            kalshi_ws.decode_orderbook_delta(frame)  # validates shape
            if isinstance(frame.get("seq"), int):
                seqs.append(frame["seq"])
            if first_delta_shape is None:
                first_delta_shape = sanitise(frame)
            if deltas >= want_deltas:
                break

    return {
        "market_ticker_redacted": "<redacted>",
        "snapshots": snapshots,
        "deltas": deltas,
        "frame_type_histogram": dict(sorted(frame_types.items())),
        "seq_values": seqs,
        "seq_strictly_increasing": all(a < b for a, b in zip(seqs, seqs[1:], strict=False)),
        "first_snapshot_shape": first_snapshot_shape,
        "first_delta_shape": first_delta_shape,
    }


def sanitise(value: Any) -> Any:
    """Structure-first: keep object/array shape and every field *name*; replace
    each scalar leaf with a type token (mirrors the REST observation script)."""
    if isinstance(value, dict):
        return {k: sanitise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitise(v) for v in value[:2]] + (["<...>"] if len(value) > 2 else [])
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "<number>"
    return "<redacted>"


# --------------------------------------------------------------------------- #
# The real session (only reachable via --observe + env guard)
# --------------------------------------------------------------------------- #


def run_observation() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key_id = read_keychain_password(KEYCHAIN_SERVICE)
    signer = OpensslRsaPssSigner(PEM_PATH)
    credentials = KalshiCredentials(api_key_id=key_id, private_key_pem=PEM_PATH.read_text())

    def make_handshake() -> Any:
        # Fresh timestamp + signature per connection (K-WS-AUTH-02/03).
        return kalshi_ws_handshake(credentials, signer, now=datetime.now(UTC), url=PROD_WS_URL)

    ticker = pick_liquid_market()
    session_start = datetime.now(UTC)

    # 1. Connect + subscribe + snapshot + delta.
    t1 = WebsocketsTransport(recv_timeout=30.0)
    t1.connect(make_handshake())
    first = consume_book_stream(
        t1, command_id=1, market_ticker=ticker, want_deltas=3, max_frames=200
    )
    t1.close()  # 2. Disconnect.

    # 3. Reconnect + resubscribe -> the channel re-sends a fresh snapshot then
    #    deltas (K-WS-02), i.e. a full resync on a new connection.
    t2 = WebsocketsTransport(recv_timeout=30.0)
    t2.connect(make_handshake())
    second = consume_book_stream(
        t2, command_id=2, market_ticker=ticker, want_deltas=1, max_frames=200
    )
    t2.close()

    session_end = datetime.now(UTC)
    summary = {
        "venue": "kalshi",
        "environment": "production",
        "transport": "authenticated WebSocket (orderbook_delta channel)",
        "ws_url": PROD_WS_URL,
        "auth": "KALSHI-ACCESS-KEY / -TIMESTAMP(ms) / -SIGNATURE(base64 RSA-PSS SHA-256)",
        "session_start_utc": session_start.isoformat(),
        "session_end_utc": session_end.isoformat(),
        "first_connection": first,
        "after_reconnect_resubscribe": second,
        "resync_delivered_fresh_snapshot": second["snapshots"] >= 1,
        "notes": [
            "No /portfolio call, no order call, no balance/position/fill read.",
            "LIVE_TRADING not read or set; no execution wiring.",
            "Real-money gate items #2/#7/#8 remain unchecked.",
        ],
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"first: {first['snapshots']} snap / {first['deltas']} delta; "
        f"reconnect: {second['snapshots']} snap / {second['deltas']} delta; "
        f"seq increasing: {first['seq_strictly_increasing']}"
    )
    print(f"wrote sanitised evidence to {OUT_DIR}")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = "--check"
    for candidate in ("--check", "--observe"):
        if candidate in args:
            mode = candidate

    report = preflight()
    print("preflight:")
    for key, val in report.items():
        print(f"  {key}: {val}")
    print()

    if mode == "--check":
        if not report["ready"]:
            print(CREATE_KEY_STEPS)
        else:
            print(
                "Ready. Start the read-only session with:\n"
                f"  {RUN_ENV_GUARD}=1 python "
                "scripts/observe_kalshi_prod_ws_market_data.py --observe\n"
            )
        return 0

    # mode == "--observe"
    if report["env_guard_set"] is not True:
        print(
            f"Refusing to open a production socket: set {RUN_ENV_GUARD}=1 to confirm.\n",
            file=sys.stderr,
        )
        return 2
    if not report["ready"]:
        print("Refusing to connect: preflight did not pass (see above).\n", file=sys.stderr)
        print(CREATE_KEY_STEPS, file=sys.stderr)
        return 2
    return run_observation()


if __name__ == "__main__":
    sys.exit(main())
