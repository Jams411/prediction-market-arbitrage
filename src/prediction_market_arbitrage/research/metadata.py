"""Pure adapter from explicit Kalshi contract metadata to research relations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from prediction_market_arbitrage.domain import Contract, Market, Venue
from prediction_market_arbitrage.domain.validation import (
    DomainValidationError,
    require_non_empty,
    to_decimal,
)

from .models import EvidenceStatus, ThresholdRelationship

_ABOVE = re.compile(r"^above\s+(-?(?:\d+(?:\.\d+)?|\.\d+))%?$", re.IGNORECASE)
_GREATER = re.compile(
    r"(?:strictly\s+greater\s+than|more\s+than)\s+(?:<percent>|-?(?:\d+(?:\.\d+)?|\.\d+)%?)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CpiContractMetadata:
    """The authoritative, already extracted fields required for one CPI child.

    The adapter intentionally requires explicit normalized fields. It does not
    infer a parent, threshold, source, or semantic orientation from a ticker.
    """

    contract: Contract
    event_id: str
    underlying: str
    observation_window: str
    unit: str
    source: str
    threshold: Decimal
    yes_semantics: str
    evidence_refs: tuple[str, ...]
    evidence_status: EvidenceStatus

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> CpiContractMetadata:
        """Parse a fixture/API-shaped mapping without making defaults."""
        if not isinstance(raw, Mapping):
            raise DomainValidationError("CPI metadata must be a mapping")

        def text(key: str) -> str:
            return _text(raw, key)

        venue_id = text("venue_id")
        venue_name = text("venue_name")
        market_id = text("market_id")
        ticker = text("ticker")
        title = text("title")
        yes_subtitle = _alias(raw, "yes_subtitle", "yes_sub_title")
        event_id = _alias(raw, "event_id", "event_ticker")
        threshold = _decimal(raw, "threshold")
        semantics = text("yes_semantics")
        if semantics != "X > threshold":
            raise DomainValidationError("yes_semantics must be exactly 'X > threshold'")
        refs = raw.get("evidence_refs")
        if (
            not isinstance(refs, (tuple, list))
            or not refs
            or any(not isinstance(x, str) for x in refs)
        ):
            raise DomainValidationError("evidence_refs must be a nonempty sequence of strings")
        refs = tuple(refs)
        status_raw = raw.get("evidence_status")
        try:
            status = (
                status_raw
                if isinstance(status_raw, EvidenceStatus)
                else EvidenceStatus(status_raw)
                if isinstance(status_raw, str)
                else None
            )
        except ValueError as exc:
            raise DomainValidationError("evidence_status must be a known EvidenceStatus") from exc
        if status not in (
            EvidenceStatus.OBSERVED,
            EvidenceStatus.TESTED,
            EvidenceStatus.VERIFIED,
        ):
            raise DomainValidationError("CPI relationship requires observed or tested metadata")
        primary_rules = text("rules_primary")
        if not _GREATER.search(primary_rules):
            raise DomainValidationError(
                "rules_primary does not prove strict greater-than YES semantics"
            )
        displayed = _ABOVE.fullmatch(yes_subtitle.strip())
        if displayed is None or Decimal(displayed.group(1)) != threshold:
            raise DomainValidationError("yes_subtitle and threshold disagree or are ambiguous")
        underlying = text("underlying")
        unit = text("unit")
        source = text("source")
        if "cpi" not in underlying.casefold():
            raise DomainValidationError("underlying is not an explicit CPI measurement")
        if unit.casefold() not in {"percent", "percentage", "%"}:
            raise DomainValidationError("unit is not an explicit CPI percent unit")
        if source.casefold() not in {"bls", "bureau of labor statistics"}:
            raise DomainValidationError("source is not the Bureau of Labor Statistics")
        contract = Contract(Market(Venue(venue_id, venue_name), market_id, title), ticker, "YES")
        return cls(
            contract=contract,
            event_id=event_id,
            underlying=underlying,
            observation_window=text("observation_window"),
            unit=unit,
            source=source,
            threshold=threshold,
            yes_semantics=semantics,
            evidence_refs=refs,
            evidence_status=status,
        )


def derive_cpi_threshold_relationship(
    lower: Mapping[str, object] | CpiContractMetadata,
    higher: Mapping[str, object] | CpiContractMetadata,
    *,
    relationship_id: str,
    version: str,
    settlement_limitations: tuple[str, ...],
) -> ThresholdRelationship:
    """Derive a detector-safe relationship from two explicit metadata records."""
    low = (
        lower if isinstance(lower, CpiContractMetadata) else CpiContractMetadata.from_mapping(lower)
    )
    high = (
        higher
        if isinstance(higher, CpiContractMetadata)
        else CpiContractMetadata.from_mapping(higher)
    )
    for field in ("event_id", "underlying", "observation_window", "unit", "source"):
        if getattr(low, field) != getattr(high, field):
            raise DomainValidationError(f"CPI metadata mismatch: {field}")
    if low.contract.venue != high.contract.venue:
        raise DomainValidationError("CPI metadata mismatch: venue")
    if low.contract.market.id == high.contract.market.id:
        raise DomainValidationError("CPI metadata ambiguous: same market id")
    refs = tuple(dict.fromkeys(low.evidence_refs + high.evidence_refs))
    return ThresholdRelationship(
        id=relationship_id,
        version=version,
        event_id=low.event_id,
        lower_yes=low.contract,
        higher_yes=high.contract,
        lower_threshold=low.threshold,
        higher_threshold=high.threshold,
        underlying=low.underlying,
        observation_window=low.observation_window,
        source=low.source,
        evidence_refs=refs,
        ordinary_proof_status=(EvidenceStatus.TESTED),
        settlement_limitations=settlement_limitations,
        metadata_status=(
            EvidenceStatus.VERIFIED
            if low.evidence_status is EvidenceStatus.VERIFIED
            and high.evidence_status is EvidenceStatus.VERIFIED
            else EvidenceStatus.OBSERVED
        ),
        unit=low.unit,
    )


def _text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise DomainValidationError(f"CPI metadata field {key!r} must be text")
    return require_non_empty(value, field=key)


def _alias(raw: Mapping[str, object], *keys: str) -> str:
    values = [(key, raw[key]) for key in keys if key in raw]
    if not values:
        raise DomainValidationError(f"CPI metadata requires one of {keys!r}")
    if any(not isinstance(value, str) for _, value in values):
        raise DomainValidationError(f"CPI metadata aliases {keys!r} must be text")
    texts_list: list[str] = []
    for key, value in values:
        if not isinstance(value, str):
            raise DomainValidationError(f"CPI metadata aliases {keys!r} must be text")
        texts_list.append(require_non_empty(value, field=key))
    texts = tuple(texts_list)
    if len(set(texts)) != 1:
        raise DomainValidationError(f"CPI metadata aliases {keys!r} disagree")
    return texts[0]


def _decimal(raw: Mapping[str, object], key: str) -> Decimal:
    value = raw.get(key)
    try:
        return to_decimal(value, field=key)  # type: ignore[arg-type]
    except DomainValidationError:
        raise
