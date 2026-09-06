"""Loader + validator for the manual verified market-pair registry (M1.4).

Reads a TOML file (stdlib ``tomllib`` — no new dependency) into
:class:`MarketPairRecord`s and enforces every rule a human reviewer relies on.
The registry **fails closed**: any malformed record, unknown status, duplicate
id, or unsafe/conflicting mapping raises :class:`RegistryError` and no registry
is returned.

``MarketPairRegistry.eligible()`` returns **only** ``VERIFIED`` pairs. DRAFT,
REVIEW_REQUIRED, REJECTED and SUSPENDED pairs can never reach it.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .models import (
    ELIGIBLE_STATUSES,
    REQUIRED_CHECKLIST_KEYS,
    MarketPairRecord,
    OutcomeRelation,
    PairStatus,
    RegistryError,
    VenueLeg,
)

#: Canonical curated registry shipped with the package.
DEFAULT_REGISTRY_PATH = Path(__file__).parent / "data" / "market_pairs.toml"

_SCHEMA_VERSION = 1
_LEG_SPECS: tuple[tuple[str, str], ...] = (
    ("kalshi", "kalshi"),
    ("polymarket_us", "polymarket_us"),
)

_TOP_LEVEL_KEYS = frozenset({"schema_version", "pair"})
_RECORD_KEYS = frozenset(
    {
        "pair_id",
        "proposition",
        "status",
        "relation",
        "kalshi",
        "polymarket_us",
        "settlement_notes",
        "known_differences",
        "known_differences_reviewed",
        "checklist",
        "reviewer",
        "verified_at",
        "live_use_eligible",
        "blocking_reason",
        "notes",
    }
)
_LEG_KEYS = frozenset({"venue", "market_id", "outcome", "sources"})


class MarketPairRegistry:
    """An immutable, fully-validated set of reviewed market-pair records."""

    def __init__(self, records: Sequence[MarketPairRecord]) -> None:
        self._records: tuple[MarketPairRecord, ...] = tuple(records)
        self._by_id = {record.pair_id: record for record in self._records}

    def all(self) -> tuple[MarketPairRecord, ...]:
        """Every record, regardless of status."""
        return self._records

    def eligible(self) -> tuple[MarketPairRecord, ...]:
        """Only pairs that later strategy code may compare — VERIFIED only.

        This is **not** a live-trading approval; see ``docs/MARKET_PAIRING.md``
        and ``docs/ASSUMPTIONS.md`` (A-001, A-013/A-015/A-016, Real-money gate).
        """
        return tuple(r for r in self._records if r.status in ELIGIBLE_STATUSES)

    def by_status(self, status: PairStatus) -> tuple[MarketPairRecord, ...]:
        return tuple(r for r in self._records if r.status == status)

    def get(self, pair_id: str) -> MarketPairRecord | None:
        return self._by_id.get(pair_id)


def load_registry(path: Path | None = None) -> MarketPairRegistry:
    """Load and validate the registry from ``path`` (default: the shipped file)."""
    resolved = path if path is not None else DEFAULT_REGISTRY_PATH
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read registry file {resolved}: {exc}") from exc
    return load_registry_text(text, source=str(resolved))


def load_registry_text(text: str, *, source: str = "<string>") -> MarketPairRegistry:
    """Load and validate a registry from a TOML string."""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"{source}: invalid TOML: {exc}") from exc

    _reject_unknown_keys(parsed, _TOP_LEVEL_KEYS, ctx=source)

    schema_version = parsed.get("schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise RegistryError(
            f"{source}: schema_version must be {_SCHEMA_VERSION}, got {schema_version!r}"
        )

    raw_pairs = parsed.get("pair", [])
    if not isinstance(raw_pairs, list):
        raise RegistryError(f"{source}: 'pair' must be an array of tables")

    records: list[MarketPairRecord] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_pairs):
        ctx = f"{source} pair[{index}]"
        record = _parse_record(_as_table(raw, ctx=ctx), ctx=ctx)
        if record.pair_id in seen_ids:
            raise RegistryError(f"{ctx}: duplicate pair_id {record.pair_id!r}")
        seen_ids.add(record.pair_id)
        records.append(record)

    _reject_conflicting_mappings(records, source=source)
    return MarketPairRegistry(records)


# --------------------------------------------------------------------------- #
# Record parsing
# --------------------------------------------------------------------------- #


def _parse_record(table: dict[str, object], *, ctx: str) -> MarketPairRecord:
    _reject_unknown_keys(table, _RECORD_KEYS, ctx=ctx)

    pair_id = _req_str(table, "pair_id", ctx=ctx)
    ctx = f"{ctx} ({pair_id})"
    proposition = _req_str(table, "proposition", ctx=ctx)
    status = _parse_status(table.get("status"), ctx=ctx)
    relation = _parse_relation(table.get("relation"), ctx=ctx)

    kalshi = _parse_leg(table, "kalshi", "kalshi", ctx=ctx)
    polymarket_us = _parse_leg(table, "polymarket_us", "polymarket_us", ctx=ctx)

    settlement_notes = _opt_str(table, "settlement_notes", ctx=ctx)
    known_differences = _str_list(
        table.get("known_differences", []), ctx=f"{ctx}.known_differences"
    )
    known_differences_reviewed = _opt_bool(table, "known_differences_reviewed", ctx=ctx)
    checklist = _parse_checklist(table.get("checklist", {}), ctx=ctx)
    reviewer = _opt_str(table, "reviewer", ctx=ctx)
    verified_at = _parse_optional_timestamp(table.get("verified_at", ""), ctx=f"{ctx}.verified_at")
    live_use_eligible = _opt_bool(table, "live_use_eligible", ctx=ctx)
    blocking_reason = _opt_str(table, "blocking_reason", ctx=ctx)
    notes = _opt_str(table, "notes", ctx=ctx)

    _validate_live_use(live_use_eligible, blocking_reason, ctx=ctx)
    if status == PairStatus.VERIFIED:
        _validate_verified(
            ctx=ctx,
            reviewer=reviewer,
            verified_at=verified_at,
            settlement_notes=settlement_notes,
            kalshi=kalshi,
            polymarket_us=polymarket_us,
            checklist=checklist,
            known_differences=known_differences,
            known_differences_reviewed=known_differences_reviewed,
        )

    return MarketPairRecord(
        pair_id=pair_id,
        proposition=proposition,
        status=status,
        relation=relation,
        kalshi=kalshi,
        polymarket_us=polymarket_us,
        settlement_notes=settlement_notes,
        known_differences=known_differences,
        known_differences_reviewed=known_differences_reviewed,
        checklist=checklist,
        reviewer=reviewer,
        verified_at=verified_at,
        live_use_eligible=live_use_eligible,
        blocking_reason=blocking_reason,
        notes=notes,
    )


def _parse_status(value: object, *, ctx: str) -> PairStatus:
    if not isinstance(value, str):
        raise RegistryError(f"{ctx}: status must be a string")
    try:
        return PairStatus(value)
    except ValueError:
        allowed = ", ".join(s.value for s in PairStatus)
        raise RegistryError(
            f"{ctx}: unknown status {value!r} (fail closed; allowed: {allowed})"
        ) from None


def _parse_relation(value: object, *, ctx: str) -> OutcomeRelation:
    if not isinstance(value, str):
        raise RegistryError(f"{ctx}: relation must be a string")
    try:
        return OutcomeRelation(value)
    except ValueError:
        allowed = ", ".join(r.value for r in OutcomeRelation)
        raise RegistryError(
            f"{ctx}: unknown relation {value!r} (allowed: {allowed})"
        ) from None


def _parse_leg(table: dict[str, object], key: str, expected_venue: str, *, ctx: str) -> VenueLeg:
    leg_ctx = f"{ctx}.{key}"
    leg = _as_table(_require(table, key, ctx=ctx), ctx=leg_ctx)
    _reject_unknown_keys(leg, _LEG_KEYS, ctx=leg_ctx)
    venue = _req_str(leg, "venue", ctx=leg_ctx)
    if venue != expected_venue:
        raise RegistryError(f"{leg_ctx}.venue: must be {expected_venue!r}, got {venue!r}")
    return VenueLeg(
        venue=venue,
        market_id=_req_str(leg, "market_id", ctx=leg_ctx),
        outcome=_req_str(leg, "outcome", ctx=leg_ctx),
        sources=_str_list(leg.get("sources", []), ctx=f"{leg_ctx}.sources"),
    )


def _parse_checklist(value: object, *, ctx: str) -> tuple[tuple[str, bool], ...]:
    table = _as_table(value, ctx=f"{ctx}.checklist")
    unknown = set(table) - set(REQUIRED_CHECKLIST_KEYS)
    if unknown:
        raise RegistryError(f"{ctx}.checklist: unknown item(s) {sorted(unknown)}")
    items: list[tuple[str, bool]] = []
    for k, v in table.items():
        if not isinstance(v, bool):
            raise RegistryError(f"{ctx}.checklist.{k}: must be a boolean")
        items.append((k, v))
    return tuple(sorted(items))


# --------------------------------------------------------------------------- #
# VERIFIED-completeness + cross-record safety
# --------------------------------------------------------------------------- #


def _validate_live_use(live_use_eligible: bool, blocking_reason: str, *, ctx: str) -> None:
    if live_use_eligible:
        # M1.4 hard rule: no pair can be live-eligible while venue semantics and
        # cross-venue equivalence assumptions are unresolved (A-001/A-002/A-003,
        # A-013/A-015/A-016). See docs/MARKET_PAIRING.md + Real-money gate.
        raise RegistryError(
            f"{ctx}: live_use_eligible must be false in M1.4 — no pair is approved "
            "for live use while A-001/A-013/A-015/A-016 remain unresolved"
        )
    if not blocking_reason.strip():
        raise RegistryError(
            f"{ctx}: blocking_reason is required while live_use_eligible is false"
        )


def _validate_verified(
    *,
    ctx: str,
    reviewer: str,
    verified_at: datetime | None,
    settlement_notes: str,
    kalshi: VenueLeg,
    polymarket_us: VenueLeg,
    checklist: tuple[tuple[str, bool], ...],
    known_differences: tuple[str, ...],
    known_differences_reviewed: bool,
) -> None:
    if not reviewer.strip():
        raise RegistryError(f"{ctx}: VERIFIED pair requires a non-empty 'reviewer'")
    if verified_at is None:
        raise RegistryError(f"{ctx}: VERIFIED pair requires a 'verified_at' timestamp")
    if not settlement_notes.strip():
        raise RegistryError(f"{ctx}: VERIFIED pair requires non-empty 'settlement_notes'")
    if not kalshi.sources:
        raise RegistryError(f"{ctx}: VERIFIED pair requires primary-source refs for the Kalshi leg")
    if not polymarket_us.sources:
        raise RegistryError(
            f"{ctx}: VERIFIED pair requires primary-source refs for the Polymarket US leg"
        )
    check_map = dict(checklist)
    missing = [k for k in REQUIRED_CHECKLIST_KEYS if k not in check_map]
    if missing:
        raise RegistryError(f"{ctx}: VERIFIED pair is missing checklist item(s) {missing}")
    not_true = [k for k in REQUIRED_CHECKLIST_KEYS if check_map[k] is not True]
    if not_true:
        raise RegistryError(
            f"{ctx}: VERIFIED pair has un-affirmed checklist item(s) {not_true}"
        )
    if not known_differences and not known_differences_reviewed:
        raise RegistryError(
            f"{ctx}: VERIFIED pair with empty 'known_differences' must set "
            "'known_differences_reviewed = true' (a reviewer must affirm there are none)"
        )


def _reject_conflicting_mappings(records: Sequence[MarketPairRecord], *, source: str) -> None:
    seen_leg_pairs: dict[tuple[tuple[str, str, str], tuple[str, str, str]], str] = {}
    verified_leg_owner: dict[tuple[str, str, str], MarketPairRecord] = {}
    for record in records:
        leg_pair = (record.kalshi.identity(), record.polymarket_us.identity())
        if leg_pair in seen_leg_pairs:
            raise RegistryError(
                f"{source}: pair {record.pair_id!r} duplicates the venue mapping of "
                f"{seen_leg_pairs[leg_pair]!r}"
            )
        seen_leg_pairs[leg_pair] = record.pair_id

        if record.status != PairStatus.VERIFIED:
            continue
        for leg in (record.kalshi, record.polymarket_us):
            prior = verified_leg_owner.get(leg.identity())
            if prior is not None and prior.pair_id != record.pair_id:
                raise RegistryError(
                    f"{source}: VERIFIED pairs {prior.pair_id!r} and {record.pair_id!r} both "
                    f"map leg {leg.identity()} but to different counterparties"
                )
            verified_leg_owner[leg.identity()] = record


# --------------------------------------------------------------------------- #
# Small typed extractors — every wrong type fails loudly
# --------------------------------------------------------------------------- #


def _as_table(value: object, *, ctx: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RegistryError(f"{ctx}: expected a table, got {type(value).__name__}")
    return value


def _require(table: dict[str, object], key: str, *, ctx: str) -> object:
    if key not in table:
        raise RegistryError(f"{ctx}: missing required field {key!r}")
    return table[key]


def _req_str(table: dict[str, object], key: str, *, ctx: str) -> str:
    value = _require(table, key, ctx=ctx)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{ctx}: field {key!r} must be a non-empty string")
    return value


def _opt_str(table: dict[str, object], key: str, *, ctx: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise RegistryError(f"{ctx}: field {key!r} must be a string")
    return value


def _opt_bool(table: dict[str, object], key: str, *, ctx: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise RegistryError(f"{ctx}: field {key!r} must be a boolean")
    return value


def _str_list(value: object, *, ctx: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RegistryError(f"{ctx}: expected a list of strings")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise RegistryError(f"{ctx}[{index}]: must be a non-empty string")
        out.append(item)
    return tuple(out)


def _parse_optional_timestamp(value: object, *, ctx: str) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if not value.strip():
            return None
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise RegistryError(f"{ctx}: malformed timestamp {value!r}") from exc
    else:
        raise RegistryError(f"{ctx}: must be an RFC-3339 string or empty")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegistryError(f"{ctx}: timestamp {value!r} must be timezone-aware")
    return parsed


def _reject_unknown_keys(table: dict[str, object], allowed: frozenset[str], *, ctx: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise RegistryError(f"{ctx}: unknown field(s) {sorted(unknown)}")
