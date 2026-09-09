"""Deterministic replay of an M2.2 recording (Milestone M2.3).

``ReplaySession`` is a **read-only** consumer of a recorder DuckDB database. It
reconstructs each recorded stream — order books, opportunities, order events,
fills, positions, PnL, health events — for one ``session_id``, in the
deterministic order the recorder appended them (its monotonic per-table ``id``),
and exposes:

- per-stream iterators (``order_books()``, ``opportunities()``, ...),
- ``timeline()`` — the streams merged and ordered by
  ``(recorded_at, kind, row_id)``,
- ``play(sleep=..., speed=...)`` — ``timeline()`` with the recorded inter-event
  wall-gap applied through an **injected** ``sleep``; the default
  :func:`no_sleep` makes replay fully deterministic for tests, and
  :func:`realtime` reproduces the original timing,
- ``as_book_snapshots()`` / ``feed_book_snapshots()`` — the live-book
  consumption path: a replayed order book handed to
  ``livebook.LiveBookFeed.apply_snapshot`` unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

import duckdb

from prediction_market_arbitrage.domain import DomainValidationError, OrderBook, PriceLevel
from prediction_market_arbitrage.livebook import (
    BookSnapshot,
    FeedHealth,
    HealthStatus,
    LiveBookFeed,
)
from prediction_market_arbitrage.recorder.schema import SCHEMA_VERSION
from prediction_market_arbitrage.registry import OutcomeRelation

from ._read import (
    opt_to_decimal,
    opt_to_utc,
    rebuild_contract,
    to_decimal,
    to_utc,
)
from .errors import ReplayError
from .models import (
    RecordedFill,
    RecordedHealthEvent,
    RecordedLegRiskEvent,
    RecordedOpportunity,
    RecordedOrderBook,
    RecordedOrderEvent,
    RecordedPnl,
    RecordedPosition,
    ReplayEvent,
)

if TYPE_CHECKING:
    from types import TracebackType

Sleep = Callable[[float], None]

#: Tie-break order when two events share a ``recorded_at`` — fixed and total.
_KIND_RANK: dict[str, int] = {
    "order_book": 0,
    "opportunity": 1,
    "order_event": 2,
    "fill": 3,
    "position": 4,
    "pnl": 5,
    "health": 6,
    "leg_risk": 7,
}


def no_sleep(_seconds: float) -> None:
    """Injectable ``sleep`` that returns immediately — deterministic replay."""


def realtime(speed: float = 1.0) -> Sleep:
    """A ``sleep`` that reproduces recorded timing (``speed`` > 1 fast-forwards)."""
    if speed <= 0:
        raise ReplayError("realtime speed must be > 0")
    return lambda seconds: time.sleep(max(0.0, seconds) / speed)


class ReplaySession:
    """Read-only reconstruction of one recorded session."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, *, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ReplayError("session_id must be a non-empty string")
        self._conn = connection
        self._session_id = session_id
        self._check_schema()
        if not self._session_exists():
            raise ReplayError(
                f"session {session_id!r} is not in recording_sessions "
                f"(present: {self.available_sessions(connection)})"
            )

    @classmethod
    def open(
        cls,
        database: str,
        *,
        session_id: str,
        read_only: bool = True,
    ) -> ReplaySession:
        """Open ``database`` (a file path) read-only and bind to ``session_id``."""
        return cls(duckdb.connect(database, read_only=read_only), session_id=session_id)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ReplaySession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def session_id(self) -> str:
        return self._session_id

    @staticmethod
    def available_sessions(connection: duckdb.DuckDBPyConnection) -> list[str]:
        return [
            row[0]
            for row in connection.execute(
                "SELECT session_id FROM recording_sessions ORDER BY session_id"
            ).fetchall()
        ]

    def counts(self) -> dict[str, int]:
        """Row count per stream for this session (order of ``_KIND_RANK``).

        ``leg_risk`` is ``0`` for a recording written before that table existed
        (see :meth:`has_leg_risk_stream`)."""
        tables = {
            "order_book": "order_book_snapshots",
            "opportunity": "opportunities",
            "order_event": "order_events",
            "fill": "fills",
            "position": "positions",
            "pnl": "pnl",
            "health": "health_events",
            "leg_risk": "leg_risk_events",
        }
        out: dict[str, int] = {}
        for kind, table in tables.items():
            if kind == "leg_risk" and not self.has_leg_risk_stream():
                out[kind] = 0
                continue
            row = self._conn.execute(
                f"SELECT count(*) FROM {table} WHERE session_id = ?", [self._session_id]
            ).fetchone()
            out[kind] = int(row[0]) if row is not None else 0
        return out

    def has_leg_risk_stream(self) -> bool:
        """``True`` when this recording's database has the ``leg_risk_events``
        table. A recording written before the table existed returns ``False`` —
        its leg-risk data is genuinely absent, not "zero events"."""
        row = self._conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'leg_risk_events'"
        ).fetchone()
        return row is not None

    # -- streams (each ordered by the recorder's monotonic id) --------- #

    def order_books(self) -> Iterator[RecordedOrderBook]:
        rows = self._conn.execute(
            """
            SELECT id, venue, market_id, contract_id, outcome,
                   book_timestamp, recorded_at, source
            FROM order_book_snapshots
            WHERE session_id = ?
            ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for snapshot_id, venue, market_id, contract_id, outcome, book_ts, rec_at, source in rows:
            yield self._build_order_book(
                snapshot_id, venue, market_id, contract_id, outcome, book_ts, rec_at, source
            )

    def as_book_snapshots(self) -> Iterator[tuple[BookSnapshot, datetime]]:
        """``(BookSnapshot, recorded_at)`` per recorded book — the livebook path."""
        for recorded in self.order_books():
            yield recorded.as_book_snapshot(), recorded.recorded_at

    def opportunities(self) -> Iterator[RecordedOpportunity]:
        rows = self._conn.execute(
            """
            SELECT id, pair_id, relation, evaluation_time, recorded_at,
                   executable_quantity, depth_capped, gross_total_cost, gross_edge,
                   fees, execution_buffer, net_total_cost, net_edge,
                   has_opportunity, rejection_reason
            FROM opportunities WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedOpportunity(
                row_id=int(r[0]),
                pair_id=r[1],
                relation=self._relation(r[2]),
                evaluation_time=to_utc(r[3]),
                recorded_at=to_utc(r[4]),
                executable_quantity=to_decimal(r[5], field="executable_quantity"),
                depth_capped=bool(r[6]),
                gross_total_cost=to_decimal(r[7], field="gross_total_cost"),
                gross_edge=to_decimal(r[8], field="gross_edge"),
                fees=to_decimal(r[9], field="fees"),
                execution_buffer=to_decimal(r[10], field="execution_buffer"),
                net_total_cost=to_decimal(r[11], field="net_total_cost"),
                net_edge=to_decimal(r[12], field="net_edge"),
                has_opportunity=bool(r[13]),
                rejection_reason=r[14],
            )

    def order_events(self) -> Iterator[RecordedOrderEvent]:
        rows = self._conn.execute(
            """
            SELECT id, order_id, venue, contract_id, side, order_type, limit_price,
                   quantity, status, event_time, recorded_at, reason
            FROM order_events WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedOrderEvent(
                row_id=int(r[0]),
                order_id=r[1],
                venue=r[2],
                contract_id=r[3],
                side=r[4],
                order_type=r[5],
                limit_price=opt_to_decimal(r[6], field="limit_price"),
                quantity=to_decimal(r[7], field="quantity"),
                status=r[8],
                event_time=to_utc(r[9]),
                recorded_at=to_utc(r[10]),
                reason=r[11],
            )

    def fills(self) -> Iterator[RecordedFill]:
        rows = self._conn.execute(
            """
            SELECT id, fill_id, order_id, venue, contract_id, price, quantity,
                   fee, liquidity, filled_at, recorded_at
            FROM fills WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedFill(
                row_id=int(r[0]),
                fill_id=r[1],
                order_id=r[2],
                venue=r[3],
                contract_id=r[4],
                price=to_decimal(r[5], field="price"),
                quantity=to_decimal(r[6], field="quantity"),
                fee=to_decimal(r[7], field="fee"),
                liquidity=r[8],
                filled_at=to_utc(r[9]),
                recorded_at=to_utc(r[10]),
            )

    def positions(self) -> Iterator[RecordedPosition]:
        rows = self._conn.execute(
            """
            SELECT id, venue, contract_id, quantity, avg_price, as_of, recorded_at
            FROM positions WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedPosition(
                row_id=int(r[0]),
                venue=r[1],
                contract_id=r[2],
                quantity=to_decimal(r[3], field="quantity"),
                avg_price=to_decimal(r[4], field="avg_price"),
                as_of=to_utc(r[5]),
                recorded_at=to_utc(r[6]),
            )

    def pnl(self) -> Iterator[RecordedPnl]:
        rows = self._conn.execute(
            """
            SELECT id, scope, scope_id, realized, unrealized, fees, as_of, recorded_at
            FROM pnl WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedPnl(
                row_id=int(r[0]),
                scope=r[1],
                scope_id=r[2],
                realized=to_decimal(r[3], field="realized"),
                unrealized=to_decimal(r[4], field="unrealized"),
                fees=to_decimal(r[5], field="fees"),
                as_of=to_utc(r[6]),
                recorded_at=to_utc(r[7]),
            )

    def health_events(self) -> Iterator[RecordedHealthEvent]:
        rows = self._conn.execute(
            """
            SELECT id, venue, contract_id, status, reason, trading_enabled,
                   as_of, last_update, last_sequence, recorded_at
            FROM health_events WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            status = self._health_status(r[3])
            health = FeedHealth(
                status=status,
                reason=r[4],
                as_of=to_utc(r[6]),
                last_update=opt_to_utc(r[7]),
                last_sequence=None if r[8] is None else int(r[8]),
            )
            if bool(r[5]) != health.trading_enabled:
                raise ReplayError(
                    f"health row {int(r[0])}: stored trading_enabled={bool(r[5])} "
                    f"disagrees with reconstructed status {status}"
                )
            yield RecordedHealthEvent(
                row_id=int(r[0]),
                venue=r[1],
                contract_id=r[2],
                health=health,
                recorded_at=to_utc(r[9]),
            )

    def leg_risk_events(self) -> Iterator[RecordedLegRiskEvent]:
        """One-legged-exposure events (recorder ``leg_risk_events``), append order.

        Yields nothing for a recording whose database predates the table
        (``has_leg_risk_stream()`` is ``False``)."""
        if not self.has_leg_risk_stream():
            return
        rows = self._conn.execute(
            """
            SELECT id, order_a_id, order_b_id, a_filled_quantity, b_filled_quantity,
                   unhedged_quantity, a_average_price, b_average_price,
                   hedge_completion_price, unhedged_notional, both_terminal,
                   as_of, recorded_at
            FROM leg_risk_events WHERE session_id = ? ORDER BY id
            """,
            [self._session_id],
        ).fetchall()
        for r in rows:
            yield RecordedLegRiskEvent(
                row_id=int(r[0]),
                order_a_id=r[1],
                order_b_id=r[2],
                a_filled_quantity=to_decimal(r[3], field="a_filled_quantity"),
                b_filled_quantity=to_decimal(r[4], field="b_filled_quantity"),
                unhedged_quantity=to_decimal(r[5], field="unhedged_quantity"),
                a_average_price=to_decimal(r[6], field="a_average_price"),
                b_average_price=to_decimal(r[7], field="b_average_price"),
                hedge_completion_price=opt_to_decimal(
                    r[8], field="hedge_completion_price"
                ),
                unhedged_notional=opt_to_decimal(r[9], field="unhedged_notional"),
                both_terminal=bool(r[10]),
                as_of=to_utc(r[11]),
                recorded_at=to_utc(r[12]),
            )

    # -- merged timeline + pacing ------------------------------------ #

    def timeline(self) -> list[ReplayEvent]:
        """All streams merged, ordered by ``(recorded_at, kind, row_id)``."""
        events: list[ReplayEvent] = []
        streams: Sequence[tuple[str, Iterator[object]]] = (
            ("order_book", self.order_books()),
            ("opportunity", self.opportunities()),
            ("order_event", self.order_events()),
            ("fill", self.fills()),
            ("position", self.positions()),
            ("pnl", self.pnl()),
            ("health", self.health_events()),
            ("leg_risk", self.leg_risk_events()),
        )
        for kind, stream in streams:
            for payload in stream:
                events.append(
                    ReplayEvent(
                        kind=kind,
                        recorded_at=payload.recorded_at,  # type: ignore[attr-defined]
                        row_id=payload.row_id,  # type: ignore[attr-defined]
                        payload=payload,  # type: ignore[arg-type]
                    )
                )
        events.sort(key=lambda e: (e.recorded_at, _KIND_RANK[e.kind], e.row_id))
        return events

    def play(self, *, sleep: Sleep = no_sleep, speed: float = 1.0) -> Iterator[ReplayEvent]:
        """Yield ``timeline()`` events, calling ``sleep`` for the recorded wall-gap
        before each event after the first. ``speed`` divides every gap
        (``speed=2`` -> twice as fast). With the default :func:`no_sleep` this is
        a plain deterministic iterator."""
        if speed <= 0:
            raise ReplayError("play speed must be > 0")
        previous: datetime | None = None
        for event in self.timeline():
            if previous is not None:
                gap = (event.recorded_at - previous).total_seconds()
                sleep(max(0.0, gap) / speed)
            previous = event.recorded_at
            yield event

    def feed_book_snapshots(
        self,
        feeds: Mapping[str, LiveBookFeed],
        *,
        sleep: Sleep = no_sleep,
        speed: float = 1.0,
    ) -> int:
        """Apply every recorded book to the matching ``LiveBookFeed`` (keyed by
        ``contract_id``), paced by the recorded gaps. Books for a contract not in
        ``feeds`` are skipped. Returns the number applied."""
        if speed <= 0:
            raise ReplayError("feed_book_snapshots speed must be > 0")
        applied = 0
        previous: datetime | None = None
        for snapshot, recorded_at in self.as_book_snapshots():
            if previous is not None:
                gap = (recorded_at - previous).total_seconds()
                sleep(max(0.0, gap) / speed)
            previous = recorded_at
            feed = feeds.get(snapshot.contract_id)
            if feed is None:
                continue
            feed.apply_snapshot(snapshot, received_at=recorded_at)
            applied += 1
        return applied

    # -- internals ------------------------------------------------- #

    def _build_order_book(
        self,
        snapshot_id: int,
        venue: str,
        market_id: str,
        contract_id: str,
        outcome: str,
        book_ts: datetime,
        recorded_at: datetime,
        source: str,
    ) -> RecordedOrderBook:
        levels = self._conn.execute(
            """
            SELECT side, level_index, price, quantity
            FROM order_book_levels WHERE snapshot_id = ? ORDER BY side, level_index
            """,
            [snapshot_id],
        ).fetchall()
        bids: list[PriceLevel] = []
        asks: list[PriceLevel] = []
        for side, index, price, quantity in levels:
            level = PriceLevel(
                price=to_decimal(price, field=f"level {snapshot_id}/{side}/{index}.price"),
                quantity=to_decimal(quantity, field=f"level {snapshot_id}/{side}/{index}.qty"),
            )
            (bids if side == "bid" else asks).append(level)
        contract = rebuild_contract(venue, market_id, contract_id, outcome)
        try:
            book = OrderBook(
                contract=contract,
                bids=tuple(sorted(bids, key=lambda level: level.price, reverse=True)),
                asks=tuple(sorted(asks, key=lambda level: level.price)),
                timestamp=to_utc(book_ts),
            )
        except DomainValidationError as exc:
            raise ReplayError(
                f"order-book snapshot {snapshot_id} does not reconstruct: {exc}"
            ) from exc
        return RecordedOrderBook(
            row_id=int(snapshot_id),
            book=book,
            recorded_at=to_utc(recorded_at),
            source=source,
        )

    def _relation(self, value: str) -> OutcomeRelation:
        try:
            return OutcomeRelation(value)
        except ValueError as exc:
            raise ReplayError(f"unknown OutcomeRelation {value!r}") from exc

    def _health_status(self, value: str) -> HealthStatus:
        try:
            return HealthStatus(value)
        except ValueError as exc:
            raise ReplayError(f"unknown HealthStatus {value!r}") from exc

    def _check_schema(self) -> None:
        try:
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        except duckdb.Error as exc:
            raise ReplayError(f"not a recorder database: {exc}") from exc
        if row is None:
            raise ReplayError("recorder database has no schema_version")
        if int(row[0]) != SCHEMA_VERSION:
            raise ReplayError(
                f"database schema_version {row[0]} != replay's expected {SCHEMA_VERSION}"
            )

    def _session_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM recording_sessions WHERE session_id = ?", [self._session_id]
        ).fetchone()
        return row is not None
