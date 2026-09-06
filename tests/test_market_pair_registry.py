"""Deterministic, offline tests for the manual market-pair registry (M1.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prediction_market_arbitrage.registry import (
    REQUIRED_CHECKLIST_KEYS,
    OutcomeRelation,
    PairStatus,
    RegistryError,
    load_registry,
    load_registry_text,
)

_CHECKLIST_ALL_TRUE = "\n".join(f"  {key} = true" for key in REQUIRED_CHECKLIST_KEYS)


def _verified_toml(
    *,
    pair_id: str = "p-verified",
    status: str = "VERIFIED",
    relation: str = "COMPLEMENTARY",
    reviewer: str = '"alice"',
    verified_at: str = '"2026-01-02T03:04:05Z"',
    settlement_notes: str = '"reviewed both primary rule sets; economically equivalent"',
    known_differences: str = "[]",
    known_differences_reviewed: str = "true",
    kalshi_sources: str = '["https://kalshi.example/rules#rev1"]',
    poly_sources: str = '["https://poly.example/rules#rev1"]',
    kalshi_market: str = "kalshi-test-market",
    poly_market: str = "polymarket-test-market",
    checklist: str | None = None,
    extra_record_lines: str = "",
) -> str:
    check_block = _CHECKLIST_ALL_TRUE if checklist is None else checklist
    return f"""schema_version = 1

[[pair]]
pair_id = "{pair_id}"
proposition = "synthetic verified example — not a real candidate"
status = "{status}"
relation = "{relation}"
settlement_notes = {settlement_notes}
known_differences = {known_differences}
known_differences_reviewed = {known_differences_reviewed}
reviewer = {reviewer}
verified_at = {verified_at}
live_use_eligible = false
blocking_reason = "VERIFIED for paper analysis only; live use blocked by A-001/A-013"
notes = ""
{extra_record_lines}
  [pair.kalshi]
  venue = "kalshi"
  market_id = "{kalshi_market}"
  outcome = "YES"
  sources = {kalshi_sources}

  [pair.polymarket_us]
  venue = "polymarket_us"
  market_id = "{poly_market}"
  outcome = "SHORT"
  sources = {poly_sources}

  [pair.checklist]
{check_block}
"""


def _draft_toml(pair_id: str = "p-draft", *, status: str = "DRAFT") -> str:
    return f"""schema_version = 1

[[pair]]
pair_id = "{pair_id}"
proposition = "synthetic draft example"
status = "{status}"
relation = "COMPLEMENTARY"
settlement_notes = "not reviewed"
known_differences = []
known_differences_reviewed = false
reviewer = ""
verified_at = ""
live_use_eligible = false
blocking_reason = "not reviewed"
notes = ""

  [pair.kalshi]
  venue = "kalshi"
  market_id = "kalshi-test-market-draft"
  outcome = "YES"
  sources = []

  [pair.polymarket_us]
  venue = "polymarket_us"
  market_id = "polymarket-test-market-draft"
  outcome = "SHORT"
  sources = []

  [pair.checklist]
  same_underlying_event = false
"""


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #


def test_valid_draft_pair_loads() -> None:
    registry = load_registry_text(_draft_toml())
    assert len(registry.all()) == 1
    assert registry.all()[0].status is PairStatus.DRAFT
    assert registry.eligible() == ()


def test_valid_verified_pair_loads_and_is_eligible() -> None:
    registry = load_registry_text(_verified_toml())
    record = registry.all()[0]
    assert record.status is PairStatus.VERIFIED
    assert record.relation is OutcomeRelation.COMPLEMENTARY
    assert record.reviewer == "alice"
    assert record.verified_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert record.kalshi.identity() == ("kalshi", "kalshi-test-market", "YES")
    assert record.polymarket_us.identity() == (
        "polymarket_us",
        "polymarket-test-market",
        "SHORT",
    )
    assert registry.eligible() == (record,)
    assert registry.get("p-verified") is record


def test_shipped_registry_is_empty_and_loads() -> None:
    # The canonical version-controlled registry ships with ZERO pairs: no
    # cross-venue pair has been human-verified, and no real venue identifiers
    # appear in the file. It must still load cleanly.
    registry = load_registry()
    assert registry.all() == ()
    assert registry.eligible() == ()


# --------------------------------------------------------------------------- #
# VERIFIED completeness
# --------------------------------------------------------------------------- #


def test_verified_missing_reviewer_fails() -> None:
    with pytest.raises(RegistryError, match="reviewer"):
        load_registry_text(_verified_toml(reviewer='""'))


def test_verified_missing_timestamp_fails() -> None:
    with pytest.raises(RegistryError, match="verified_at"):
        load_registry_text(_verified_toml(verified_at='""'))


def test_verified_naive_timestamp_fails() -> None:
    with pytest.raises(RegistryError, match="timezone-aware"):
        load_registry_text(_verified_toml(verified_at='"2026-01-02T03:04:05"'))


def test_verified_missing_settlement_notes_fails() -> None:
    with pytest.raises(RegistryError, match="settlement_notes"):
        load_registry_text(_verified_toml(settlement_notes='""'))


@pytest.mark.parametrize("field", ["kalshi_sources", "poly_sources"])
def test_verified_requires_sources_for_both_legs(field: str) -> None:
    with pytest.raises(RegistryError, match="source"):
        load_registry_text(_verified_toml(**{field: "[]"}))


def test_verified_incomplete_checklist_fails() -> None:
    partial = "\n".join(f"  {k} = true" for k in REQUIRED_CHECKLIST_KEYS[:-1])
    with pytest.raises(RegistryError, match="checklist item"):
        load_registry_text(_verified_toml(checklist=partial))


def test_verified_unaffirmed_checklist_item_fails() -> None:
    one_false = "\n".join(
        f"  {k} = {'false' if k == 'same_timezone' else 'true'}" for k in REQUIRED_CHECKLIST_KEYS
    )
    with pytest.raises(RegistryError, match="un-affirmed checklist"):
        load_registry_text(_verified_toml(checklist=one_false))


def test_verified_empty_known_differences_requires_reviewed_flag() -> None:
    with pytest.raises(RegistryError, match="known_differences_reviewed"):
        load_registry_text(
            _verified_toml(known_differences="[]", known_differences_reviewed="false")
        )
    # explicitly reviewed -> allowed
    registry = load_registry_text(
        _verified_toml(known_differences="[]", known_differences_reviewed="true")
    )
    assert registry.eligible()[0].known_differences == ()


def test_verified_with_listed_known_differences_loads() -> None:
    registry = load_registry_text(
        _verified_toml(
            known_differences='["Kalshi rounds to whole degrees; Polymarket US does not."]',
            known_differences_reviewed="false",
        )
    )
    assert registry.eligible()[0].known_differences == (
        "Kalshi rounds to whole degrees; Polymarket US does not.",
    )


# --------------------------------------------------------------------------- #
# Status / mapping validity — fail closed
# --------------------------------------------------------------------------- #


def test_unknown_status_fails_closed() -> None:
    with pytest.raises(RegistryError, match="unknown status"):
        load_registry_text(_verified_toml(status="MAYBE"))


def test_unknown_relation_fails() -> None:
    with pytest.raises(RegistryError, match="unknown relation"):
        load_registry_text(_verified_toml(relation="OPPOSITE"))


def test_duplicate_pair_id_fails() -> None:
    doubled = _verified_toml() + _verified_toml(poly_market="polymarket-test-market-2").split(
        "schema_version = 1", 1
    )[1]
    with pytest.raises(RegistryError, match="duplicate pair_id"):
        load_registry_text(doubled)


@pytest.mark.parametrize(
    "toml_text",
    [
        # empty pair_id
        _verified_toml().replace('pair_id = "p-verified"', 'pair_id = ""'),
        # empty kalshi market_id
        _verified_toml().replace('market_id = "kalshi-test-market"', 'market_id = ""'),
        # empty outcome
        _verified_toml().replace('outcome = "YES"', 'outcome = ""'),
        # wrong venue literal
        _verified_toml().replace('venue = "kalshi"', 'venue = "polymarket_us"'),
    ],
)
def test_malformed_identifiers_fail(toml_text: str) -> None:
    with pytest.raises(RegistryError):
        load_registry_text(toml_text)


def test_live_use_eligible_true_is_rejected_in_m14() -> None:
    with pytest.raises(RegistryError, match="live_use_eligible must be false"):
        load_registry_text(
            _verified_toml().replace(
                "live_use_eligible = false", "live_use_eligible = true"
            )
        )


def test_missing_blocking_reason_fails() -> None:
    with pytest.raises(RegistryError, match="blocking_reason"):
        load_registry_text(
            _verified_toml().replace(
                'blocking_reason = "VERIFIED for paper analysis only; '
                'live use blocked by A-001/A-013"',
                'blocking_reason = ""',
            )
        )


# --------------------------------------------------------------------------- #
# Cross-record safety
# --------------------------------------------------------------------------- #


def test_duplicate_venue_mapping_fails() -> None:
    body = _verified_toml(pair_id="p-b").split("schema_version = 1", 1)[1]
    with pytest.raises(RegistryError, match="duplicates the venue mapping"):
        load_registry_text(_verified_toml(pair_id="p-a") + body)


def test_conflicting_verified_leg_mapping_fails() -> None:
    body = _verified_toml(pair_id="p-b", poly_market="polymarket-test-market-2").split(
        "schema_version = 1", 1
    )[1]
    with pytest.raises(RegistryError, match="different counterparties"):
        load_registry_text(_verified_toml(pair_id="p-a") + body)


# --------------------------------------------------------------------------- #
# eligible() membership by status
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["DRAFT", "REVIEW_REQUIRED", "REJECTED", "SUSPENDED"])
def test_non_verified_statuses_excluded_from_eligible(status: str) -> None:
    registry = load_registry_text(_draft_toml(status=status))
    assert registry.all()[0].status == PairStatus(status)
    assert registry.eligible() == ()


def test_verified_included_others_excluded_in_mixed_registry() -> None:
    verified_body = _verified_toml(
        pair_id="p-ok",
        kalshi_market="kalshi-test-market-ok",
        poly_market="polymarket-test-market-ok",
    ).split("schema_version = 1", 1)[1]
    draft_body = _draft_toml("p-draft").split("schema_version = 1", 1)[1]
    registry = load_registry_text("schema_version = 1\n" + verified_body + draft_body)
    eligible_ids = [r.pair_id for r in registry.eligible()]
    assert eligible_ids == ["p-ok"]
    assert {r.pair_id for r in registry.all()} == {"p-ok", "p-draft"}


# --------------------------------------------------------------------------- #
# Fail closed on malformed files
# --------------------------------------------------------------------------- #


def test_invalid_toml_fails() -> None:
    with pytest.raises(RegistryError, match="invalid TOML"):
        load_registry_text("this is [ not valid toml")


def test_wrong_schema_version_fails() -> None:
    with pytest.raises(RegistryError, match="schema_version"):
        load_registry_text(_verified_toml().replace("schema_version = 1", "schema_version = 2"))


def test_unknown_top_level_key_fails() -> None:
    text = _verified_toml().replace("schema_version = 1", "schema_version = 1\nfoo = 1")
    with pytest.raises(RegistryError, match="unknown field"):
        load_registry_text(text)


def test_unknown_record_key_fails() -> None:
    with pytest.raises(RegistryError, match="unknown field"):
        load_registry_text(_verified_toml(extra_record_lines='bogus_field = "x"'))


def test_unknown_checklist_key_fails() -> None:
    bad = _CHECKLIST_ALL_TRUE + "\n  not_a_real_check = true"
    with pytest.raises(RegistryError, match="unknown item"):
        load_registry_text(_verified_toml(checklist=bad))


def test_non_bool_checklist_value_fails() -> None:
    bad = _CHECKLIST_ALL_TRUE.replace("same_timezone = true", 'same_timezone = "yes"')
    with pytest.raises(RegistryError, match="must be a boolean"):
        load_registry_text(_verified_toml(checklist=bad))


def test_missing_leg_table_fails() -> None:
    text = _verified_toml()
    text = text[: text.index("  [pair.polymarket_us]")]
    with pytest.raises(RegistryError, match="polymarket_us"):
        load_registry_text(text + "\n  [pair.checklist]\n" + _CHECKLIST_ALL_TRUE + "\n")
