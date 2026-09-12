"""Offline tests for the compact CPI record/replay path."""

import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from prediction_market_arbitrage.domain import DomainValidationError
from prediction_market_arbitrage.research import (
    Diagnostic,
    deserialize_snapshot,
    replay_snapshot,
    serialize_snapshot,
)

ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / (
    "docs/evidence/contract-discovery/"
    "kalshi-cpi-relative-value-snapshot-local-2026-09-12.json"
)


def observation() -> dict[str, object]:
    return cast("dict[str, object]", json.loads(SNAPSHOT.read_text()))


def test_snapshot_round_trip_and_replay_fixture() -> None:
    snapshot = deserialize_snapshot(SNAPSHOT.read_text())
    assert deserialize_snapshot(serialize_snapshot(snapshot)) == snapshot
    results = replay_snapshot(snapshot)
    assert len(results) == 10
    assert all(result.signal is None for result in results)
    assert all(result.diagnostics == (Diagnostic.NO_DISCREPANCY,) for result in results)


def test_replay_is_deterministic_and_matches_recorded_inputs() -> None:
    snapshot = observation()
    first = replay_snapshot(snapshot)
    second = replay_snapshot(serialize_snapshot(snapshot))
    assert [(r.signal, r.diagnostics) for r in first] == [
        (r.signal, r.diagnostics) for r in second
    ]


def test_malformed_snapshot_fails_closed() -> None:
    snapshot = observation()
    broken = dict(snapshot)
    broken["contracts"] = tuple(snapshot["contracts"][:-1])  # type: ignore[index]
    with pytest.raises(DomainValidationError):
        serialize_snapshot(broken)


def test_stale_snapshot_is_reported_by_existing_detector() -> None:
    snapshot = observation()
    results = replay_snapshot(
        snapshot,
        evaluation_time=__import__("datetime").datetime.fromisoformat(snapshot["observed_at"])
        + timedelta(hours=1),
    )
    assert all(result.signal is None for result in results)
    assert all(result.diagnostics == (Diagnostic.STALE_BOOK,) for result in results)
