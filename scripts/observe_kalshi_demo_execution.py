"""Bounded **Kalshi DEMO** execution observation through the shipped orchestrator
(real-money-gate readiness — #3 / #4 / #6 / #10).

Runs ONE tiny limit order end to end through
``demo_execution.DemoExecutionOrchestrator`` +
``demo_execution.KalshiDemoRestTransport`` (M3.6) against the Kalshi **demo**
host, then observes / reconciles / cancels / records sanitised evidence.

Everything is DEMO:

- Base URL hard-pinned to ``external-api.demo.kalshi.co`` via
  ``demo_execution.assert_demo_host`` (a production host is a hard failure
  before any request).
- Demo API key id from macOS Keychain ``pma-kalshi-demo-api-key-id``; demo RSA
  key from ``~/.config/pma/kalshi-demo-private-key.pem`` (``scripts.kalshi_signer``
  — file-only, never printed/logged/persisted).
- Production Kalshi is never called. No Polymarket US. ``LIVE_TRADING`` is never
  read or set. No fund movement.

Safety of the order itself:

- **1 contract**, ``limit`` ``buy`` (bid) at the current best ask, on a liquid
  demo market whose best ask is ``<= --max-price`` (default $0.60) — so max
  notional at risk is ~$0.60 of demo funny-money.
- Whatever is not immediately filled is **cancelled**; a ``finally`` block makes
  one more best-effort shard-routed cancel and reports loudly if anything is
  left resting.
- Exactly one create attempt. An unexpected rejection stops the run.

Run modes::

    python scripts/observe_kalshi_demo_execution.py                 # --check (NO network)
    python scripts/observe_kalshi_demo_execution.py --diagnose [--max-price 0.60] [--pages N]
        # READ-ONLY: public GET /markets* on the demo host; lists candidate
        # markets with the YES-book facts the picker uses. No auth, no order.
        # --pages 1 (default) mirrors the picker; a higher N only widens the scan.
    PMA_KALSHI_DEMO_EXECUTE=1 \
        python scripts/observe_kalshi_demo_execution.py --observe \
        --ticker KX... [--max-price 0.60]

Sanitised evidence -> ``docs/evidence/kalshi-demo/execution/``:
``SUMMARY.json`` (the ``ExecutionOutcome.to_evidence_dict()`` + a venue-vs-local
reconciliation block + timings) and per-step ``NN_*.json`` (venue bodies through
``observe_kalshi_demo.sanitise_body`` — the D-024 fail-safe allowlist).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import observe_kalshi_demo as demo
from kalshi_signer import OpensslRsaPssSigner, SignerError, read_keychain_password

from prediction_market_arbitrage.adapters.kalshi import DEMO_BASE_URL, KalshiClient
from prediction_market_arbitrage.adapters.kalshi.adapter import KalshiMarketDataAdapter
from prediction_market_arbitrage.demo_execution import (
    DemoExecutionError,
    DemoExecutionOrchestrator,
    KalshiDemoLiveBroker,
    KalshiDemoRestTransport,
    assert_demo_host,
)
from prediction_market_arbitrage.live_broker import REQUIRED_PHRASE, LiveTradingGate
from prediction_market_arbitrage.live_broker.models import LiveOrderRequest
from prediction_market_arbitrage.livebook import FeedHealth, HealthStatus
from prediction_market_arbitrage.recorder import PositionRow, Recorder
from prediction_market_arbitrage.risk import RiskLimits, RiskManager

KEYCHAIN_SERVICE = "pma-kalshi-demo-api-key-id"
PEM_PATH = Path.home() / ".config" / "pma" / "kalshi-demo-private-key.pem"
RUN_ENV_GUARD = "PMA_KALSHI_DEMO_EXECUTE"
OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "evidence"
    / "kalshi-demo"
    / "execution"
)
DEFAULT_MAX_PRICE = Decimal("0.60")
ORDER_QUANTITY = Decimal("1")
MAX_DAILY_LOSS = Decimal("2")

#: A usable two-sided book needs at least this many resting levels per side.
#: Shared by :func:`pick_liquid_demo_market` and the read-only diagnostic so the
#: diagnostic reports exactly the rule the picker enforces.
MIN_BOOK_DEPTH = 2
#: ``GET /markets`` page size for both the picker and the diagnostic.
DIAG_MARKET_LIMIT = 100

#: The only keys copied verbatim into the sanitised evidence from
#: ``ExecutionOutcome.to_evidence_dict()``. Booleans + code-internal enum strings
#: + risk-check *labels* only — never a market ticker, a client_order_id, a raw
#: price/size, or a free-text risk reason (those can echo a contract id).
_SAFE_OUTCOME_KEYS = (
    "risk_allowed",
    "risk_checks_run",
    "submitted",
    "duplicate",
    "blocked_reason",
    "venue_accepted",
    "venue_state",
    "order_status_state",
    "cancelled",
    "reconciled",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _probe_risk_limits() -> RiskLimits:
    """Fail-closed limits for the one-order demo probe: never more than 1
    contract, never a net position above 1, and a $2 realised-loss breaker on
    demo funny-money."""
    return RiskLimits(
        max_order_size=ORDER_QUANTITY,
        max_position=ORDER_QUANTITY,
        max_daily_loss=MAX_DAILY_LOSS,
    )


def _safe_outcome(evidence: dict[str, Any]) -> dict[str, Any]:
    """Project ``ExecutionOutcome.to_evidence_dict()`` down to the
    :data:`_SAFE_OUTCOME_KEYS` allowlist plus a reason *count* — no ticker,
    client_order_id, or reason strings reach the evidence file."""
    out: dict[str, Any] = {k: evidence.get(k) for k in _SAFE_OUTCOME_KEYS}
    out["risk_reason_count"] = len(evidence.get("risk_reasons", ()) or ())
    return out


# --------------------------------------------------------------------------- #
# preflight (no socket)
# --------------------------------------------------------------------------- #


def preflight() -> dict[str, Any]:
    from shutil import which

    openssl_ok = which("openssl") is not None
    pem_ok = PEM_PATH.is_file()
    try:
        read_keychain_password(KEYCHAIN_SERVICE)
        keychain = "present"
    except SignerError as exc:
        keychain = str(exc)
    host_ok = True
    try:
        assert_demo_host(DEMO_BASE_URL)
    except Exception as exc:  # noqa: BLE001
        host_ok = False
        keychain = f"{keychain}; host-guard: {exc}"
    return {
        "openssl_on_path": openssl_ok,
        "demo_private_key_present": pem_ok,
        "demo_keychain_key_id": keychain,
        "demo_base_url": DEMO_BASE_URL,
        "demo_host_guard_passes": host_ok,
        "env_guard_set": os.environ.get(RUN_ENV_GUARD) == "1",
        "ready": openssl_ok and pem_ok and keychain == "present" and host_ok,
    }


# --------------------------------------------------------------------------- #
# market selection (read-only, demo base)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Pick:
    ticker: str
    contract_id: str
    best_ask: Decimal


def pick_liquid_demo_market(max_price: Decimal) -> _Pick:
    """One open demo market with a two-sided book and best ask <= ``max_price``.
    Read-only (``GET /markets*`` on the demo base)."""
    adapter = KalshiMarketDataAdapter(KalshiClient(base_url=DEMO_BASE_URL))
    page = adapter.list_markets(status="open", limit=DIAG_MARKET_LIMIT)
    best: _Pick | None = None
    for market in page.markets:
        try:
            books = adapter.get_order_books(market.id)
        except Exception:  # noqa: BLE001 - skip a bad market, keep scanning
            continue
        yes = books.yes
        if yes.best_bid is None or yes.best_ask is None:
            continue
        ask = yes.best_ask.price
        if ask > max_price or ask <= Decimal("0"):
            continue
        depth = min(len(yes.bids), len(yes.asks))
        if depth < MIN_BOOK_DEPTH:
            continue
        if best is None or ask < best.best_ask:
            best = _Pick(ticker=market.id, contract_id=f"{market.id}:YES", best_ask=ask)
    if best is None:
        raise SystemExit(
            f"no open demo market with a two-sided book and best ask <= {max_price}"
        )
    return best


def pick_authorized_demo_market(ticker: str, max_price: Decimal) -> _Pick:
    """Retrieve and revalidate exactly one operator-authorized Demo ticker.

    Explicit selection is authorization to *evaluate* ``ticker``, never a
    validation bypass. The exact market must exist, identify itself by the same
    ticker, remain active, and satisfy the unchanged picker criteria.
    """
    target = ticker.strip()
    if not target or target.startswith("--"):
        raise SystemExit("--ticker must name one non-empty Kalshi Demo market")

    client = KalshiClient(base_url=DEMO_BASE_URL)
    adapter = KalshiMarketDataAdapter(client)
    try:
        raw_market = client.get_market(target)
    except Exception as exc:  # noqa: BLE001 - unavailable/invalid target -> no order
        raise SystemExit(
            f"authorized demo ticker is unavailable ({type(exc).__name__}); no order"
        ) from exc

    returned_ticker = raw_market.get("ticker")
    if returned_ticker != target:
        raise SystemExit("authorized demo ticker response is ambiguous; no order")
    status = raw_market.get("status")
    if status != "active":
        raise SystemExit(
            f"authorized demo ticker is not active (status={status!r}); no order"
        )

    try:
        books = adapter.get_order_books(target)
    except Exception as exc:  # noqa: BLE001 - book/read failure -> no order
        raise SystemExit(
            f"authorized demo ticker book is unavailable ({type(exc).__name__}); no order"
        ) from exc
    candidate = assess_candidate(target, status, books.yes, max_price)
    if not candidate.picker_eligible:
        raise SystemExit(
            f"authorized demo ticker is not eligible: {candidate.note}; no order"
        )
    best_ask = candidate.best_ask
    if best_ask is None:  # defensive fail-closed guard; eligibility should imply this
        raise SystemExit("authorized demo ticker has no best ask; no order")
    return _Pick(
        ticker=target,
        contract_id=f"{target}:YES",
        best_ask=best_ask,
    )


# --------------------------------------------------------------------------- #
# read-only candidate diagnostic (--diagnose): explains what the picker sees
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Candidate:
    """One open demo market as the picker's YES-book rule sees it. Every field is
    public market data (ticker + book aggregates) — no account/credential data."""

    ticker: str
    status: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    two_sided: bool
    bid_levels: int
    ask_levels: int
    size_at_best_ask: Decimal | None
    picker_eligible: bool
    note: str


def assess_candidate(
    ticker: str, status: str, yes_book: Any, max_price: Decimal
) -> _Candidate:
    """Score one market's YES book against the exact rule in
    :func:`pick_liquid_demo_market`: a two-sided book, ``MIN_BOOK_DEPTH`` levels
    per side, and ``0 < best_ask <= max_price``. Pure — no I/O."""
    bid_levels, ask_levels = len(yes_book.bids), len(yes_book.asks)
    two_sided = bid_levels > 0 and ask_levels > 0
    bb, ba = yes_book.best_bid, yes_book.best_ask
    best_bid = bb.price if bb is not None else None
    best_ask = ba.price if ba is not None else None
    size_at_best_ask = ba.quantity if ba is not None else None

    reasons: list[str] = []
    if not two_sided:
        reasons.append("book not two-sided")
    if best_ask is None:
        reasons.append("no best ask")
    elif best_ask <= Decimal("0"):
        reasons.append("best ask <= 0")
    elif best_ask > max_price:
        reasons.append(f"best ask {best_ask} > max-price {max_price}")
    if two_sided and min(bid_levels, ask_levels) < MIN_BOOK_DEPTH:
        reasons.append(f"depth {min(bid_levels, ask_levels)} < {MIN_BOOK_DEPTH}")

    return _Candidate(
        ticker=ticker,
        status=status,
        best_bid=best_bid,
        best_ask=best_ask,
        two_sided=two_sided,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        size_at_best_ask=size_at_best_ask,
        picker_eligible=not reasons,
        note="picker-eligible" if not reasons else "; ".join(reasons),
    )


def recommend_max_price(
    candidates: list[_Candidate], current_max_price: Decimal
) -> tuple[Decimal | None, str]:
    """Suggest a ``--max-price`` for a safe single-contract observation, or
    ``None`` when no safe suggestion exists. This is advisory only: the caller
    prints it and never applies it (raising ``--max-price`` stays an operator
    decision — see the task constraints and D-0xx).

    A market is "tradeable-shaped" here iff it is two-sided, has
    ``>= MIN_BOOK_DEPTH`` levels per side, and ``best_ask > 0`` — i.e. the
    picker would take it at a high enough ``--max-price``.

    TODO(you): implement the recommendation policy (~8-10 lines).
    Consider these cases and their trade-offs:
      * No tradeable-shaped market at all -> return ``(None, reason)``. Raising
        ``--max-price`` cannot conjure liquidity, so do not suggest a number.
      * The cheapest tradeable-shaped ``best_ask`` is already ``<=
        current_max_price`` -> the picker should already succeed; returning that
        exact ask (not a rounded-up value) documents the tightest safe bound and
        signals the earlier empty result was transient.
      * The cheapest tradeable-shaped ``best_ask`` is ``> current_max_price`` ->
        report that number in the *reason* for the operator to weigh, but think
        about whether returning it as a recommendation vs. ``None`` better
        respects "do not increase --max-price automatically".
    Keep the returned Decimal exact (no rounding that could push it above a real
    resting ask). Return a one-line human reason string in every branch.

    Policy (operator-chosen, 2026-09-10): when the cheapest tradeable-shaped ask
    is above ``current_max_price`` the function returns ``None`` and only *cites*
    that number in the reason — a ``--max-price`` increase is never surfaced as a
    recommendation, only as information for the operator to weigh.
    """
    tradeable = [
        c
        for c in candidates
        if c.two_sided
        and c.best_ask is not None
        and c.best_ask > Decimal("0")
        and min(c.bid_levels, c.ask_levels) >= MIN_BOOK_DEPTH
    ]
    if not tradeable:
        return (
            None,
            f"no open demo market has a two-sided YES book with >= "
            f"{MIN_BOOK_DEPTH} levels per side; raising --max-price cannot help",
        )
    cheapest = min(c.best_ask for c in tradeable if c.best_ask is not None)
    if cheapest <= current_max_price:
        return (
            cheapest,
            f"{len(tradeable)} market(s) already satisfy the picker rule at "
            f"--max-price {current_max_price}; tightest safe bound is best ask "
            f"{cheapest} — an earlier empty result was transient, just retry",
        )
    return (
        None,
        f"cheapest two-sided YES best ask is {cheapest}, above --max-price "
        f"{current_max_price}; raising --max-price is an operator decision, "
        f"not automatic",
    )


def _fmt_price(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _scan_open_demo_markets(
    client: KalshiClient,
    adapter: KalshiMarketDataAdapter,
    max_price: Decimal,
    pages: int,
) -> list[_Candidate]:
    """Walk ``GET /markets?status=open`` for up to ``pages`` pages of
    ``DIAG_MARKET_LIMIT`` and score each market's YES book. ``pages=1`` mirrors
    :func:`pick_liquid_demo_market` exactly; a higher value only widens the
    read-only scan, it does not change the picker."""
    candidates: list[_Candidate] = []
    cursor: str | None = None
    for _ in range(max(1, pages)):
        listing = client.list_markets(
            status="open", limit=DIAG_MARKET_LIMIT, cursor=cursor
        )
        raw_markets = listing.get("markets") if isinstance(listing, dict) else None
        if not isinstance(raw_markets, list) or not raw_markets:
            break
        for entry in raw_markets:
            if not isinstance(entry, dict):
                continue
            ticker = str(entry.get("ticker") or "").strip()
            if not ticker:
                continue
            status = str(entry.get("status") or "unknown")
            try:
                books = adapter.get_order_books(ticker)
            except Exception as exc:  # noqa: BLE001 - skip a bad market, keep scanning
                candidates.append(
                    _Candidate(
                        ticker, status, None, None, False, 0, 0, None, False,
                        f"orderbook unavailable ({type(exc).__name__})",
                    )
                )
                continue
            candidates.append(assess_candidate(ticker, status, books.yes, max_price))
        raw_cursor = listing.get("cursor") if isinstance(listing, dict) else None
        cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
        if cursor is None:
            break
    return candidates


def run_diagnostic(max_price: Decimal, pages: int = 1) -> int:
    """READ-ONLY: list open demo markets and report, per candidate, the YES-book
    facts the picker uses. Public market-data endpoints only — no auth, no
    order, no account data, no production host."""
    print(
        "Kalshi DEMO candidate diagnostic — READ-ONLY "
        "(public GET /markets* on the demo host; no credentials, no order)\n"
    )
    client = KalshiClient(base_url=DEMO_BASE_URL)
    adapter = KalshiMarketDataAdapter(client)

    try:
        candidates = _scan_open_demo_markets(client, adapter, max_price, pages)
    except Exception as exc:  # noqa: BLE001 - report, do not crash the diagnostic
        print(f"market-data scan failed: {type(exc).__name__}")
        return 2
    if not candidates:
        print("Candidates:\n  (none — GET /markets?status=open returned no markets)")
        return 1

    candidates.sort(
        key=lambda c: (
            not c.picker_eligible,
            c.best_ask if c.best_ask is not None else Decimal("999"),
        )
    )

    print(
        f"Candidates: ({len(candidates)} open demo markets scanned "
        f"across up to {max(1, pages)} page(s) of {DIAG_MARKET_LIMIT})"
    )
    header = (
        f"  {'ticker':<34} {'status':<10} {'bid':>8} {'ask':>8} "
        f"{'2-sided':>7} {'lvls b/a':>9} {'sz@ask':>8}  note"
    )
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for c in candidates:
        print(
            f"  {c.ticker:<34} {c.status:<10} "
            f"{_fmt_price(c.best_bid):>8} {_fmt_price(c.best_ask):>8} "
            f"{('yes' if c.two_sided else 'no'):>7} "
            f"{f'{c.bid_levels}/{c.ask_levels}':>9} "
            f"{('—' if c.size_at_best_ask is None else str(c.size_at_best_ask)):>8}  "
            f"{c.note}"
        )

    eligible = [c for c in candidates if c.picker_eligible]
    print(
        f"\n  -> {len(eligible)} market(s) satisfy the picker rule at "
        f"--max-price {max_price}"
    )

    suggested, reason = recommend_max_price(candidates, max_price)
    print("\nRecommended max-price:")
    print(f"  {'keep --max-price unchanged' if suggested is None else suggested}")
    print("Reason:")
    print(f"  {reason}")
    print(
        "\n(advisory only — this diagnostic never changes --max-price, submits "
        "an order, or touches credentials/production.)"
    )
    return 0


# --------------------------------------------------------------------------- #
# the observation
# --------------------------------------------------------------------------- #


def _fresh_health(now: datetime) -> FeedHealth:
    return FeedHealth(
        status=HealthStatus.HEALTHY, reason="", as_of=now, last_update=now, last_sequence=1
    )


def current_market_position(
    broker: KalshiDemoLiveBroker, *, contract_id: str, ticker: str, now: datetime
) -> dict[str, PositionRow]:
    """Read the account's **current** demo position for ``ticker`` through the
    existing broker path and return it keyed by the order's ``contract_id`` for
    the M2.5 risk check.

    Fail-closed: ``broker.get_positions`` already raises
    :class:`DemoCapabilityError` on a failed / malformed / unmappable
    ``market_positions`` body; this adds the "two rows for one ticker"
    ambiguity. A market with no position row → an explicit ``0`` (Kalshi
    returns ``market_positions: []`` for a flat account — K-TR-OBS-04)."""
    rows = broker.get_positions(now=now)
    matches = [p for p in rows if p.contract_id == ticker]
    if len(matches) > 1:
        raise DemoExecutionError(
            f"ambiguous demo position: {len(matches)} market_positions rows for {ticker!r}"
        )
    signed_qty = matches[0].quantity if matches else Decimal(0)
    return {
        contract_id: PositionRow(
            venue="kalshi",
            contract_id=contract_id,
            quantity=signed_qty,
            avg_price=Decimal(0),
            as_of=now,
        )
    }


def _venue_step(name: str, body: Any) -> dict[str, Any]:
    """A raw venue-response body through the D-024 fail-safe allowlist."""
    return {"name": name, "body": demo.sanitise_body(body)}


def _outcome_step(name: str, outcome: Any) -> dict[str, Any]:
    return {"name": name, "outcome": _safe_outcome(outcome.to_evidence_dict())}


def _write_blocker(reason: str, session_start: datetime) -> None:
    """Sanitised evidence for a run that fails closed before submitting."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "SUMMARY.json").write_text(
        json.dumps(
            {
                "venue": "kalshi",
                "environment": "demo",
                "result": "BLOCKED — order not submitted",
                "reason": reason,
                "session_start_utc": session_start.isoformat(),
                "session_end_utc": utc_now().isoformat(),
                "safety": [
                    "DEMO host only; no production call; LIVE_TRADING untouched",
                    "no order was submitted (fail-closed before orch.execute)",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def run_observation(max_price: Decimal, ticker: str) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session_start = utc_now()

    # Public Demo market data only. Resolve the exact authorized target before
    # loading execution credentials or constructing any authenticated client.
    pick = pick_authorized_demo_market(ticker, max_price)

    key_id = read_keychain_password(KEYCHAIN_SERVICE)
    signer = OpensslRsaPssSigner(PEM_PATH)
    transport = KalshiDemoRestTransport(
        base_url=DEMO_BASE_URL, api_key_id=key_id, signer=signer
    )
    broker = KalshiDemoLiveBroker(
        transport,
        gate=LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE),
    )
    risk = RiskManager(_probe_risk_limits())
    recorder = Recorder.open(
        str(OUT_DIR / "recording.duckdb"),
        session_id=f"demo-exec-{int(session_start.timestamp())}",
        opened_at=session_start,
    )
    orch = DemoExecutionOrchestrator(
        broker=broker, risk=risk, recorder=recorder, clock=utc_now
    )

    client_order_id = f"pma-demo-exec-{int(session_start.timestamp())}"
    intent = LiveOrderRequest(
        client_order_id=client_order_id,
        venue="kalshi",
        contract_id=pick.contract_id,
        side="buy",
        order_type="limit",
        quantity=ORDER_QUANTITY,
        limit_price=pick.best_ask,  # crossable -> taker
        time_in_force="gtc",
    )
    print(f"DEMO market  = {pick.ticker}  best_ask={pick.best_ask}  qty={ORDER_QUANTITY}")
    print(f"DEMO client_order_id = {client_order_id} (synthetic)")

    # Pre-submit: read the account's ACTUAL current position for this market and
    # feed it into the risk check. Fail closed (no order) if it cannot be read
    # or mapped unambiguously.
    try:
        positions = current_market_position(
            broker, contract_id=intent.contract_id, ticker=pick.ticker, now=utc_now()
        )
    except Exception as exc:  # noqa: BLE001 - any read/parse/ambiguity failure -> no submit
        recorder.close()
        _write_blocker(
            f"pre-submit position read failed ({type(exc).__name__}); order NOT submitted",
            session_start,
        )
        print(f"BLOCKED: pre-submit position read failed ({type(exc).__name__}); no order placed")
        return 2
    print(
        "current position for this market: "
        f"{next(iter(positions.values())).quantity} contract(s)"
    )

    steps: list[dict[str, Any]] = []
    outcome = None
    left_resting = False
    try:
        outcome = orch.execute(
            intent, positions=positions, health=_fresh_health(utc_now())
        )
        steps.append(_outcome_step("01_execute", outcome))
        if not outcome.submitted:
            print(
                f"not submitted: {outcome.blocked_reason}; "
                f"reasons={outcome.risk_decision.reasons}"
            )
        else:
            time.sleep(2)  # let the order settle onto the shard book / portfolio
            outcome = orch.reconcile(outcome)
            steps.append(_outcome_step("02_reconcile", outcome))
            state = outcome.order_status.state.value if outcome.order_status else "unknown"
            print(f"venue order state after submit: {state}")
            steps.append(_venue_step("03_fills", transport.get_fills().body))
            steps.append(_venue_step("04_positions", transport.get_positions().body))
            if outcome.order_status is not None and outcome.order_status.remaining_quantity > 0:
                outcome = orch.cancel(outcome)
                steps.append(_outcome_step("05_cancel", outcome))
                time.sleep(2)
                outcome = orch.reconcile(outcome)
                steps.append(_outcome_step("06_reconcile_after_cancel", outcome))
    finally:
        # best-effort: if an order reached the venue, make one more cancel
        if outcome is not None and outcome.ack is not None and outcome.ack.venue_order_id:
            try:
                transport.cancel_order(
                    outcome.ack.venue_order_id, market_ticker=pick.ticker
                )
            except Exception:  # noqa: BLE001 - cleanup must not mask the result
                pass

    # venue-vs-local reconciliation
    recon = _reconcile_block(outcome, transport, pick)
    if recon.get("left_resting"):
        left_resting = True

    session_end = utc_now()
    summary = {
        "venue": "kalshi",
        "environment": "demo",
        "path": "demo_execution.DemoExecutionOrchestrator + KalshiDemoRestTransport",
        "market_ticker": "<redacted>",
        "session_start_utc": session_start.isoformat(),
        "session_end_utc": session_end.isoformat(),
        "wall_elapsed_s": round((session_end - session_start).total_seconds(), 3),
        "order": {
            "quantity": str(ORDER_QUANTITY),
            "limit_price": "<redacted>",
            "side": "buy",
            "time_in_force": "gtc",
        },
        "outcome": None if outcome is None else _safe_outcome(outcome.to_evidence_dict()),
        "venue_vs_local": recon,
        "steps": steps,
        "safety": [
            "DEMO host only (assert_demo_host); production Kalshi never called",
            "no production credentials; LIVE_TRADING never read or set; no fund movement",
            "no Polymarket US; single 1-contract order; remainder cancelled",
        ],
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    recorder.close()
    print(f"wrote sanitised evidence to {OUT_DIR / 'SUMMARY.json'}")
    if left_resting:
        print("\n*** WARNING: a demo order may still be resting — check manually. ***")
        return 1
    return 0


def _reconcile_block(
    outcome: Any, transport: KalshiDemoRestTransport, pick: _Pick
) -> dict[str, Any]:
    if outcome is None or outcome.ack is None or not outcome.ack.accepted:
        return {"reached_venue": False}
    try:
        order = transport.get_order(outcome.ack.venue_order_id, market_ticker=pick.ticker)
        positions = transport.get_positions()
        fills = transport.get_fills()
    except Exception as exc:  # noqa: BLE001
        # cannot confirm the order is closed -> assume the worst and warn.
        return {
            "reached_venue": True,
            "reconcile_error": type(exc).__name__,
            "left_resting": True,
        }
    _nested = order.body.get("order")
    venue_order = _nested if isinstance(_nested, dict) else order.body
    venue_status = venue_order.get("status") if isinstance(venue_order, dict) else None
    return {
        "reached_venue": True,
        "venue_order_status": demo.sanitise_body(venue_status),
        "venue_positions_shape": (
            sorted(positions.body) if isinstance(positions.body, dict) else None
        ),
        "venue_fills_key_present": "fills" in (fills.body or {}),
        "local_position_is_flat": (
            outcome.local_position is None or outcome.local_position.quantity == Decimal(0)
        ),
        "left_resting": venue_status
        not in ("canceled", "cancelled", "executed", None, "<redacted>"),
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--diagnose" in args:
        mode = "--diagnose"
    elif "--observe" in args:
        mode = "--observe"
    else:
        mode = "--check"
    max_price = DEFAULT_MAX_PRICE
    if "--max-price" in args:
        max_price = Decimal(args[args.index("--max-price") + 1])
    pages = 1
    if "--pages" in args:
        pages = max(1, int(args[args.index("--pages") + 1]))

    ticker: str | None = None
    if mode == "--observe":
        if args.count("--ticker") != 1:
            print(
                "Refusing to place a demo order: --observe requires exactly one "
                "--ticker KX... argument.\n",
                file=sys.stderr,
            )
            return 2
        ticker_index = args.index("--ticker")
        if ticker_index + 1 >= len(args):
            print(
                "Refusing to place a demo order: --ticker requires a value.\n",
                file=sys.stderr,
            )
            return 2
        ticker = args[ticker_index + 1].strip()
        if not ticker or ticker.startswith("--"):
            print(
                "Refusing to place a demo order: --ticker requires a non-empty value.\n",
                file=sys.stderr,
            )
            return 2

    # --diagnose is read-only public market data: no preflight, no credentials.
    if mode == "--diagnose":
        return run_diagnostic(max_price, pages)

    report = preflight()
    print("preflight:")
    for key, value in report.items():
        print(f"  {key}: {value}")
    print()

    if mode == "--check":
        if report["ready"]:
            print(
                f"Ready. {RUN_ENV_GUARD}=1 python "
                "scripts/observe_kalshi_demo_execution.py --observe "
                "--ticker KX...\n"
            )
        else:
            print(
                "Not ready. Need: openssl on PATH, "
                f"{PEM_PATH} (chmod 600), Keychain '{KEYCHAIN_SERVICE}', demo host guard.\n"
            )
        return 0

    if report["env_guard_set"] is not True:
        print(f"Refusing to place a demo order: set {RUN_ENV_GUARD}=1.\n", file=sys.stderr)
        return 2
    if not report["ready"]:
        print("Refusing to connect: preflight did not pass.\n", file=sys.stderr)
        return 2
    assert ticker is not None  # validated above for --observe
    return run_observation(max_price, ticker)


if __name__ == "__main__":
    sys.exit(main())
