"""Safety-review regression tests for ``scripts/observe_kalshi_demo_execution.py``
— the pending first real Kalshi **demo** execution observation.

No network: only the pure helpers, constants, arg handling, and the evidence
redactor are exercised. Every check maps to a review item ("is the first real
demo order run bounded and safe enough to execute?").
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import observe_kalshi_demo_execution as harness
import pytest
from demo_execution_support import T0, FakeDemoTransport

from prediction_market_arbitrage.adapters.kalshi import DEMO_BASE_URL
from prediction_market_arbitrage.demo_execution import (
    DemoExecutionError,
    DemoExecutionOrchestrator,
    DemoResponse,
    KalshiDemoLiveBroker,
    assert_demo_host,
)
from prediction_market_arbitrage.live_broker import REQUIRED_PHRASE, LiveTradingGate
from prediction_market_arbitrage.live_broker.models import LiveOrderRequest
from prediction_market_arbitrage.recorder import Recorder
from prediction_market_arbitrage.risk import RiskManager

# --------------------------------------------------------------------------- #
# default mode = --check, no network, no order
# --------------------------------------------------------------------------- #


def _ready_report(**over: Any) -> dict[str, Any]:
    report = {
        "openssl_on_path": True,
        "demo_private_key_present": True,
        "demo_keychain_key_id": "present",
        "demo_base_url": DEMO_BASE_URL,
        "demo_host_guard_passes": True,
        "env_guard_set": False,
        "ready": True,
    }
    report.update(over)
    return report


def test_default_mode_is_check_and_never_runs_the_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness, "preflight", _ready_report)
    monkeypatch.setattr(
        harness, "run_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert harness.main([]) == 0


def test_observe_refuses_without_the_env_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "preflight", lambda: _ready_report(env_guard_set=False))
    monkeypatch.setattr(
        harness, "run_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert harness.main(["--observe", "--ticker", "KXSYNTH-TARGET"]) == 2


def test_observe_refuses_when_preflight_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        harness, "preflight", lambda: _ready_report(env_guard_set=True, ready=False)
    )
    monkeypatch.setattr(
        harness, "run_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert harness.main(["--observe", "--ticker", "KXSYNTH-TARGET"]) == 2


def test_observe_requires_exactly_one_explicit_ticker_before_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness, "preflight",
        lambda: (_ for _ in ()).throw(AssertionError("preflight must not run")),
    )
    assert harness.main(["--observe"]) == 2
    assert harness.main(["--observe", "--ticker"]) == 2
    assert (
        harness.main(
            ["--observe", "--ticker", "KXSYNTH-A", "--ticker", "KXSYNTH-B"]
        )
        == 2
    )


def test_observe_routes_the_explicit_ticker_and_exact_max_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness, "preflight", lambda: _ready_report(env_guard_set=True)
    )
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        harness,
        "run_observation",
        lambda max_price, ticker: seen.update(
            max_price=max_price, ticker=ticker
        )
        or 0,
    )
    assert (
        harness.main(
            ["--observe", "--ticker", "KXSYNTH-TARGET", "--max-price", "0.60"]
        )
        == 0
    )
    assert seen == {
        "max_price": Decimal("0.60"),
        "ticker": "KXSYNTH-TARGET",
    }


# --------------------------------------------------------------------------- #
# DEMO host pin + credential boundary
# --------------------------------------------------------------------------- #


def test_base_url_is_a_demo_host_not_production() -> None:
    assert assert_demo_host(DEMO_BASE_URL) == DEMO_BASE_URL
    assert "demo.kalshi.co" in DEMO_BASE_URL
    assert "external-api.kalshi.com" not in DEMO_BASE_URL


def test_credentials_are_demo_scoped_only() -> None:
    assert harness.KEYCHAIN_SERVICE == "pma-kalshi-demo-api-key-id"
    pem = str(harness.PEM_PATH)
    assert "demo" in pem and "prod" not in pem
    assert "prod" not in harness.KEYCHAIN_SERVICE


def test_source_never_references_production_or_the_live_trading_switch() -> None:
    import ast
    import inspect

    src = inspect.getsource(harness)
    # no production host / prod credential service anywhere
    assert "external-api.kalshi.com" not in src
    assert "pma-kalshi-prod" not in src
    # the LIVE_TRADING switch is never touched in *code* (docstring may mention it)
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    consts = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "LIVE_TRADING_ENABLED" not in names | attrs
    assert "LIVE_TRADING_ENV_VAR" not in names | attrs
    assert not any("PMA_LIVE_TRADING" in c or "LIVE_TRADING" == c for c in consts)


# --------------------------------------------------------------------------- #
# order bounds
# --------------------------------------------------------------------------- #


def test_order_is_exactly_one_contract_and_price_is_bounded() -> None:
    assert harness.ORDER_QUANTITY == Decimal("1")
    assert harness.DEFAULT_MAX_PRICE == Decimal("0.60")


def test_probe_risk_limits_are_strict() -> None:
    limits = harness._probe_risk_limits()
    assert limits.max_order_size == Decimal("1")
    assert limits.max_position == Decimal("1")
    assert limits.max_daily_loss is not None and limits.max_daily_loss <= Decimal("2")


def test_market_filter_bounds_the_limit_price_by_max_price() -> None:
    # the picker only accepts a best ask in (0, max_price]; the intent's
    # limit_price is that best ask verbatim (see run_observation).
    import inspect

    src = inspect.getsource(harness.pick_liquid_demo_market)
    assert "ask > max_price" in src and "ask <= Decimal" in src
    assert "limit_price=pick.best_ask" in inspect.getsource(harness.run_observation)


# --------------------------------------------------------------------------- #
# evidence sanitisation
# --------------------------------------------------------------------------- #


_RAW_OUTCOME = {
    "client_order_id": "pma-demo-exec-1757000000",
    "ticker": "KXREALDEMOMARKET-SHARD1-ABC",
    "side": "buy",
    "order_type": "limit",
    "risk_allowed": True,
    "risk_checks_run": ["kill_switch", "max_order_size", "max_position", "max_daily_loss"],
    "risk_reasons": ["projected position 2 for KXREALDEMOMARKET-SHARD1-ABC:YES exceeds max 1"],
    "submitted": True,
    "duplicate": False,
    "blocked_reason": "",
    "venue_accepted": True,
    "venue_state": "submitted",
    "order_status_state": "resting",
    "cancelled": True,
    "reconciled": True,
}


def test_safe_outcome_drops_ticker_client_order_id_and_reason_strings() -> None:
    import json

    safe = harness._safe_outcome(_RAW_OUTCOME)
    blob = json.dumps(safe)
    assert "KXREALDEMOMARKET" not in blob
    assert "pma-demo-exec-1757000000" not in blob
    assert "projected position" not in blob
    assert "ticker" not in safe and "client_order_id" not in safe
    assert safe["risk_reason_count"] == 1
    assert safe["submitted"] is True
    assert safe["risk_checks_run"] == _RAW_OUTCOME["risk_checks_run"]


def test_safe_outcome_key_set_is_a_fixed_allowlist() -> None:
    safe = harness._safe_outcome(_RAW_OUTCOME)
    assert set(safe) == set(harness._SAFE_OUTCOME_KEYS) | {"risk_reason_count"}


def test_safe_execution_outcome_persists_only_allowlisted_rejection_metadata() -> None:
    tr = FakeDemoTransport(
        create=DemoResponse(
            401,
            {
                "code": "permission_denied",
                "message": "contains unrestricted venue text",
                "ticker": "KXSECRET-TICKER",
            },
        )
    )
    outcome = _orch(_broker(tr)).execute(
        _INTENT,
        positions={},
        health=harness._fresh_health(T0),
    )

    safe = harness._safe_execution_outcome(outcome)
    assert safe["venue_rejection"] == {
        "http_status": "401",
        "venue_error_category": "authentication_or_authorization",
        "venue_error_code": "permission_denied",
    }
    assert "unrestricted venue text" not in str(safe)
    assert "KXSECRET" not in str(safe)


def test_rejection_evidence_boundary_revalidates_values() -> None:
    assert harness._safe_rejection(
        {
            "http_status": "401; leaked",
            "venue_error_category": "arbitrary_category",
            "venue_error_code": "unsafe code with spaces",
            "message": "must never persist",
        }
    ) == {}


# --------------------------------------------------------------------------- #
# pre-submit real position read -> risk projection (fail closed on a bad read)
# --------------------------------------------------------------------------- #

_TICKER = "KXDEMO-T1"
_INTENT = LiveOrderRequest(
    client_order_id="pma-demo-exec-1",
    venue="kalshi",
    contract_id=f"{_TICKER}:YES",
    side="buy",
    order_type="limit",
    quantity=Decimal("1"),
    limit_price=Decimal("0.05"),
    time_in_force="gtc",
)


def _positions_body(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {"market_positions": rows, "event_positions": [], "cursor": ""}


def _broker(transport: FakeDemoTransport) -> KalshiDemoLiveBroker:
    return KalshiDemoLiveBroker(
        transport,
        gate=LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE),
    )


def _orch(broker: KalshiDemoLiveBroker) -> DemoExecutionOrchestrator:
    return DemoExecutionOrchestrator(
        broker=broker,
        risk=RiskManager(harness._probe_risk_limits()),
        recorder=Recorder.open(":memory:", session_id="t", opened_at=T0),
        clock=lambda: T0,
    )


def test_existing_position_is_included_in_projected_position_risk() -> None:
    # flat -> projected 1 -> allowed (order reaches the venue)
    flat = FakeDemoTransport(positions=DemoResponse(200, _positions_body([])))
    b = _broker(flat)
    pos = harness.current_market_position(
        b, contract_id=_INTENT.contract_id, ticker=_TICKER, now=T0
    )
    assert pos[_INTENT.contract_id].quantity == Decimal("0")
    assert _orch(b).execute(
        _INTENT, positions=pos, health=harness._fresh_health(T0)
    ).submitted is True

    # 1 held -> projected 2 -> blocked purely because the existing position is
    # folded into the projection
    held = FakeDemoTransport(
        positions=DemoResponse(200, _positions_body([{"ticker": _TICKER, "position_fp": "1"}]))
    )
    b2 = _broker(held)
    pos2 = harness.current_market_position(
        b2, contract_id=_INTENT.contract_id, ticker=_TICKER, now=T0
    )
    assert pos2[_INTENT.contract_id].quantity == Decimal("1")
    out = _orch(b2).execute(_INTENT, positions=pos2, health=harness._fresh_health(T0))
    assert out.submitted is False
    assert any("projected position" in r for r in out.risk_decision.reasons)
    assert "create_order" not in held.call_names()


def test_existing_position_at_the_limit_blocks_the_order() -> None:
    tr = FakeDemoTransport(
        positions=DemoResponse(200, _positions_body([{"ticker": _TICKER, "position_fp": "1"}]))
    )
    b = _broker(tr)
    pos = harness.current_market_position(
        b, contract_id=_INTENT.contract_id, ticker=_TICKER, now=T0
    )
    out = _orch(b).execute(_INTENT, positions=pos, health=harness._fresh_health(T0))
    assert out.submitted is False
    assert out.blocked_reason == "risk_rejected"
    assert tr.call_names().count("create_order") == 0


@pytest.mark.parametrize(
    "positions_response",
    [
        DemoResponse(500, {"error": {"code": "x", "message": "y"}}),  # failed read
        DemoResponse(200, {"event_positions": [], "cursor": ""}),  # no market_positions
        DemoResponse(200, _positions_body([{"ticker": _TICKER}])),  # row missing position_fp
        DemoResponse(200, _positions_body([{"position_fp": "1"}])),  # row missing ticker
        DemoResponse(  # two rows for one ticker -> ambiguous
            200,
            _positions_body(
                [{"ticker": _TICKER, "position_fp": "1"}, {"ticker": _TICKER, "position_fp": "2"}]
            ),
        ),
    ],
)
def test_bad_pre_submit_position_read_fails_closed_with_no_create(
    positions_response: DemoResponse,
) -> None:
    tr = FakeDemoTransport(positions=positions_response)
    with pytest.raises(DemoExecutionError):
        harness.current_market_position(
            _broker(tr), contract_id=_INTENT.contract_id, ticker=_TICKER, now=T0
        )
    assert "create_order" not in tr.call_names()  # no POST /orders on a bad read


def test_safe_outcome_handles_a_blocked_run_without_a_venue_ack() -> None:
    blocked = {
        "client_order_id": "pma-demo-exec-x",
        "ticker": "KXSECRET-1",
        "risk_allowed": False,
        "risk_checks_run": ["kill_switch"],
        "risk_reasons": ["kill switch engaged: manual halt"],
        "submitted": False,
        "duplicate": False,
        "blocked_reason": "risk_rejected",
        "venue_accepted": None,
        "venue_state": None,
        "order_status_state": None,
        "cancelled": False,
        "reconciled": False,
    }
    safe = harness._safe_outcome(blocked)
    assert "KXSECRET-1" not in str(safe)
    assert safe["blocked_reason"] == "risk_rejected"
    assert safe["risk_reason_count"] == 1


# --------------------------------------------------------------------------- #
# --diagnose: read-only candidate diagnostic (no network in these tests)
# --------------------------------------------------------------------------- #

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class _Lvl:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class _Book:
    """Minimal stand-in for a normalized YES ``OrderBook`` — only the surface
    ``assess_candidate`` reads."""

    bids: tuple[_Lvl, ...]
    asks: tuple[_Lvl, ...]

    @property
    def best_bid(self) -> _Lvl | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> _Lvl | None:
        return self.asks[0] if self.asks else None


def _two_sided_book(ask: str, *, size: str = "50", depth: int = 2) -> _Book:
    asks = tuple(
        _Lvl(Decimal(ask) + Decimal("0.01") * i, Decimal(size)) for i in range(depth)
    )
    bids = tuple(
        _Lvl(Decimal("0.001") * (depth - i), Decimal(size)) for i in range(depth)
    )
    return _Book(bids=bids, asks=asks)


class _ExactTargetClient:
    def __init__(self, market: dict[str, str] | Exception) -> None:
        self.market = market
        self.requested: list[str] = []

    def get_market(self, ticker: str) -> dict[str, str]:
        self.requested.append(ticker)
        if isinstance(self.market, Exception):
            raise self.market
        return self.market

    def list_markets(self, **_kwargs: Any) -> Any:
        raise AssertionError("explicit targeting must not depend on discovery ordering")


class _ExactTargetAdapter:
    def __init__(self, book: _Book | Exception) -> None:
        self.book = book
        self.requested: list[str] = []

    def get_order_books(self, ticker: str) -> Any:
        self.requested.append(ticker)
        if isinstance(self.book, Exception):
            raise self.book
        return SimpleNamespace(yes=self.book)


def _install_exact_target_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    market: dict[str, str] | Exception,
    book: _Book | Exception,
) -> tuple[_ExactTargetClient, _ExactTargetAdapter]:
    client = _ExactTargetClient(market)
    adapter = _ExactTargetAdapter(book)
    monkeypatch.setattr(harness, "KalshiClient", lambda **_kwargs: client)
    monkeypatch.setattr(harness, "KalshiMarketDataAdapter", lambda _client: adapter)
    return client, adapter


def test_explicit_valid_ticker_is_retrieved_exactly_without_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = "KXSYNTH-TARGET"
    client, adapter = _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": ticker, "status": "active"},
        book=_two_sided_book("0.40", size="25"),
    )
    pick = harness.pick_authorized_demo_market(ticker, Decimal("0.60"))
    assert pick == harness._Pick(ticker, f"{ticker}:YES", Decimal("0.40"))
    assert client.requested == [ticker]
    assert adapter.requested == [ticker]


def test_explicit_ticker_not_found_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_exact_target_fakes(
        monkeypatch, market=RuntimeError("not found"), book=_two_sided_book("0.40")
    )
    with pytest.raises(SystemExit, match="unavailable"):
        harness.pick_authorized_demo_market("KXSYNTH-MISSING", Decimal("0.60"))


def test_explicit_closed_ticker_fails_before_reading_its_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = "KXSYNTH-CLOSED"
    _, adapter = _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": ticker, "status": "closed"},
        book=_two_sided_book("0.40"),
    )
    with pytest.raises(SystemExit, match="not active"):
        harness.pick_authorized_demo_market(ticker, Decimal("0.60"))
    assert adapter.requested == []


def test_explicit_ticker_response_mismatch_fails_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, adapter = _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": "KXSYNTH-OTHER", "status": "active"},
        book=_two_sided_book("0.40"),
    )
    with pytest.raises(SystemExit, match="ambiguous"):
        harness.pick_authorized_demo_market("KXSYNTH-TARGET", Decimal("0.60"))
    assert adapter.requested == []


def test_explicit_ticker_above_price_cap_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = "KXSYNTH-EXPENSIVE"
    _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": ticker, "status": "active"},
        book=_two_sided_book("0.61"),
    )
    with pytest.raises(SystemExit, match=r"best ask 0\.61 > max-price 0\.60"):
        harness.pick_authorized_demo_market(ticker, Decimal("0.60"))


def test_explicit_ticker_with_insufficient_depth_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = "KXSYNTH-THIN"
    _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": ticker, "status": "active"},
        book=_two_sided_book("0.40", depth=1),
    )
    with pytest.raises(SystemExit, match="depth 1 < 2"):
        harness.pick_authorized_demo_market(ticker, Decimal("0.60"))


def test_explicit_ticker_with_one_sided_book_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = "KXSYNTH-ONE-SIDED"
    _install_exact_target_fakes(
        monkeypatch,
        market={"ticker": ticker, "status": "active"},
        book=_Book(
            bids=(_Lvl(Decimal("0.30"), Decimal("10")),),
            asks=(),
        ),
    )
    with pytest.raises(SystemExit, match="book not two-sided"):
        harness.pick_authorized_demo_market(ticker, Decimal("0.60"))


def test_discovery_picker_behavior_is_unchanged_without_explicit_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markets = (
        SimpleNamespace(id="KXSYNTH-FIRST"),
        SimpleNamespace(id="KXSYNTH-CHEAPER"),
    )
    books = {
        "KXSYNTH-FIRST": _two_sided_book("0.40"),
        "KXSYNTH-CHEAPER": _two_sided_book("0.30"),
    }

    class _DiscoveryAdapter:
        def __init__(self, _client: Any) -> None:
            pass

        def list_markets(self, **kwargs: Any) -> Any:
            assert kwargs == {"status": "open", "limit": harness.DIAG_MARKET_LIMIT}
            return SimpleNamespace(markets=markets)

        def get_order_books(self, ticker: str) -> Any:
            return SimpleNamespace(yes=books[ticker])

    monkeypatch.setattr(harness, "KalshiClient", lambda **_kwargs: object())
    monkeypatch.setattr(harness, "KalshiMarketDataAdapter", _DiscoveryAdapter)
    assert harness.pick_liquid_demo_market(Decimal("0.60")) == harness._Pick(
        "KXSYNTH-CHEAPER", "KXSYNTH-CHEAPER:YES", Decimal("0.30")
    )


def test_explicit_target_flow_keeps_position_and_orchestrator_checks_before_submit() -> None:
    import inspect

    source = inspect.getsource(harness.run_observation)
    position_check = source.index("current_market_position(")
    orchestrator_execute = source.index("orch.execute(")
    assert position_check < orchestrator_execute
    assert "pick_authorized_demo_market(ticker, max_price)" in source
    assert "KalshiDemoLiveBroker(" in source


def test_diagnose_is_a_read_only_mode_that_skips_preflight_and_the_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness, "preflight",
        lambda: (_ for _ in ()).throw(AssertionError("preflight must not run")),
    )
    monkeypatch.setattr(
        harness, "run_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        harness, "run_diagnostic",
        lambda max_price, pages=1: seen.update(max_price=max_price, pages=pages) or 0,
    )
    assert harness.main(["--diagnose", "--max-price", "0.42", "--pages", "3"]) == 0
    assert seen == {"max_price": Decimal("0.42"), "pages": 3}


def test_min_book_depth_constant_is_the_rule_the_picker_enforces() -> None:
    import inspect

    assert harness.MIN_BOOK_DEPTH == 2
    assert "MIN_BOOK_DEPTH" in inspect.getsource(harness.pick_liquid_demo_market)


def test_assess_candidate_marks_a_one_sided_book_ineligible() -> None:
    book = _Book(bids=(_Lvl(Decimal("0.30"), Decimal("10")),), asks=())
    c = harness.assess_candidate("KXSYNTH-1", "active", book, Decimal("0.60"))
    assert c.two_sided is False
    assert c.picker_eligible is False
    assert c.best_ask is None and c.size_at_best_ask is None
    assert "two-sided" in c.note


def test_assess_candidate_accepts_a_two_sided_in_range_book_and_reports_ask_size() -> None:
    c = harness.assess_candidate(
        "KXSYNTH-2", "active", _two_sided_book("0.40", size="25"), Decimal("0.60")
    )
    assert c.picker_eligible is True
    assert c.two_sided is True
    assert c.best_ask == Decimal("0.40")
    assert c.size_at_best_ask == Decimal("25")
    assert c.note == "picker-eligible"


def test_assess_candidate_rejects_an_ask_above_max_price() -> None:
    c = harness.assess_candidate(
        "KXSYNTH-3", "active", _two_sided_book("0.75"), Decimal("0.60")
    )
    assert c.picker_eligible is False
    assert "> max-price" in c.note


def test_assess_candidate_rejects_a_two_sided_book_thinner_than_min_depth() -> None:
    c = harness.assess_candidate(
        "KXSYNTH-4", "active", _two_sided_book("0.20", depth=1), Decimal("0.60")
    )
    assert c.two_sided is True
    assert c.picker_eligible is False
    assert f"< {harness.MIN_BOOK_DEPTH}" in c.note


def _candidate(**over: Any) -> Any:
    base: dict[str, Any] = dict(
        ticker="KXSYNTH-X",
        status="active",
        best_bid=Decimal("0.39"),
        best_ask=Decimal("0.40"),
        two_sided=True,
        bid_levels=2,
        ask_levels=2,
        size_at_best_ask=Decimal("10"),
        picker_eligible=True,
        note="picker-eligible",
    )
    base.update(over)
    return harness._Candidate(**base)


def test_recommend_max_price_returns_none_when_nothing_is_two_sided() -> None:
    cands = [
        _candidate(two_sided=False, best_ask=None, picker_eligible=False, ask_levels=0),
    ]
    value, reason = harness.recommend_max_price(cands, Decimal("0.60"))
    assert value is None
    assert "two-sided" in reason and "cannot help" in reason


def test_recommend_max_price_returns_the_tightest_bound_when_already_satisfiable() -> None:
    cands = [_candidate(best_ask=Decimal("0.55")), _candidate(best_ask=Decimal("0.30"))]
    value, reason = harness.recommend_max_price(cands, Decimal("0.60"))
    assert value == Decimal("0.30")  # exact cheapest ask, no rounding
    assert "0.30" in reason


def test_recommend_max_price_never_suggests_raising_above_the_current_bound() -> None:
    # cheapest two-sided ask is 0.75, above the 0.60 bound -> None, cite the number
    cands = [_candidate(best_ask=Decimal("0.75"), picker_eligible=False,
                        note="best ask 0.75 > max-price 0.60")]
    value, reason = harness.recommend_max_price(cands, Decimal("0.60"))
    assert value is None
    assert "0.75" in reason
    assert "operator decision" in reason
