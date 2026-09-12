"""Synthetic repeat-observation persistence tests."""

import copy
from decimal import Decimal
from pathlib import Path

import pytest

from prediction_market_arbitrage.domain import DomainValidationError
from prediction_market_arbitrage.research import (
    PersistenceClass,
    ResearchScoringConfig,
    classify_persistence,
    collect_snapshots,
    deserialize_snapshot,
    serialize_snapshot,
)

ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / (
    "docs/evidence/contract-discovery/"
    "kalshi-cpi-relative-value-snapshot-local-2026-09-12.json"
)


def snapshot() -> dict[str, object]:
    return deserialize_snapshot(SNAPSHOT.read_text())


def with_first_signal(value: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(value)
    contracts = result["contracts"]
    assert isinstance(contracts, tuple)
    lower = contracts[0]["market_id"]
    higher = contracts[1]["market_id"]
    quotes = {item["market_id"]: item["quote"] for item in contracts}
    quotes[lower]["yes_ask"] = "0.50"
    quotes[lower]["yes_bid"] = "0.40"
    quotes[higher]["yes_bid"] = "0.70"
    return result


def test_persistence_classifies_no_signal_transient_and_persistent() -> None:
    base = snapshot()
    signal = with_first_signal(base)
    records = classify_persistence(
        (base, signal, signal),
        scoring_config=ResearchScoringConfig(),
    )
    assert records[0].classification is PersistenceClass.PERSISTENT
    assert records[0].persistence_count == 2
    assert records[0].persistence_rate == Decimal(2) / Decimal(3)
    assert all(record.classification is PersistenceClass.NO_SIGNAL for record in records[1:])

    transient = classify_persistence((base, signal), scoring_config=ResearchScoringConfig())
    assert transient[0].classification is PersistenceClass.TRANSIENT


def test_collect_snapshots_is_bounded_and_canonical() -> None:
    values = iter((snapshot(), snapshot()))
    sleeps: list[float] = []
    captured = collect_snapshots(
        lambda: next(values),
        count=2,
        interval_seconds=0.25,
        sleep=sleeps.append,
    )
    assert len(captured) == 2
    assert captured[0] == serialize_snapshot(snapshot())
    assert sleeps == [0.25]


def test_invalid_count_and_malformed_snapshot_fail_closed() -> None:
    with pytest.raises(DomainValidationError):
        collect_snapshots(snapshot, count=0)
    broken = snapshot()
    broken["pair_count"] = 1
    with pytest.raises(DomainValidationError):
        classify_persistence((broken,))
