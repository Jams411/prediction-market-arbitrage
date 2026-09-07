"""DuckDB schema for the persistent recorder (Milestone M2.2).

One embedded, single-file (or in-memory) DuckDB database. Every table is
**append-only**: rows are inserted and never updated or deleted, so an
entity that changes over time (an order's status, a position, PnL, a feed's
health) is recorded as a sequence of rows ordered by a monotonic ``id`` from a
per-table sequence plus the injected event/record timestamps.

Monetary / price / quantity columns are ``VARCHAR`` holding exact
``str(Decimal)`` text (see ``_convert.dec_text``). Timestamp columns are
naive-UTC ``TIMESTAMP`` (``_convert.utc_naive``).

``initialize`` is idempotent (``CREATE ... IF NOT EXISTS``) and refuses to touch
a database written by a different ``SCHEMA_VERSION``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import RecorderError

if TYPE_CHECKING:
    import duckdb

SCHEMA_VERSION = 1

_SEQUENCES = (
    "seq_order_book_snapshots",
    "seq_opportunities",
    "seq_order_events",
    "seq_fills",
    "seq_positions",
    "seq_pnl",
    "seq_health_events",
)

_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recording_sessions (
        session_id VARCHAR PRIMARY KEY,
        opened_at  TIMESTAMP NOT NULL,
        label      VARCHAR NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_book_snapshots (
        id             BIGINT PRIMARY KEY DEFAULT nextval('seq_order_book_snapshots'),
        session_id     VARCHAR NOT NULL,
        venue          VARCHAR NOT NULL,
        market_id      VARCHAR NOT NULL,
        contract_id    VARCHAR NOT NULL,
        outcome        VARCHAR NOT NULL,
        book_timestamp TIMESTAMP NOT NULL,
        recorded_at    TIMESTAMP NOT NULL,
        source         VARCHAR NOT NULL,
        bid_count      INTEGER NOT NULL,
        ask_count      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_book_levels (
        snapshot_id BIGINT NOT NULL,
        side        VARCHAR NOT NULL,   -- 'bid' | 'ask'
        level_index INTEGER NOT NULL,   -- 0 == best
        price       VARCHAR NOT NULL,
        quantity    VARCHAR NOT NULL,
        PRIMARY KEY (snapshot_id, side, level_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opportunities (
        id                  BIGINT PRIMARY KEY DEFAULT nextval('seq_opportunities'),
        session_id          VARCHAR NOT NULL,
        pair_id             VARCHAR NOT NULL,
        relation            VARCHAR NOT NULL,
        evaluation_time     TIMESTAMP NOT NULL,
        recorded_at         TIMESTAMP NOT NULL,
        executable_quantity VARCHAR NOT NULL,
        depth_capped        BOOLEAN NOT NULL,
        gross_total_cost    VARCHAR NOT NULL,
        gross_edge          VARCHAR NOT NULL,
        fees                VARCHAR NOT NULL,
        execution_buffer    VARCHAR NOT NULL,
        net_total_cost      VARCHAR NOT NULL,
        net_edge            VARCHAR NOT NULL,
        has_opportunity     BOOLEAN NOT NULL,
        rejection_reason    VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_events (
        id          BIGINT PRIMARY KEY DEFAULT nextval('seq_order_events'),
        session_id  VARCHAR NOT NULL,
        order_id    VARCHAR NOT NULL,
        venue       VARCHAR NOT NULL,
        contract_id VARCHAR NOT NULL,
        side        VARCHAR NOT NULL,   -- 'buy' | 'sell'
        order_type  VARCHAR NOT NULL,   -- 'limit' | 'market'
        limit_price VARCHAR,            -- NULL for market orders
        quantity    VARCHAR NOT NULL,
        status      VARCHAR NOT NULL,
        event_time  TIMESTAMP NOT NULL,
        recorded_at TIMESTAMP NOT NULL,
        reason      VARCHAR NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        id          BIGINT PRIMARY KEY DEFAULT nextval('seq_fills'),
        session_id  VARCHAR NOT NULL,
        fill_id     VARCHAR NOT NULL,
        order_id    VARCHAR NOT NULL,
        venue       VARCHAR NOT NULL,
        contract_id VARCHAR NOT NULL,
        price       VARCHAR NOT NULL,
        quantity    VARCHAR NOT NULL,
        fee         VARCHAR NOT NULL,
        liquidity   VARCHAR NOT NULL,  -- 'maker' | 'taker' | 'unknown'
        filled_at   TIMESTAMP NOT NULL,
        recorded_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id          BIGINT PRIMARY KEY DEFAULT nextval('seq_positions'),
        session_id  VARCHAR NOT NULL,
        venue       VARCHAR NOT NULL,
        contract_id VARCHAR NOT NULL,
        quantity    VARCHAR NOT NULL,   -- signed
        avg_price   VARCHAR NOT NULL,
        as_of       TIMESTAMP NOT NULL,
        recorded_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pnl (
        id          BIGINT PRIMARY KEY DEFAULT nextval('seq_pnl'),
        session_id  VARCHAR NOT NULL,
        scope       VARCHAR NOT NULL,  -- 'contract' | 'pair' | 'portfolio'
        scope_id    VARCHAR NOT NULL,
        realized    VARCHAR NOT NULL,
        unrealized  VARCHAR NOT NULL,
        fees        VARCHAR NOT NULL,
        as_of       TIMESTAMP NOT NULL,
        recorded_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS health_events (
        id               BIGINT PRIMARY KEY DEFAULT nextval('seq_health_events'),
        session_id       VARCHAR NOT NULL,
        venue            VARCHAR NOT NULL,
        contract_id      VARCHAR NOT NULL,
        status           VARCHAR NOT NULL,
        reason           VARCHAR NOT NULL,
        trading_enabled  BOOLEAN NOT NULL,
        as_of            TIMESTAMP NOT NULL,
        last_update      TIMESTAMP,
        last_sequence    BIGINT,
        recorded_at      TIMESTAMP NOT NULL
    )
    """,
)


def initialize(connection: duckdb.DuckDBPyConnection) -> None:
    """Create the schema if absent; validate the version if present. Idempotent."""
    for sequence in _SEQUENCES:
        connection.execute(f"CREATE SEQUENCE IF NOT EXISTS {sequence} START 1")
    for ddl in _TABLES:
        connection.execute(ddl)

    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO schema_meta VALUES ('schema_version', ?)", [str(SCHEMA_VERSION)]
        )
        return
    found = int(row[0])
    if found != SCHEMA_VERSION:
        raise RecorderError(
            f"database schema_version {found} != this build's {SCHEMA_VERSION}; "
            "recorder does not migrate"
        )
