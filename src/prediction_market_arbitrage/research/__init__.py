"""Offline advisory research. No broker, transport or registry integration."""

from .metadata import CpiContractMetadata, derive_cpi_threshold_relationship
from .models import (
    Diagnostic,
    EvidenceStatus,
    ResearchEvaluation,
    ResearchSignal,
    SignalType,
    ThresholdRelationship,
)
from .persistence import (
    PersistenceClass,
    PersistenceRecord,
    classify_persistence,
    collect_snapshots,
)
from .replay import (
    SCHEMA_VERSION,
    deserialize_snapshot,
    normalize_observation,
    replay_snapshot,
    serialize_snapshot,
)
from .scoring import (
    RejectionReason,
    ResearchScore,
    ResearchScoringConfig,
    rank_research_scores,
    score_research_evaluation,
)
from .thresholds import evaluate_threshold_ordering, rank_threshold_signals

__all__ = [
    "Diagnostic",
    "EvidenceStatus",
    "ResearchEvaluation",
    "ResearchSignal",
    "SignalType",
    "ThresholdRelationship",
    "CpiContractMetadata",
    "derive_cpi_threshold_relationship",
    "evaluate_threshold_ordering",
    "rank_threshold_signals",
    "SCHEMA_VERSION",
    "normalize_observation",
    "serialize_snapshot",
    "deserialize_snapshot",
    "replay_snapshot",
    "RejectionReason",
    "ResearchScore",
    "ResearchScoringConfig",
    "score_research_evaluation",
    "rank_research_scores",
    "PersistenceClass",
    "PersistenceRecord",
    "collect_snapshots",
    "classify_persistence",
]
