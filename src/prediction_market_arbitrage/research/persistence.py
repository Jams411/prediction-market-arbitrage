"""Synchronous repeat-observation persistence analysis."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

from prediction_market_arbitrage.domain.validation import DomainValidationError

from .models import ResearchEvaluation
from .replay import deserialize_snapshot, replay_snapshot, serialize_snapshot
from .scoring import ResearchScoringConfig, score_research_evaluation


class PersistenceClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    PERSISTENT = "PERSISTENT"
    NO_SIGNAL = "NO_SIGNAL"


@dataclass(frozen=True, slots=True)
class PersistenceRecord:
    relationship_key: str
    observation_count: int
    persistence_count: int
    persistence_rate: Decimal
    classification: PersistenceClass


def collect_snapshots(
    capture: Callable[[], Mapping[str, object] | str],
    *,
    count: int,
    interval_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, ...]:
    """Capture a bounded sequence of canonical snapshots synchronously."""
    if count <= 0:
        raise DomainValidationError("observation count must be positive")
    if interval_seconds < 0:
        raise DomainValidationError("observation interval must be nonnegative")
    snapshots: list[str] = []
    for index in range(count):
        raw = capture()
        canonical = (
            serialize_snapshot(deserialize_snapshot(raw))
            if isinstance(raw, str)
            else serialize_snapshot(raw)
        )
        snapshots.append(canonical)
        if index + 1 < count and interval_seconds:
            sleep(interval_seconds)
    return tuple(snapshots)


def classify_persistence(
    snapshots: Sequence[Mapping[str, object] | str],
    *,
    scoring_config: ResearchScoringConfig | None = None,
) -> tuple[PersistenceRecord, ...]:
    """Compare identical adjacent relationships across validated snapshots."""
    if not snapshots:
        raise DomainValidationError("at least one snapshot is required")
    evaluations = [replay_snapshot(snapshot) for snapshot in snapshots]
    first = (
        deserialize_snapshot(snapshots[0])
        if isinstance(snapshots[0], str)
        else dict(snapshots[0])
    )
    contracts = first["contracts"]
    if not isinstance(contracts, tuple):
        raise DomainValidationError("snapshot contracts are malformed")
    keys = [
        f"{_threshold(contracts[index])}>{_threshold(contracts[index + 1])}"
        for index in range(len(contracts) - 1)
        if isinstance(contracts[index], Mapping) and isinstance(contracts[index + 1], Mapping)
    ]
    records: list[PersistenceRecord] = []
    for index, key in enumerate(keys):
        count = sum(
            1
            for result in evaluations
            if _is_signal(result[index], scoring_config)
        )
        total = len(evaluations)
        classification = (
            PersistenceClass.NO_SIGNAL
            if count == 0
            else PersistenceClass.TRANSIENT
            if count == 1
            else PersistenceClass.PERSISTENT
        )
        records.append(
            PersistenceRecord(
                relationship_key=key,
                observation_count=total,
                persistence_count=count,
                persistence_rate=Decimal(count) / Decimal(total),
                classification=classification,
            )
        )
    return tuple(records)


def _is_signal(
    result: ResearchEvaluation,
    scoring_config: ResearchScoringConfig | None,
) -> bool:
    if result.signal is None:
        return False
    return (
        score_research_evaluation(result, scoring_config).accepted
        if scoring_config is not None
        else True
    )


def _threshold(contract: object) -> str:
    if not isinstance(contract, Mapping) or not isinstance(contract.get("threshold"), str):
        raise DomainValidationError("snapshot contract threshold is malformed")
    return cast(str, contract["threshold"])
