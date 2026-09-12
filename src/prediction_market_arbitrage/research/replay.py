"""Compact, validated record/replay for CPI threshold observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from prediction_market_arbitrage.domain import OrderBook, PriceLevel
from prediction_market_arbitrage.domain.validation import (
    DomainValidationError,
    require_aware,
    to_decimal,
)

from .metadata import CpiContractMetadata, derive_cpi_threshold_relationship
from .models import EvidenceStatus, ResearchEvaluation
from .thresholds import evaluate_threshold_ordering

SCHEMA_VERSION = "cpi-relative-value-snapshot.v1"
_REQUIRED_SHARED = ("event_id", "underlying", "observation_window", "unit", "source")


def normalize_observation(raw: Mapping[str, object]) -> dict[str, object]:
    """Reduce an observation artifact to the replay schema and validate it."""
    if not isinstance(raw, Mapping):
        raise DomainValidationError("observation must be a mapping")
    contracts = raw.get("contracts")
    snapshots = raw.get("market_quote_snapshots")
    if not isinstance(contracts, list) or not contracts:
        raise DomainValidationError("observation contracts must be a nonempty list")
    if not isinstance(snapshots, Mapping):
        raise DomainValidationError("observation quote snapshots are required")
    pairs = raw.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != len(contracts) - 1:
        raise DomainValidationError("observation must contain adjacent pair evidence")
    shared = {
        "event_id": "KXCPI-26SEP",
        "underlying": "CPI",
        "observation_window": "September 2026 month-over-month",
        "unit": "percent",
        "source": "BLS",
    }
    observed_at = _timestamp(raw.get("observed_at"), "observed_at")
    normalized: list[dict[str, object]] = []
    for ticker in contracts:
        if not isinstance(ticker, str) or not ticker:
            raise DomainValidationError("contract ticker must be text")
        quote = snapshots.get(ticker)
        if not isinstance(quote, Mapping):
            raise DomainValidationError(f"missing quote snapshot for {ticker}")
        threshold = _threshold_from_ticker(ticker)
        subtitle = f"Above {threshold}%"
        normalized.append(
            {
                "market_id": ticker,
                "contract_id": f"{ticker}:YES",
                "title": f"CPI above {threshold}%",
                "yes_subtitle": subtitle,
                "event_id": shared["event_id"],
                "threshold": threshold,
                "yes_semantics": "X > threshold",
                "rules_primary": f"CPI increases by more than {threshold}% in September 2026.",
                **shared,
                "evidence_refs": (
                    "https://external-api.kalshi.com/trade-api/v2/markets?event_ticker=KXCPI-26SEP",
                ),
                "evidence_status": raw.get("metadata_status", EvidenceStatus.OBSERVED.value),
                "quote": {
                    "observed_at": _timestamp(
                        quote.get("request_finished_at"), "quote time"
                    ).isoformat(),
                    "metadata_updated_time": quote.get("metadata_updated_time"),
                    "yes_bid": _decimal_text(quote.get("yes_bid"), "yes_bid"),
                    "yes_bid_size": _decimal_text(quote.get("yes_bid_size"), "yes_bid_size"),
                    "yes_ask": _decimal_text(quote.get("yes_ask"), "yes_ask"),
                    "yes_ask_size": _decimal_text(quote.get("yes_ask_size"), "yes_ask_size"),
                },
            }
        )
    limitations = raw.get("limitations", ())
    if not isinstance(limitations, (list, tuple)):
        raise DomainValidationError("observation limitations must be a sequence")
    result = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed_at.isoformat(),
        "contract_count": len(normalized),
        "pair_count": len(pairs),
        **shared,
        "metadata_status": raw.get("metadata_status", EvidenceStatus.OBSERVED.value),
        "ordinary_proof_status": raw.get("ordinary_proof_status", EvidenceStatus.TESTED.value),
        "settlement_limitations": tuple(str(x) for x in limitations),
        "contracts": tuple(normalized),
    }
    _validate_snapshot(result)
    return result


def serialize_snapshot(snapshot: Mapping[str, object]) -> str:
    """Validate and encode a canonical compact snapshot."""
    _validate_snapshot(dict(snapshot))
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def deserialize_snapshot(data: str) -> dict[str, object]:
    """Decode and validate one snapshot, rejecting malformed input."""
    try:
        value: object = json.loads(data)
    except json.JSONDecodeError as exc:
        raise DomainValidationError("snapshot is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DomainValidationError("snapshot must be a JSON object")
    _validate_snapshot(value)
    return value


def replay_snapshot(
    snapshot: Mapping[str, object] | str,
    *,
    evaluation_time: datetime | None = None,
    max_age: timedelta = timedelta(minutes=5),
    max_skew: timedelta = timedelta(minutes=2),
) -> tuple[ResearchEvaluation, ...]:
    """Derive adjacent relationships and run the existing pure detector."""
    value = deserialize_snapshot(snapshot) if isinstance(snapshot, str) else dict(snapshot)
    _validate_snapshot(value)
    contracts = value["contracts"]
    assert isinstance(contracts, tuple)
    parsed = [_metadata(value, item) for item in contracts if isinstance(item, Mapping)]
    if len(parsed) != len(contracts):
        raise DomainValidationError("snapshot contracts are malformed")
    parsed.sort(key=lambda item: item[0].threshold)
    when = evaluation_time or _timestamp(value["observed_at"], "observed_at")
    results: list[ResearchEvaluation] = []
    for (lower, lower_book), (higher, higher_book) in zip(
        parsed, parsed[1:], strict=False
    ):
        relation = derive_cpi_threshold_relationship(
            lower,
            higher,
            relationship_id=f"{lower.event_id}:{lower.threshold}>{higher.threshold}",
            version="1",
            settlement_limitations=tuple(cast("tuple[str, ...]", value["settlement_limitations"])),
        )
        results.append(
            evaluate_threshold_ordering(
                relation,
                lower_book,
                higher_book,
                evaluation_time=when,
                max_age=max_age,
                max_skew=max_skew,
                input_status=EvidenceStatus.OBSERVED,
            )
        )
    return tuple(results)


def _metadata(
    shared: Mapping[str, object], item: Mapping[str, object]
) -> tuple[CpiContractMetadata, OrderBook]:
    quote = item.get("quote")
    if not isinstance(quote, Mapping):
        raise DomainValidationError("contract quote is required")
    meta = CpiContractMetadata.from_mapping(
        {
            "venue_id": "kalshi",
            "venue_name": "Kalshi",
            "market_id": item.get("market_id"),
            "ticker": item.get("contract_id"),
            "title": item.get("title"),
            "yes_subtitle": item.get("yes_subtitle"),
            "event_id": item.get("event_id"),
            "threshold": item.get("threshold"),
            "yes_semantics": item.get("yes_semantics"),
            "underlying": shared["underlying"],
            "observation_window": shared["observation_window"],
            "unit": shared["unit"],
            "source": shared["source"],
            "rules_primary": item.get("rules_primary"),
            "evidence_refs": item.get("evidence_refs"),
            "evidence_status": shared["metadata_status"],
        }
    )
    bids = (
        PriceLevel(
            to_decimal(quote["yes_bid"], field="yes_bid"),
            to_decimal(quote["yes_bid_size"], field="yes_bid_size"),
        ),
    )
    asks = (
        PriceLevel(
            to_decimal(quote["yes_ask"], field="yes_ask"),
            to_decimal(quote["yes_ask_size"], field="yes_ask_size"),
        ),
    )
    return meta, OrderBook(
        meta.contract,
        bids,
        asks,
        _timestamp(quote["observed_at"], "quote observed_at"),
    )


def _validate_snapshot(snapshot: dict[str, object]) -> None:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise DomainValidationError("unsupported snapshot schema")
    for key in ("observed_at", *_REQUIRED_SHARED, "metadata_status", "ordinary_proof_status"):
        if not isinstance(snapshot.get(key), str) or not snapshot[key]:
            raise DomainValidationError(f"snapshot field {key} is required")
    _timestamp(snapshot["observed_at"], "observed_at")
    contracts = snapshot.get("contracts")
    if not isinstance(contracts, (list, tuple)) or len(contracts) < 2:
        raise DomainValidationError("snapshot requires at least two contracts")
    if snapshot.get("contract_count") != len(contracts):
        raise DomainValidationError("snapshot contract_count is inconsistent")
    if snapshot.get("pair_count") != len(contracts) - 1:
        raise DomainValidationError("snapshot pair_count is inconsistent")
    for item in contracts:
        if not isinstance(item, Mapping):
            raise DomainValidationError("snapshot contract must be an object")
        required = (
            "market_id",
            "contract_id",
            "title",
            "yes_subtitle",
            "event_id",
            "threshold",
            "yes_semantics",
            "rules_primary",
            "quote",
        )
        for key in required:
            if key not in item:
                raise DomainValidationError(f"snapshot contract missing {key}")
        if not isinstance(item["quote"], Mapping):
            raise DomainValidationError("snapshot quote must be an object")
        for key in ("observed_at", "yes_bid", "yes_bid_size", "yes_ask", "yes_ask_size"):
            if key not in item["quote"]:
                raise DomainValidationError(f"snapshot quote missing {key}")
            if key == "observed_at":
                _timestamp(item["quote"][key], "quote observed_at")
            else:
                _decimal_text(item["quote"][key], key)
    snapshot["contracts"] = tuple(contracts)
    limits = snapshot.get("settlement_limitations", ())
    if not isinstance(limits, (list, tuple)) or any(not isinstance(x, str) for x in limits):
        raise DomainValidationError("settlement_limitations must be text values")
    snapshot["settlement_limitations"] = tuple(limits)


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainValidationError(f"{field} must be an ISO timestamp") from exc
    require_aware(parsed, field=field)
    return parsed.astimezone(UTC)


def _decimal_text(value: object, field: str) -> str:
    if not isinstance(value, (str, Decimal)):
        raise DomainValidationError(f"{field} must be a decimal string")
    parsed = to_decimal(value, field=field)
    return str(parsed)


def _threshold_from_ticker(ticker: str) -> str:
    if "-T" not in ticker:
        raise DomainValidationError("CPI ticker does not contain a threshold")
    value = ticker.rsplit("-T", 1)[1]
    if value.startswith("-"):
        value = "-" + value[1:]
    parsed = to_decimal(value, field="threshold")
    return str(parsed)
