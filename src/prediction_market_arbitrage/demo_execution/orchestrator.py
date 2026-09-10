"""``DemoExecutionOrchestrator`` — composes the existing risk / live-broker /
recorder components into one **DEMO-only** execution path (M3.5).

Flow for :meth:`execute`:

1. record the approved **execution intent** (``OrderEventRow`` status ``new``);
2. run every configured **fail-closed risk check** (kill switch, position,
   order-size, exposure, daily-loss, data freshness / health, minimum edge) via
   the unchanged :class:`~..risk.RiskManager`;
3. on rejection: record ``rejected`` with the reasons and **return without
   calling the broker**;
4. on approval: submit through :class:`~..live_broker.LiveBroker`
   (``LiveTradingGate`` + ``IdempotencyGuard`` enforced there) — a duplicate
   ``client_order_id`` is recorded and **not** resubmitted;
5. record the **venue acknowledgement** as the next lifecycle row.

:meth:`cancel` and :meth:`reconcile` are separate explicit steps. Everything is
deterministic except the injected :class:`~.transport.DemoTransport` calls
(the venue I/O boundary) and the injected ``clock``.

Nothing here reads or sets ``LIVE_TRADING``; the broker it drives is
:class:`~.broker.KalshiDemoLiveBroker`, hard-pinned to the demo host.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from prediction_market_arbitrage.arbitrage import OpportunityEvaluation
from prediction_market_arbitrage.live_broker import (
    CancelRequest,
    DuplicateOrderError,
    LiveBroker,
    LiveOrderAck,
    LiveOrderState,
    LiveOrderStatus,
    LivePosition,
    LiveTradingDisabledError,
)
from prediction_market_arbitrage.live_broker.models import LiveOrderRequest
from prediction_market_arbitrage.livebook import FeedHealth
from prediction_market_arbitrage.paper_broker import LegRiskSnapshot, OrderRequest
from prediction_market_arbitrage.recorder import OrderEventRow, PositionRow, Recorder
from prediction_market_arbitrage.risk import RiskDecision, RiskManager

from .broker import KalshiDemoLiveBroker
from .errors import DemoExecutionError

_STATE_TO_RECORDER = {
    LiveOrderState.NEW: "new",
    LiveOrderState.SUBMITTED: "submitted",
    LiveOrderState.PARTIALLY_FILLED: "partially_filled",
    LiveOrderState.FILLED: "filled",
    LiveOrderState.CANCELED: "canceled",
    LiveOrderState.REJECTED: "rejected",
    LiveOrderState.EXPIRED: "expired",
}


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """The full result of one :meth:`DemoExecutionOrchestrator.execute` (plus any
    later cancel / reconcile applied to the same outcome)."""

    intent: LiveOrderRequest
    risk_decision: RiskDecision
    submitted: bool
    duplicate: bool
    ack: LiveOrderAck | None
    #: reason the broker was not called (risk reject / duplicate / gate closed).
    blocked_reason: str = ""
    order_status: LiveOrderStatus | None = None
    venue_positions: tuple[LivePosition, ...] = ()
    local_position: PositionRow | None = None
    cancelled: bool = False
    recorded_row_ids: tuple[int, ...] = ()
    #: True once a reconcile has resolved an otherwise-ambiguous venue state.
    reconciled: bool = False

    @property
    def reached_venue(self) -> bool:
        return self.ack is not None

    def to_evidence_dict(self) -> dict[str, object]:
        """A sanitised, value-free-ish summary for an evidence artifact — no raw
        prices/sizes/ids beyond the caller-chosen client_order_id and ticker."""
        return {
            "client_order_id": self.intent.client_order_id,
            "ticker": self.intent.contract_id.rsplit(":", 1)[0],
            "side": self.intent.side,
            "order_type": self.intent.order_type,
            "risk_allowed": self.risk_decision.allowed,
            "risk_checks_run": list(self.risk_decision.checks_run),
            "risk_reasons": list(self.risk_decision.reasons),
            "submitted": self.submitted,
            "duplicate": self.duplicate,
            "blocked_reason": self.blocked_reason,
            "venue_accepted": None if self.ack is None else self.ack.accepted,
            "venue_state": None if self.ack is None else self.ack.state.value,
            "order_status_state": (
                None if self.order_status is None else self.order_status.state.value
            ),
            "cancelled": self.cancelled,
            "reconciled": self.reconciled,
        }


class DemoExecutionOrchestrator:
    """One instance per demo execution session."""

    def __init__(
        self,
        *,
        broker: LiveBroker,
        risk: RiskManager,
        recorder: Recorder,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(broker, KalshiDemoLiveBroker):
            raise DemoExecutionError(
                "DemoExecutionOrchestrator only drives a KalshiDemoLiveBroker "
                "(host-pinned to Kalshi demo)"
            )
        if not isinstance(risk, RiskManager):
            raise DemoExecutionError("risk must be a RiskManager")
        if not isinstance(recorder, Recorder):
            raise DemoExecutionError("recorder must be a Recorder")
        self._broker = broker
        self._risk = risk
        self._rec = recorder
        self._clock = clock

    # -- main step ------------------------------------------------------ #

    def execute(
        self,
        intent: LiveOrderRequest,
        *,
        positions: Mapping[str, PositionRow] | None = None,
        marks: Mapping[str, Decimal] | None = None,
        opportunity: OpportunityEvaluation | None = None,
        health: FeedHealth | None = None,
        leg: LegRiskSnapshot | None = None,
        leg_pair_key: str | None = None,
    ) -> ExecutionOutcome:
        if not isinstance(intent, LiveOrderRequest):
            raise DemoExecutionError("execute() requires a LiveOrderRequest (the approved intent)")
        now = self._now()
        row_ids: list[int] = [self._record(intent, "new", now)]

        decision = self._risk.evaluate_order(
            _to_paper_request(intent),
            now=now,
            positions=positions,
            marks=marks,
            opportunity=opportunity,
            health=health,
            leg=leg,
            leg_pair_key=leg_pair_key,
        )
        if decision.rejected:
            row_ids.append(
                self._record(intent, "rejected", now, reason="risk: " + "; ".join(decision.reasons))
            )
            return ExecutionOutcome(
                intent=intent,
                risk_decision=decision,
                submitted=False,
                duplicate=False,
                ack=None,
                blocked_reason="risk_rejected",
                recorded_row_ids=tuple(row_ids),
            )

        try:
            ack = self._broker.submit_order(intent, now=now)
        except DuplicateOrderError as exc:
            row_ids.append(
                self._record(
                    intent, "rejected", now, reason=f"duplicate intent — not resubmitted: {exc}"
                )
            )
            return ExecutionOutcome(
                intent=intent,
                risk_decision=decision,
                submitted=False,
                duplicate=True,
                ack=None,
                blocked_reason="duplicate_intent",
                recorded_row_ids=tuple(row_ids),
            )
        except LiveTradingDisabledError as exc:
            row_ids.append(
                self._record(intent, "rejected", now, reason=f"live-trading gate not armed: {exc}")
            )
            return ExecutionOutcome(
                intent=intent,
                risk_decision=decision,
                submitted=False,
                duplicate=False,
                ack=None,
                blocked_reason="gate_disabled",
                recorded_row_ids=tuple(row_ids),
            )

        status_word = _STATE_TO_RECORDER.get(ack.state)
        if status_word is None:
            # accepted but no usable lifecycle state -> record as 'submitted' and
            # flag that a reconcile is required; never assume filled.
            status_word = "submitted"
            reason = "venue acknowledged; lifecycle state UNKNOWN — reconcile required"
        else:
            reason = "" if ack.accepted else "venue rejected the order"
        row_ids.append(self._record(intent, status_word, now, reason=reason))

        return ExecutionOutcome(
            intent=intent,
            risk_decision=decision,
            submitted=ack.accepted,
            duplicate=False,
            ack=ack,
            blocked_reason="" if ack.accepted else "venue_rejected",
            recorded_row_ids=tuple(row_ids),
        )

    # -- follow-up steps --------------------------------------------- #

    def cancel(self, outcome: ExecutionOutcome) -> ExecutionOutcome:
        """Cancel the order behind ``outcome`` through the demo broker and record
        the ``canceled`` lifecycle row."""
        if outcome.ack is None or not outcome.ack.accepted:
            raise DemoExecutionError("cannot cancel: the intent never reached the venue")
        now = self._now()
        ack = self._broker.cancel_order(
            CancelRequest(
                client_order_id=outcome.intent.client_order_id,
                venue_order_id=outcome.ack.venue_order_id,
            ),
            now=now,
        )
        row_ids = list(outcome.recorded_row_ids)
        row_ids.append(
            self._record(
                outcome.intent,
                "canceled" if ack.accepted else "submitted",
                now,
                reason="" if ack.accepted else f"cancel not confirmed (state {ack.state.value})",
            )
        )
        return replace(
            outcome,
            cancelled=ack.accepted,
            recorded_row_ids=tuple(row_ids),
        )

    def reconcile(self, outcome: ExecutionOutcome) -> ExecutionOutcome:
        """Read the venue order status + positions and record the resulting local
        order/position state. Fails closed on missing / ambiguous venue state
        (the demo broker raises :class:`DemoCapabilityError`)."""
        if outcome.ack is None or not outcome.ack.accepted:
            raise DemoExecutionError("cannot reconcile: the intent never reached the venue")
        now = self._now()
        status = self._broker.get_order(outcome.intent.client_order_id, now=now)
        venue_positions = self._broker.get_positions(now=now)

        ticker = outcome.intent.contract_id.rsplit(":", 1)[0]
        matched = next((p for p in venue_positions if p.contract_id == ticker), None)
        local_position = PositionRow(
            venue="kalshi",
            contract_id=outcome.intent.contract_id,
            quantity=matched.quantity if matched is not None else Decimal(0),
            avg_price=Decimal(0) if matched is None or matched.average_price is None
            else matched.average_price,
            as_of=now,
        )

        row_ids = list(outcome.recorded_row_ids)
        status_word = _STATE_TO_RECORDER.get(status.state, "submitted")
        row_ids.append(
            self._record(
                outcome.intent,
                status_word,
                now,
                reason=f"reconciled: venue state {status.state.value}, "
                f"filled {status.filled_quantity}, remaining {status.remaining_quantity}",
            )
        )
        pos_id = self._rec.record_position(local_position, recorded_at=now)
        row_ids.append(pos_id)

        return replace(
            outcome,
            order_status=status,
            venue_positions=tuple(venue_positions),
            local_position=local_position,
            reconciled=True,
            recorded_row_ids=tuple(row_ids),
        )

    # -- internals ------------------------------------------------- #

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise DemoExecutionError("injected clock() must return a timezone-aware datetime")
        return now

    def _record(
        self, intent: LiveOrderRequest, status: str, now: datetime, *, reason: str = ""
    ) -> int:
        return self._rec.record_order_event(
            OrderEventRow(
                order_id=intent.client_order_id,
                venue=intent.venue,
                contract_id=intent.contract_id,
                side=intent.side,
                order_type=intent.order_type,
                quantity=intent.quantity,
                status=status,
                event_time=now,
                limit_price=intent.limit_price,
                reason=reason,
            ),
            recorded_at=now,
        )


def _to_paper_request(intent: LiveOrderRequest) -> OrderRequest:
    """Adapt the approved live intent to the paper-broker request shape the
    :class:`RiskManager` checks (same fields, same (0,1) price rule)."""
    return OrderRequest(
        order_id=intent.client_order_id,
        venue=intent.venue,
        contract_id=intent.contract_id,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        immediate_or_cancel=intent.time_in_force == "ioc",
    )
