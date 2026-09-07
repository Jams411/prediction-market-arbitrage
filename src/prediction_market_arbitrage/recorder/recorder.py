"""Append-only DuckDB recorder for market data, opportunities, orders/fills,
positions/PnL, and feed health (Milestone M2.2).

The recorder **only writes**. It has no strategy, execution, or accounting
logic: it takes already-built domain / engine / livebook objects (or the
recorder row value-objects in :mod:`.models`) plus an injected ``recorded_at``
and appends one row (or, for an order book, one parent row + its levels).

Determinism: every write is a single ordered ``INSERT``; row ids come from
per-table DuckDB sequences; there is no wall-clock read and no random id. Given
the same sequence of calls with the same inputs against a fresh database, the
resulting rows are identical.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING

import duckdb

from prediction_market_arbitrage.arbitrage import OpportunityEvaluation
from prediction_market_arbitrage.domain import OrderBook
from prediction_market_arbitrage.livebook import FeedHealth

from . import schema
from ._convert import dec_text, opt_utc_naive, require_text, utc_naive
from .errors import RecorderError
from .models import FillRow, OrderEventRow, PnlRow, PositionRow

if TYPE_CHECKING:
    from collections.abc import Sequence


class Recorder:
    """Owns one DuckDB connection and appends rows to the M2.2 schema."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        session_id: str,
        opened_at: datetime,
        label: str = "",
    ) -> None:
        require_text(session_id, field="session_id")
        self._conn = connection
        self._session_id = session_id
        schema.initialize(connection)
        connection.execute(
            "INSERT OR IGNORE INTO recording_sessions VALUES (?, ?, ?)",
            [session_id, utc_naive(opened_at, field="opened_at"), label],
        )

    # -- construction / lifecycle ------------------------------------- #

    @classmethod
    def open(
        cls,
        database: str = ":memory:",
        *,
        session_id: str,
        opened_at: datetime,
        label: str = "",
    ) -> Recorder:
        """Connect to ``database`` (a file path or ``":memory:"``), init the
        schema, and register the session."""
        return cls(
            duckdb.connect(database),
            session_id=session_id,
            opened_at=opened_at,
            label=label,
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Recorder:
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

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """The underlying connection — for **reads** (analysis, replay in M2.3)."""
        return self._conn

    # -- writes (each appends and returns the new row id) ------------- #

    def record_order_book(
        self, book: OrderBook, *, recorded_at: datetime, source: str
    ) -> int:
        """Append an order-book snapshot (one parent row + one row per level)."""
        if not isinstance(book, OrderBook):
            raise RecorderError("record_order_book: expected a domain OrderBook")
        require_text(source, field="source")
        contract = book.contract
        snapshot_id = self._insert_returning(
            """
            INSERT INTO order_book_snapshots
                (session_id, venue, market_id, contract_id, outcome,
                 book_timestamp, recorded_at, source, bid_count, ask_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                contract.market.venue.id,
                contract.market.id,
                contract.id,
                contract.outcome,
                utc_naive(book.timestamp, field="book.timestamp"),
                utc_naive(recorded_at, field="recorded_at"),
                source,
                len(book.bids),
                len(book.asks),
            ],
        )
        for side, levels in (("bid", book.bids), ("ask", book.asks)):
            for index, level in enumerate(levels):
                self._conn.execute(
                    "INSERT INTO order_book_levels VALUES (?, ?, ?, ?, ?)",
                    [
                        snapshot_id,
                        side,
                        index,
                        dec_text(level.price, field="level.price"),
                        dec_text(level.quantity, field="level.quantity"),
                    ],
                )
        return snapshot_id

    def record_opportunity(
        self, evaluation: OpportunityEvaluation, *, recorded_at: datetime
    ) -> int:
        """Append one arbitrage-engine :class:`OpportunityEvaluation` result."""
        if not isinstance(evaluation, OpportunityEvaluation):
            raise RecorderError("record_opportunity: expected an OpportunityEvaluation")
        e = evaluation
        return self._insert_returning(
            """
            INSERT INTO opportunities
                (session_id, pair_id, relation, evaluation_time, recorded_at,
                 executable_quantity, depth_capped, gross_total_cost, gross_edge,
                 fees, execution_buffer, net_total_cost, net_edge,
                 has_opportunity, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                e.pair_id,
                str(e.relation),
                utc_naive(e.evaluation_time, field="evaluation.evaluation_time"),
                utc_naive(recorded_at, field="recorded_at"),
                dec_text(e.executable_quantity, field="executable_quantity"),
                bool(e.depth_capped),
                dec_text(e.gross_total_cost, field="gross_total_cost"),
                dec_text(e.gross_edge, field="gross_edge"),
                dec_text(e.fees, field="fees"),
                dec_text(e.execution_buffer, field="execution_buffer"),
                dec_text(e.net_total_cost, field="net_total_cost"),
                dec_text(e.net_edge, field="net_edge"),
                bool(e.has_opportunity),
                e.rejection_reason,
            ],
        )

    def record_order_event(self, row: OrderEventRow, *, recorded_at: datetime) -> int:
        """Append one point in an order's lifecycle."""
        if not isinstance(row, OrderEventRow):
            raise RecorderError("record_order_event: expected an OrderEventRow")
        return self._insert_returning(
            """
            INSERT INTO order_events
                (session_id, order_id, venue, contract_id, side, order_type,
                 limit_price, quantity, status, event_time, recorded_at, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                row.order_id,
                row.venue,
                row.contract_id,
                row.side,
                row.order_type,
                None if row.limit_price is None else str(row.limit_price),
                str(row.quantity),
                row.status,
                utc_naive(row.event_time, field="row.event_time"),
                utc_naive(recorded_at, field="recorded_at"),
                row.reason,
            ],
        )

    def record_fill(self, row: FillRow, *, recorded_at: datetime) -> int:
        """Append one fill."""
        if not isinstance(row, FillRow):
            raise RecorderError("record_fill: expected a FillRow")
        return self._insert_returning(
            """
            INSERT INTO fills
                (session_id, fill_id, order_id, venue, contract_id, price,
                 quantity, fee, liquidity, filled_at, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                row.fill_id,
                row.order_id,
                row.venue,
                row.contract_id,
                str(row.price),
                str(row.quantity),
                str(row.fee),
                row.liquidity,
                utc_naive(row.filled_at, field="row.filled_at"),
                utc_naive(recorded_at, field="recorded_at"),
            ],
        )

    def record_position(self, row: PositionRow, *, recorded_at: datetime) -> int:
        """Append one position snapshot."""
        if not isinstance(row, PositionRow):
            raise RecorderError("record_position: expected a PositionRow")
        return self._insert_returning(
            """
            INSERT INTO positions
                (session_id, venue, contract_id, quantity, avg_price, as_of, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                row.venue,
                row.contract_id,
                str(row.quantity),
                str(row.avg_price),
                utc_naive(row.as_of, field="row.as_of"),
                utc_naive(recorded_at, field="recorded_at"),
            ],
        )

    def record_pnl(self, row: PnlRow, *, recorded_at: datetime) -> int:
        """Append one PnL snapshot for a scope."""
        if not isinstance(row, PnlRow):
            raise RecorderError("record_pnl: expected a PnlRow")
        return self._insert_returning(
            """
            INSERT INTO pnl
                (session_id, scope, scope_id, realized, unrealized, fees, as_of, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                row.scope,
                row.scope_id,
                str(row.realized),
                str(row.unrealized),
                str(row.fees),
                utc_naive(row.as_of, field="row.as_of"),
                utc_naive(recorded_at, field="recorded_at"),
            ],
        )

    def record_health_event(
        self,
        health: FeedHealth,
        *,
        venue: str,
        contract_id: str,
        recorded_at: datetime,
    ) -> int:
        """Append one feed-health verdict (from ``livebook.LiveBookFeed.health``)."""
        if not isinstance(health, FeedHealth):
            raise RecorderError("record_health_event: expected a FeedHealth")
        require_text(venue, field="venue")
        require_text(contract_id, field="contract_id")
        return self._insert_returning(
            """
            INSERT INTO health_events
                (session_id, venue, contract_id, status, reason, trading_enabled,
                 as_of, last_update, last_sequence, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                self._session_id,
                venue,
                contract_id,
                health.status.value,
                health.reason,
                bool(health.trading_enabled),
                utc_naive(health.as_of, field="health.as_of"),
                opt_utc_naive(health.last_update, field="health.last_update"),
                health.last_sequence,
                utc_naive(recorded_at, field="recorded_at"),
            ],
        )

    # -- internals -------------------------------------------------- #

    def _insert_returning(self, sql: str, params: Sequence[object]) -> int:
        row = self._conn.execute(sql + " RETURNING id", list(params)).fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
            raise RecorderError("insert did not return a row id")
        return int(row[0])
