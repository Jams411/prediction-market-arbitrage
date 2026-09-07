"""Deterministic tests for the M2.2 recorder schema / init."""

from __future__ import annotations

import duckdb
import pytest

from prediction_market_arbitrage.recorder import SCHEMA_VERSION, RecorderError, initialize

_EXPECTED_TABLES = {
    "schema_meta",
    "recording_sessions",
    "order_book_snapshots",
    "order_book_levels",
    "opportunities",
    "order_events",
    "fills",
    "positions",
    "pnl",
    "health_events",
}


def test_initialize_creates_every_table_and_stamps_the_version() -> None:
    conn = duckdb.connect(":memory:")
    initialize(conn)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert _EXPECTED_TABLES <= tables
    version = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version == (str(SCHEMA_VERSION),)


def test_initialize_is_idempotent() -> None:
    conn = duckdb.connect(":memory:")
    initialize(conn)
    initialize(conn)
    initialize(conn)
    assert conn.execute("SELECT count(*) FROM schema_meta").fetchone() == (1,)


def test_initialize_rejects_a_foreign_schema_version() -> None:
    conn = duckdb.connect(":memory:")
    initialize(conn)
    conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    with pytest.raises(RecorderError, match="does not migrate"):
        initialize(conn)
