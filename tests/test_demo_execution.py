"""Deterministic offline tests for the M3.5 Kalshi **DEMO** execution
orchestrator. No network — every venue response is an injected
``FakeDemoTransport`` script.

Proves the safety contract:
- a production host / base URL is rejected at construction;
- a risk rejection (kill switch, position / order-size / daily-loss limit,
  data-freshness) prevents any broker call;
- a duplicate intent (local guard *and* venue 409) does not resubmit;
- the recorder captures the intent → decision → submit → cancel → reconcile
  lifecycle;
- reconciliation is deterministic given identical fake responses;
- missing / ambiguous venue state fails closed.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from demo_execution_support import DEMO_URL, PROD_URL, T0, FakeDemoTransport

from prediction_market_arbitrage.demo_execution import (
    DemoCapabilityError,
    DemoExecutionError,
    DemoExecutionOrchestrator,
    DemoHostError,
    DemoResponse,
    KalshiDemoLiveBroker,
    assert_demo_host,
)
from prediction_market_arbitrage.live_broker import (
    REQUIRED_PHRASE,
    KalshiLiveBroker,
    KalshiTradingCredentials,
    LiveTradingGate,
)
from prediction_market_arbitrage.live_broker.models import LiveOrderRequest
from prediction_market_arbitrage.recorder import Recorder
from prediction_market_arbitrage.risk import RiskLimits, RiskManager

D = Decimal
_CID = "KXDEMO-T1:YES"


def _armed() -> LiveTradingGate:
    return LiveTradingGate(enabled=True, confirmation_phrase=REQUIRED_PHRASE)


def _intent(client_order_id: str = "pma-demo-1", *, quantity: str = "1") -> LiveOrderRequest:
    return LiveOrderRequest(
        client_order_id=client_order_id,
        venue="kalshi",
        contract_id=_CID,
        side="buy",
        order_type="limit",
        quantity=D(quantity),
        limit_price=D("0.05"),
        time_in_force="gtc",
    )


def _clock():  # type: ignore[no-untyped-def]
    return T0


def _setup(
    *,
    transport: FakeDemoTransport | None = None,
    limits: RiskLimits | None = None,
    gate: LiveTradingGate | None = None,
) -> tuple[DemoExecutionOrchestrator, FakeDemoTransport, RiskManager, Recorder]:
    tr = transport if transport is not None else FakeDemoTransport()
    broker = KalshiDemoLiveBroker(tr, gate=gate if gate is not None else _armed())
    risk = RiskManager(limits if limits is not None else RiskLimits())
    rec = Recorder.open(":memory:", session_id="demo", opened_at=T0)
    orch = DemoExecutionOrchestrator(broker=broker, risk=risk, recorder=rec, clock=_clock)
    return orch, tr, risk, rec


def _statuses(rec: Recorder) -> list[str]:
    rows = rec.connection.execute("SELECT status FROM order_events ORDER BY id").fetchall()
    return [r[0] for r in rows]


# ------------------------------------------------------------------ #
# host guard
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "url",
    [
        PROD_URL,
        "https://api.kalshi.com/trade-api/v2",
        "https://external-api.kalshi.com/trade-api/v2",
        "https://example.test/trade-api/v2",  # not a kalshi demo host
        "http://external-api.demo.kalshi.co/trade-api/v2",  # not https
        "",
    ],
)
def test_non_demo_host_is_rejected(url: str) -> None:
    with pytest.raises(DemoHostError):
        assert_demo_host(url)


def test_demo_host_is_accepted() -> None:
    assert assert_demo_host(DEMO_URL) == DEMO_URL


def test_broker_construction_rejects_a_production_transport() -> None:
    with pytest.raises(DemoHostError):
        KalshiDemoLiveBroker(FakeDemoTransport(base_url=PROD_URL), gate=_armed())


def test_orchestrator_rejects_a_non_demo_broker() -> None:
    prod = KalshiLiveBroker(KalshiTradingCredentials("k-id", "k-pem"), gate=_armed())
    rec = Recorder.open(":memory:", session_id="x", opened_at=T0)
    with pytest.raises(DemoExecutionError):
        DemoExecutionOrchestrator(
            broker=prod, risk=RiskManager(RiskLimits()), recorder=rec, clock=_clock
        )


# ------------------------------------------------------------------ #
# risk checks gate the broker call
# ------------------------------------------------------------------ #


def test_kill_switch_prevents_the_broker_call() -> None:
    orch, tr, risk, rec = _setup()
    risk.kill("manual halt")
    outcome = orch.execute(_intent())
    assert outcome.submitted is False
    assert outcome.blocked_reason == "risk_rejected"
    assert any("kill switch engaged: manual halt" in r for r in outcome.risk_decision.reasons)
    assert tr.calls == []  # the venue was never touched
    assert _statuses(rec) == ["new", "rejected"]


@pytest.mark.parametrize(
    ("limits", "intent_kwargs", "extra", "needle"),
    [
        (RiskLimits(max_order_size=D("1")), {"quantity": "2"}, {}, "exceeds max"),
        (
            RiskLimits(max_position=D("5")),
            {"quantity": "4"},
            {"positions": {_CID: "pos"}},
            "exceeds max",
        ),
        (RiskLimits(max_daily_loss=D("50")), {}, {"loss": D("-60")}, "daily realized loss"),
        (RiskLimits(max_data_age=timedelta(seconds=5)), {}, {}, "no market-data health provided"),
        (RiskLimits(min_net_edge_per_unit=D("0.02")), {}, {}, "no opportunity evaluation provided"),
    ],
)
def test_a_configured_risk_limit_blocks_before_the_broker(
    limits: RiskLimits, intent_kwargs: dict[str, str], extra: dict[str, object], needle: str
) -> None:
    from risk_support import position as _position

    orch, tr, risk, rec = _setup(limits=limits)
    if "loss" in extra:
        risk.record_realized_pnl(extra.pop("loss"), at=T0)  # type: ignore[arg-type]
    kwargs: dict[str, object] = {}
    if "positions" in extra:
        kwargs["positions"] = {_CID: _position(_CID, quantity="4")}
    outcome = orch.execute(_intent(**intent_kwargs), **kwargs)  # type: ignore[arg-type]
    assert outcome.submitted is False
    assert outcome.blocked_reason == "risk_rejected"
    assert any(needle in r for r in outcome.risk_decision.reasons)
    assert tr.calls == []
    assert _statuses(rec) == ["new", "rejected"]


def test_a_disabled_gate_fails_closed_without_touching_the_venue() -> None:
    orch, tr, _risk, rec = _setup(gate=LiveTradingGate.disabled())
    outcome = orch.execute(_intent())
    assert outcome.submitted is False
    assert outcome.blocked_reason == "gate_disabled"
    assert tr.calls == []
    assert _statuses(rec) == ["new", "rejected"]


# ------------------------------------------------------------------ #
# duplicate prevention
# ------------------------------------------------------------------ #


def test_local_idempotency_guard_blocks_a_second_submission() -> None:
    orch, tr, _risk, rec = _setup()
    first = orch.execute(_intent("dup-1"))
    assert first.submitted is True
    second = orch.execute(_intent("dup-1"))
    assert second.submitted is False
    assert second.duplicate is True
    assert second.blocked_reason == "duplicate_intent"
    assert tr.call_names() == ["create_order"]  # only the first reached the venue
    assert _statuses(rec) == ["new", "submitted", "new", "rejected"]


def test_a_venue_side_409_is_surfaced_as_a_duplicate() -> None:
    tr = FakeDemoTransport(create=DemoResponse(409, {"error": {"code": "x", "message": "y"}}))
    orch, tr, _risk, _rec = _setup(transport=tr)
    outcome = orch.execute(_intent("v-dup"))
    assert outcome.submitted is False
    assert outcome.duplicate is True


# ------------------------------------------------------------------ #
# happy path + lifecycle recording + reconcile
# ------------------------------------------------------------------ #


def test_execute_then_cancel_then_reconcile_records_the_full_lifecycle() -> None:
    orch, tr, _risk, rec = _setup()
    outcome = orch.execute(_intent("lc-1"))
    assert outcome.submitted is True
    assert outcome.ack is not None and outcome.ack.venue_order_id == "demo-ord-1"

    outcome = orch.cancel(outcome)
    assert outcome.cancelled is True

    outcome = orch.reconcile(outcome)
    assert outcome.reconciled is True
    assert outcome.order_status is not None
    assert outcome.local_position is not None and outcome.local_position.quantity == D("0")

    assert _statuses(rec) == ["new", "submitted", "canceled", "canceled"]
    pos_row = rec.connection.execute("SELECT count(*) FROM positions").fetchone()
    assert pos_row is not None and pos_row[0] == 1
    assert tr.call_names() == ["create_order", "cancel_order", "get_order", "get_positions"]


def test_reconcile_folds_a_venue_position_into_local_state() -> None:
    tr = FakeDemoTransport(
        get_order=DemoResponse(
            200, {"order": {"status": "executed", "fill_count_fp": "1", "remaining_count_fp": "0"}}
        ),
        positions=DemoResponse(
            200,
            {
                "market_positions": [{"ticker": "KXDEMO-T1", "position_fp": "1"}],
                "event_positions": [],
                "cursor": "",
            },
        ),
    )
    orch, _tr, _risk, rec = _setup(transport=tr)
    outcome = orch.reconcile(orch.execute(_intent("f-1")))
    assert outcome.order_status is not None and outcome.order_status.filled_quantity == D("1")
    assert outcome.local_position is not None and outcome.local_position.quantity == D("1")
    assert _statuses(rec)[-1] == "filled"


def test_reconciliation_is_deterministic_across_identical_runs() -> None:
    def run() -> tuple[object, ...]:
        tr = FakeDemoTransport(
            get_order=DemoResponse(
                200,
                {"order": {"status": "resting", "fill_count_fp": "0", "remaining_count_fp": "1"}},
            )
        )
        orch, _tr, _risk, rec = _setup(transport=tr)
        outcome = orch.reconcile(orch.execute(_intent("det-1")))
        rows = rec.connection.execute(
            "SELECT status, reason FROM order_events ORDER BY id"
        ).fetchall()
        return (outcome.to_evidence_dict(), rows)

    assert run() == run()


# ------------------------------------------------------------------ #
# fail-closed on missing / ambiguous venue state
# ------------------------------------------------------------------ #


def test_create_2xx_without_an_order_id_fails_closed() -> None:
    tr = FakeDemoTransport(create=DemoResponse(201, {"fill_count": "0", "remaining_count": "1"}))
    orch, _tr, _risk, _rec = _setup(transport=tr)
    with pytest.raises(DemoCapabilityError):
        orch.execute(_intent("no-id"))


def test_reconcile_fails_closed_on_ambiguous_order_status() -> None:
    tr = FakeDemoTransport(get_order=DemoResponse(200, {"order": {"fill_count_fp": "0"}}))
    orch, _tr, _risk, _rec = _setup(transport=tr)
    outcome = orch.execute(_intent("amb-1"))
    with pytest.raises(DemoCapabilityError):
        orch.reconcile(outcome)


def test_reconcile_fails_closed_when_positions_read_errors() -> None:
    tr = FakeDemoTransport(positions=DemoResponse(500, {"error": {"code": "x", "message": "y"}}))
    orch, _tr, _risk, _rec = _setup(transport=tr)
    outcome = orch.execute(_intent("perr-1"))
    with pytest.raises(DemoCapabilityError):
        orch.reconcile(outcome)


def test_non_2xx_create_is_recorded_rejected_not_assumed_placed() -> None:
    tr = FakeDemoTransport(create=DemoResponse(400, {"error": {"code": "x", "message": "y"}}))
    orch, _tr, _risk, rec = _setup(transport=tr)
    outcome = orch.execute(_intent("rej-1"))
    assert outcome.submitted is False
    assert outcome.ack is not None and outcome.ack.accepted is False
    assert _statuses(rec) == ["new", "rejected"]


def test_cancelling_something_that_never_reached_the_venue_is_an_error() -> None:
    orch, _tr, risk, _rec = _setup()
    risk.kill("halt")
    blocked = orch.execute(_intent("k-1"))
    with pytest.raises(DemoExecutionError):
        orch.cancel(blocked)
    with pytest.raises(DemoExecutionError):
        orch.reconcile(blocked)
