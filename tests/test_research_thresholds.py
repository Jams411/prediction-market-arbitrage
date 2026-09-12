"""Synthetic-only offline research tests; no venue fixtures or calls."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from prediction_market_arbitrage.arbitrage import OpportunityEvaluation
from prediction_market_arbitrage.domain import (
    Contract,
    DomainValidationError,
    Market,
    Opportunity,
    OrderBook,
    PriceLevel,
    Venue,
)
from prediction_market_arbitrage.research import (
    CpiContractMetadata,
    Diagnostic,
    EvidenceStatus,
    ResearchEvaluation,
    ResearchSignal,
    SignalType,
    ThresholdRelationship,
    derive_cpi_threshold_relationship,
    evaluate_threshold_ordering,
    rank_threshold_signals,
)

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def metadata(
    ticker: str, market: str, threshold_value: str, **overrides: object
) -> dict[str, object]:
    result: dict[str, object] = {
        "venue_id": "synthetic",
        "venue_name": "Synthetic venue",
        "market_id": market,
        "ticker": ticker,
        "title": f"Synthetic CPI above {threshold_value}%",
        "yes_subtitle": f"Above {threshold_value}%",
        "event_id": "synthetic-event",
        "underlying": "CPI-U one-month change",
        "observation_window": "September 2026",
        "unit": "percent",
        "source": "BLS",
        "threshold": D(threshold_value),
        "yes_semantics": "X > threshold",
        "rules_primary": "Payout Criterion is strictly greater than <percent>.",
        "evidence_refs": ("synthetic://cpi-terms",),
        "evidence_status": EvidenceStatus.TESTED,
    }
    result.update(overrides)
    return result


@pytest.fixture
def relationship() -> ThresholdRelationship:
    venue = Venue("synthetic", "Synthetic venue")
    lower = Contract(Market(venue, "synthetic-low", "Synthetic lower"), "low-yes", "YES")
    higher = Contract(Market(venue, "synthetic-high", "Synthetic higher"), "high-yes", "YES")
    return ThresholdRelationship(
        "synthetic-cpi",
        "1",
        "synthetic-event",
        lower,
        higher,
        D(".2"),
        D(".3"),
        "synthetic CPI scalar",
        "synthetic month",
        "synthetic source",
        ("synthetic://ordinary-proof",),
        EvidenceStatus.TESTED,
        ("Exceptional settlement ordering is unproved.",),
    )


def books(r: ThresholdRelationship, high_bid: str = ".60") -> tuple[OrderBook, OrderBook]:
    return (
        OrderBook(r.lower_yes, (PriceLevel(D(".40"), D(20)),), (PriceLevel(D(".50"), D(10)),), NOW),
        OrderBook(
            r.higher_yes, (PriceLevel(D(high_bid), D(7)),), (PriceLevel(D(".80"), D(20)),), NOW
        ),
    )


def evaluate(r: ThresholdRelationship, low: OrderBook, high: OrderBook) -> ResearchEvaluation:
    return evaluate_threshold_ordering(
        r,
        low,
        high,
        evaluation_time=NOW,
        max_age=timedelta(seconds=10),
        max_skew=timedelta(seconds=2),
        input_status=EvidenceStatus.TESTED,
    )


def signal(r: ThresholdRelationship) -> ResearchSignal:
    result = evaluate(r, *books(r))
    assert result.signal is not None
    return result.signal


@pytest.mark.parametrize(("bid", "gap"), [(".60", ".10"), (".50", None), (".49", None)])
def test_gap(relationship: ThresholdRelationship, bid: str, gap: str | None) -> None:
    result = evaluate(relationship, *books(relationship, bid))
    if gap is None:
        assert result.signal is None
        assert result.diagnostics == (Diagnostic.NO_DISCREPANCY,)
    else:
        assert result.signal is not None
        assert result.signal.metric_value == D(gap)
        assert result.signal.top_level_quantity == D(7)
        assert result.diagnostics == ()


def test_provenance_and_safety(relationship: ThresholdRelationship) -> None:
    finding = signal(relationship)
    assert finding.kind is SignalType.LOGICAL_INCONSISTENCY
    assert finding.relationship == relationship
    assert finding.input_status is EvidenceStatus.TESTED
    assert finding.settlement_confidence == "UNKNOWN"
    assert finding.value_confidence == "NOT_ASSESSED"
    assert finding.fees == "NOT_EVALUATED"
    assert set(relationship.settlement_limitations).issubset(finding.limitations)
    assert not isinstance(finding, Opportunity | OpportunityEvaluation)
    assert not hasattr(finding, "to_opportunity")
    assert not hasattr(finding, "execution_eligible")
    with pytest.raises(FrozenInstanceError):
        finding.metric_value = D(1)  # type: ignore[misc]  # frozen mutation test
    with pytest.raises(DomainValidationError, match="strict arbitrage"):
        replace(finding, kind=SignalType.STRICT_ARBITRAGE)
    with pytest.raises(DomainValidationError, match="preserved"):
        replace(finding, limitations=("Other limitation",))
    assert {kind.value for kind in SignalType} == {
        "STRICT_ARBITRAGE",
        "RELATIVE_VALUE",
        "LOGICAL_INCONSISTENCY",
        "FAIR_VALUE_DEVIATION",
    }


@pytest.mark.parametrize("which", ["low", "high"])
def test_identity_and_side(relationship: ThresholdRelationship, which: str) -> None:
    low, high = books(relationship)
    target = low if which == "low" else high
    for wrong in (replace(target.contract, outcome="NO"), replace(target.contract, id="other")):
        modified = replace(target, contract=wrong)
        result = evaluate(
            relationship, modified if which == "low" else low, modified if which == "high" else high
        )
        assert result.diagnostics == (Diagnostic.IDENTITY_MISMATCH,)


@pytest.mark.parametrize("which", ["low", "high"])
def test_missing_levels(relationship: ThresholdRelationship, which: str) -> None:
    low, high = books(relationship)
    result = evaluate(
        relationship,
        replace(low, asks=()) if which == "low" else low,
        replace(high, bids=()) if which == "high" else high,
    )
    assert result.diagnostics == (Diagnostic.MISSING_LEVEL,)


@pytest.mark.parametrize(
    ("offset", "reason"),
    [
        (1, Diagnostic.FUTURE_BOOK),
        (-11, Diagnostic.STALE_BOOK),
        (-3, Diagnostic.EXCESSIVE_SKEW),
    ],
)
def test_time_rejections(
    relationship: ThresholdRelationship, offset: int, reason: Diagnostic
) -> None:
    low, high = books(relationship)
    low = replace(low, timestamp=NOW + timedelta(seconds=offset))
    assert evaluate(relationship, low, high).diagnostics == (reason,)


def test_time_boundaries_and_unknown_provenance(relationship: ThresholdRelationship) -> None:
    low, high = books(relationship)
    result = evaluate_threshold_ordering(
        relationship,
        replace(low, timestamp=NOW - timedelta(seconds=10)),
        replace(high, timestamp=NOW - timedelta(seconds=8)),
        evaluation_time=NOW,
        max_age=timedelta(seconds=10),
        max_skew=timedelta(seconds=2),
    )
    assert result.signal is not None
    assert result.signal.input_status is EvidenceStatus.UNKNOWN
    with pytest.raises(DomainValidationError):
        evaluate_threshold_ordering(
            relationship,
            low,
            high,
            evaluation_time=NOW,
            max_age=timedelta(seconds=-1),
            max_skew=timedelta(0),
        )
    with pytest.raises(DomainValidationError):
        evaluate_threshold_ordering(
            relationship,
            low,
            high,
            evaluation_time=NOW.replace(tzinfo=None),
            max_age=timedelta(0),
            max_skew=timedelta(0),
        )


@pytest.mark.parametrize(
    "status", [EvidenceStatus.UNKNOWN, EvidenceStatus.UNVERIFIED, EvidenceStatus.OBSERVED]
)
def test_unproven_relationship(relationship: ThresholdRelationship, status: EvidenceStatus) -> None:
    r = replace(relationship, ordinary_proof_status=status)
    assert evaluate(r, *books(r)).diagnostics == (Diagnostic.ORDINARY_PROOF_UNAVAILABLE,)


@pytest.mark.parametrize("threshold", [D(".2"), D(".1"), D("NaN"), D("Infinity")])
def test_bad_thresholds(relationship: ThresholdRelationship, threshold: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        replace(relationship, higher_threshold=threshold)


def test_relationship_validation(relationship: ThresholdRelationship) -> None:
    with pytest.raises(DomainValidationError):
        replace(relationship, lower_yes=replace(relationship.lower_yes, outcome="NO"))
    with pytest.raises(DomainValidationError):
        replace(relationship, higher_yes=relationship.lower_yes)
    with pytest.raises(DomainValidationError):
        replace(relationship, evidence_refs=())
    with pytest.raises(DomainValidationError):
        replace(relationship, settlement_limitations=())
    other = replace(relationship.higher_yes.market, venue=Venue("other", "Other"))
    with pytest.raises(DomainValidationError):
        replace(relationship, higher_yes=replace(relationship.higher_yes, market=other))


def test_invalid_book_values_are_rejected(relationship: ThresholdRelationship) -> None:
    low, _ = books(relationship)
    with pytest.raises(DomainValidationError):
        replace(low, bids=(PriceLevel(D(".51"), D(1)),))
    with pytest.raises(DomainValidationError):
        PriceLevel(D("NaN"), D(1))
    with pytest.raises(DomainValidationError):
        PriceLevel(D(".4"), D(0))


def test_ranking(relationship: ThresholdRelationship) -> None:
    base = signal(relationship)
    wide = replace(base, metric_value=D(".11"))
    deep = replace(base, top_level_quantity=D(8))
    old = replace(base, lower_book=replace(base.lower_book, timestamp=NOW - timedelta(seconds=1)))
    later_id = replace(base, relationship=replace(relationship, id="z-synthetic"))
    findings = (old, later_id, base, deep, wide)
    expected = (wide, deep, base, later_id, old)
    assert rank_threshold_signals(findings) == expected
    assert rank_threshold_signals(reversed(findings)) == expected
    with pytest.raises(DomainValidationError):
        rank_threshold_signals((replace(base, kind=SignalType.RELATIVE_VALUE),))


def test_ordinary_predicate_boundaries(relationship: ThresholdRelationship) -> None:
    # Algebra only, not a claim about exceptional settlement.
    for x in (D(".1"), D(".2"), D(".25"), D(".3"), D(".4")):
        lower, higher = x > relationship.lower_threshold, x > relationship.higher_threshold
        assert not higher or lower
    assert not (D(".2") > relationship.lower_threshold)
    assert not (D(".3") > relationship.higher_threshold)


def test_evaluation_invariant(relationship: ThresholdRelationship) -> None:
    with pytest.raises(DomainValidationError):
        ResearchEvaluation(None)
    with pytest.raises(DomainValidationError):
        ResearchEvaluation(signal(relationship), (Diagnostic.NO_DISCREPANCY,))


def test_metadata_adapter_derives_detector_relationship() -> None:
    low = metadata("low", "market-low", ".2")
    high = metadata(
        "high", "market-high", ".3", evidence_refs=("synthetic://cpi-terms", "synthetic://event")
    )
    relation = derive_cpi_threshold_relationship(
        low,
        high,
        relationship_id="derived-cpi",
        version="1",
        settlement_limitations=("fallback unresolved",),
    )
    assert isinstance(CpiContractMetadata.from_mapping(low), CpiContractMetadata)
    assert relation.event_id == "synthetic-event"
    assert relation.lower_threshold == D(".2")
    assert relation.higher_threshold == D(".3")
    assert relation.lower_yes.outcome == relation.higher_yes.outcome == "YES"
    assert relation.evidence_refs == ("synthetic://cpi-terms", "synthetic://event")
    assert relation.ordinary_proof_status is EvidenceStatus.TESTED


def test_metadata_adapter_accepts_kalshi_numeric_more_than_rule() -> None:
    raw = metadata(
        "kalshi-shaped",
        "market-kalshi",
        "0.6",
        rules_primary="If CPI increases by more than 0.6% in September 2026, resolves Yes.",
    )
    parsed = CpiContractMetadata.from_mapping(raw)
    assert parsed.threshold == D("0.6")


@pytest.mark.parametrize(
    "field", ["event_id", "underlying", "observation_window", "unit", "source"]
)
def test_metadata_adapter_rejects_mismatch(field: str) -> None:
    low = metadata("low", "market-low", ".2")
    high = metadata("high", "market-high", ".3", **{field: "different"})
    with pytest.raises(DomainValidationError):
        derive_cpi_threshold_relationship(
            low, high, relationship_id="x", version="1", settlement_limitations=("x",)
        )


@pytest.mark.parametrize(
    "change",
    [
        {"yes_semantics": "X >= threshold"},
        {"yes_subtitle": "Between 0.2 and 0.3"},
        {"rules_primary": "Payout Criterion is at least <percent>."},
        {"evidence_status": EvidenceStatus.UNKNOWN},
        {"threshold": D("NaN")},
    ],
)
def test_metadata_adapter_rejects_ambiguous_semantics(change: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        CpiContractMetadata.from_mapping(metadata("low", "market-low", ".2", **change))


def test_metadata_adapter_rejects_order_and_duplicate_market() -> None:
    low = metadata("low", "market-low", ".3")
    high = metadata("high", "market-high", ".2")
    with pytest.raises(DomainValidationError, match="thresholds"):
        derive_cpi_threshold_relationship(
            low, high, relationship_id="x", version="1", settlement_limitations=("x",)
        )
    with pytest.raises(DomainValidationError, match="same market"):
        derive_cpi_threshold_relationship(
            metadata("low", "same", ".2"),
            metadata("high", "same", ".3"),
            relationship_id="x",
            version="1",
            settlement_limitations=("x",),
        )


@pytest.mark.parametrize("field_value", ["GDP", "weather temperature"])
def test_metadata_adapter_rejects_non_cpi_underlying(field_value: str) -> None:
    with pytest.raises(DomainValidationError, match="CPI"):
        CpiContractMetadata.from_mapping(
            metadata("low", "market-low", ".2", underlying=field_value)
        )


@pytest.mark.parametrize("key", ["unit", "source"])
def test_metadata_adapter_rejects_non_cpi_dimensions(key: str) -> None:
    with pytest.raises(DomainValidationError):
        CpiContractMetadata.from_mapping(metadata("low", "market-low", ".2", **{key: "invalid"}))


def test_recorded_kalshi_cpi_metadata_derives_relationship() -> None:
    path = Path(__file__).parent / "fixtures" / "kalshi" / "cpi_metadata_recorded.json"
    recorded = json.loads(path.read_text())
    lower, higher = recorded["contracts"]
    relation = derive_cpi_threshold_relationship(
        lower,
        higher,
        relationship_id="KXCPI-26SEP-ordering-0.2-0.3",
        version="recorded-2026-09-12",
        settlement_limitations=("fair settlement unresolved",),
    )
    assert relation.event_id == "KXCPI-26SEP"
    assert (
        relation.underlying
        == "signed one-month, one-decimal percent change in seasonally adjusted CPI-U"
    )
    assert relation.observation_window == "September 2026"
    assert relation.unit == "percent"
    assert relation.source == "Bureau of Labor Statistics"
    assert relation.lower_threshold == D("0.2")
    assert relation.higher_threshold == D("0.3")
    assert relation.lower_yes.id == "KXCPI-26SEP-T0.2"
    assert relation.higher_yes.id == "KXCPI-26SEP-T0.3"
    assert relation.metadata_status is EvidenceStatus.OBSERVED
    assert relation.ordinary_proof_status is EvidenceStatus.TESTED


def test_recorded_kalshi_cpi_metadata_mismatch_fails_closed() -> None:
    path = Path(__file__).parent / "fixtures" / "kalshi" / "cpi_metadata_recorded.json"
    recorded = json.loads(path.read_text())
    lower, higher = recorded["contracts"]
    higher["event_ticker"] = "KXCPI-26OCT"
    with pytest.raises(DomainValidationError, match="mismatch: event_id"):
        derive_cpi_threshold_relationship(
            lower,
            higher,
            relationship_id="bad",
            version="1",
            settlement_limitations=("fair settlement unresolved",),
        )
