"""**Unauthenticated, read-only** observation of Kalshi **production** market
data — a bounded sustained session, for Real-money gate #2 "Stable live market
data".

Scope and limits (see ``docs/API_SOURCES.md`` gate-status section):

- Kalshi production **REST** market data is public — no auth, no credentials
  (K-09). This script does GET-only polling of ``/markets`` and
  ``/markets/{ticker}/orderbook`` over a sustained window and records timing,
  HTTP status, book depth, and how often the book actually moved.
- It does **not** open a WebSocket. Kalshi's production market-data WS
  (``wss://external-api-ws.kalshi.com/trade-api/ws/v2``) **requires API-key
  auth in the handshake, public channels included** (K-WS-01), and no
  production Kalshi credential exists in this environment — so WS connection
  success, per-subscription ``seq`` handling, and stream disconnect/reconnect
  are **not** verified here.
- The "transport failure + recovery" probe is a REST-level analog only
  (unreachable host → error → next good request succeeds); it is **not** a
  WebSocket reconnect/resync.

Not part of the shipped package. Run manually:

    python scripts/observe_kalshi_prod_market_data.py [DURATION_SECONDS] [INTERVAL_SECONDS]

Evidence is written sanitised to ``docs/evidence/kalshi-live/market-data/``:
counts, per-poll timing offsets, status histogram, book-change tally, and one
structure-only sample of an orderbook response (every scalar leaf → a type
token). No raw prices/sizes and no account data (there is none — unauthenticated).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROD_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
UNREACHABLE_URL = "https://external-api-ws.kalshi.invalid/trade-api/v2/markets"
_EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence"
OUT_DIR = _EVIDENCE / "kalshi-live" / "market-data"
TIMEOUT = 15.0
USER_AGENT = (
    "prediction-market-arbitrage/0.1 "
    "(read-only PROD market-data observation; +https://github.com/Jams411)"
)
HEADERS_OF_INTEREST = ("content-type", "date")


def _get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json", "User-Agent": USER_AGENT}
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
        "status": status,
        "headers": {k.lower(): v for k, v in headers.items() if k.lower() in HEADERS_OF_INTEREST},
        "body": body,
    }


def _redact(value: Any) -> Any:
    """Structure-first: keep shape + field names, replace every scalar leaf."""
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:2]] + (["<...>"] if len(value) > 2 else [])
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "<number>"
    return "<redacted>"


def _ob_levels(body: Any) -> tuple[int, int]:
    ob = body.get("orderbook_fp", {}) if isinstance(body, dict) else {}
    yes = ob.get("yes_dollars") or []
    no = ob.get("no_dollars") or []
    return len(yes), len(no)


def _ob_fingerprint(body: Any) -> str:
    """A stable digest of the full book contents — to tell a moving book from a
    static one **without persisting prices**."""
    ob = body.get("orderbook_fp", {}) if isinstance(body, dict) else {}
    return json.dumps(
        {"y": ob.get("yes_dollars"), "n": ob.get("no_dollars")}, sort_keys=True
    )


# Actively-traded production series to sample from (Bitcoin intraday / range
# markets have the most frequent book movement). We do not hard-code a market
# ticker (they roll daily) — we take the open markets of these series and pick
# the one whose order book actually has depth on both sides right now.
_ACTIVE_SERIES = ("KXBTCD", "KXBTC", "KXETHD", "KXETH")


def _pick_liquid_market() -> str:
    candidates: list[str] = []
    for series in _ACTIVE_SERIES:
        page = _get(f"{PROD_BASE_URL}/markets?limit=100&status=open&series_ticker={series}")
        markets = page["body"].get("markets", []) if isinstance(page["body"], dict) else []
        candidates += [
            m["ticker"]
            for m in markets
            if m.get("market_type") == "binary" and m.get("ticker")
        ]
        if len(candidates) >= 40:
            break
    if not candidates:
        raise SystemExit("no open markets returned for the active production series")

    best_ticker = ""
    best_depth = -1
    for ticker in candidates[:40]:
        ob = _get(f"{PROD_BASE_URL}/markets/{ticker}/orderbook")
        y, n = _ob_levels(ob["body"])
        depth = min(y, n)  # both sides must be quoted for a real two-sided book
        if depth > best_depth:
            best_depth, best_ticker = depth, ticker
    if best_depth <= 0:
        # fall back to whichever had the most one-sided depth
        for ticker in candidates[:40]:
            ob = _get(f"{PROD_BASE_URL}/markets/{ticker}/orderbook")
            y, n = _ob_levels(ob["body"])
            if y + n > best_depth:
                best_depth, best_ticker = y + n, ticker
    return best_ticker or candidates[0]


def observe(duration_s: float = 90.0, interval_s: float = 5.0) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session_start = datetime.now(UTC)
    t0 = time.monotonic()

    ticker = _pick_liquid_market()
    print(f"PROD base = {PROD_BASE_URL}")
    print(f"market    = {ticker}")

    # 1. REST snapshot initialisation.
    snap = _get(f"{PROD_BASE_URL}/markets/{ticker}/orderbook")
    snap_yes, snap_no = _ob_levels(snap["body"])
    (OUT_DIR / "01_rest_snapshot_shape.json").write_text(
        json.dumps(
            {
                "request": {"method": "GET", "path": "/markets/{ticker}/orderbook"},
                "status": snap["status"],
                "headers": snap["headers"],
                "body": _redact(snap["body"]),
                "yes_levels": snap_yes,
                "no_levels": snap_no,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    # 2. Sustained poll loop.
    polls: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    prev_fp: str | None = None
    changes = 0
    last_change_offset = 0.0
    max_gap_between_changes = 0.0
    status_hist: dict[int, int] = {}

    deadline = t0 + duration_s
    while time.monotonic() < deadline:
        offset = round(time.monotonic() - t0, 3)
        ob = _get(f"{PROD_BASE_URL}/markets/{ticker}/orderbook")
        mkt = _get(f"{PROD_BASE_URL}/markets/{ticker}")
        status_hist[ob["status"]] = status_hist.get(ob["status"], 0) + 1
        y, n = _ob_levels(ob["body"])
        fp = _ob_fingerprint(ob["body"])
        fingerprints.add(fp)
        changed = prev_fp is not None and fp != prev_fp
        if changed:
            changes += 1
            gap = offset - last_change_offset
            max_gap_between_changes = max(max_gap_between_changes, gap)
            last_change_offset = offset
        prev_fp = fp
        m = mkt["body"].get("market", {}) if isinstance(mkt["body"], dict) else {}
        polls.append(
            {
                "offset_s": offset,
                "ob_status": ob["status"],
                "mkt_status": mkt["status"],
                "yes_levels": y,
                "no_levels": n,
                "book_changed_since_prev": changed,
                "market_status_field": m.get("status"),
                "has_yes_bid": m.get("yes_bid_dollars") not in (None, ""),
                "has_no_bid": m.get("no_bid_dollars") not in (None, ""),
            }
        )
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval_s, remaining))

    # 3. Transport failure + recovery (REST analog — NOT a WS reconnect).
    try:
        urllib.request.urlopen(
            urllib.request.Request(UNREACHABLE_URL, headers={"User-Agent": USER_AGENT}),
            timeout=TIMEOUT,
        )
        fail_kind = "unexpected-success"
    except urllib.error.URLError as exc:
        fail_kind = type(exc).__name__
    except OSError as exc:
        fail_kind = type(exc).__name__
    recover = _get(f"{PROD_BASE_URL}/markets/{ticker}/orderbook")

    session_end = datetime.now(UTC)
    elapsed = round(time.monotonic() - t0, 3)

    summary = {
        "venue": "kalshi",
        "environment": "production",
        "auth": "none (public REST market data, K-09)",
        "transport": "REST polling — NOT WebSocket (K-WS-01: prod WS needs auth; no prod key)",
        "market_ticker": ticker,
        "session_start_utc": session_start.isoformat(),
        "session_end_utc": session_end.isoformat(),
        "wall_elapsed_s": elapsed,
        "requested_duration_s": duration_s,
        "poll_interval_s": interval_s,
        "polls": len(polls),
        "orderbook_status_histogram": {str(k): v for k, v in sorted(status_hist.items())},
        "rest_snapshot_status": snap["status"],
        "rest_snapshot_yes_levels": snap_yes,
        "rest_snapshot_no_levels": snap_no,
        "distinct_book_states_observed": len(fingerprints),
        "polls_with_book_change": changes,
        "max_gap_between_book_changes_s": round(max_gap_between_changes, 3),
        "transport_failure_probe": {
            "url_host": "external-api-ws.kalshi.invalid",
            "result": fail_kind,
            "note": "REST-level unreachable-host analog; NOT a WebSocket disconnect/resync",
        },
        "recovery_after_failure_status": recover["status"],
        "per_poll": polls,
        "not_verified_here": [
            "WebSocket connection success (prod WS requires auth; no prod credential)",
            "per-subscription seq / snapshot-then-delta ordering",
            "stream disconnect detection and reconnect/resync",
            "feed HealthStatus transitions across a real reconnect",
        ],
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"\n{len(polls)} polls over {elapsed}s; "
        f"{len(fingerprints)} distinct book states; {changes} changes; "
        f"recovery status {recover['status']}"
    )
    print(f"wrote evidence to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    itv = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    sys.exit(observe(dur, itv))
