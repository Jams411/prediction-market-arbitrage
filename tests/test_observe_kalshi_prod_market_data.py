"""Deterministic tests for the pure helpers in
``scripts/observe_kalshi_prod_market_data.py``.

No network: only the sanitiser / book-parsing helpers are exercised. The script
itself is an unauthenticated, read-only production market-data observation and is
not run here.
"""

from __future__ import annotations

import observe_kalshi_prod_market_data as obs


def test_redact_keeps_structure_and_field_names_but_no_scalars() -> None:
    body = {
        "orderbook_fp": {
            "yes_dollars": [["0.42", "96.31"], ["0.41", "10.00"], ["0.40", "5.0"]],
            "no_dollars": [],
        },
        "ts": 1788000000,
        "flag": True,
        "missing": None,
    }
    out = obs._redact(body)
    assert set(out) == {"orderbook_fp", "ts", "flag", "missing"}
    assert set(out["orderbook_fp"]) == {"yes_dollars", "no_dollars"}
    # list truncated to 2 samples + an ellipsis marker; every price/size redacted
    assert out["orderbook_fp"]["yes_dollars"] == [
        ["<redacted>", "<redacted>"],
        ["<redacted>", "<redacted>"],
        "<...>",
    ]
    assert out["orderbook_fp"]["no_dollars"] == []
    assert out["ts"] == "<number>"
    assert out["flag"] is True  # booleans are structural
    assert out["missing"] is None
    assert "0.42" not in repr(out) and "96.31" not in repr(out)


def test_ob_levels_counts_each_side() -> None:
    body = {
        "orderbook_fp": {
            "yes_dollars": [["0.4", "1"]],
            "no_dollars": [["0.5", "1"], ["0.6", "1"]],
        }
    }
    assert obs._ob_levels(body) == (1, 2)
    assert obs._ob_levels({"orderbook_fp": {}}) == (0, 0)
    assert obs._ob_levels(None) == (0, 0)


def test_ob_fingerprint_changes_only_when_the_book_changes() -> None:
    a = {"orderbook_fp": {"yes_dollars": [["0.4", "1"]], "no_dollars": []}}
    a_again = {"orderbook_fp": {"yes_dollars": [["0.4", "1"]], "no_dollars": []}}
    b = {"orderbook_fp": {"yes_dollars": [["0.4", "2"]], "no_dollars": []}}
    assert obs._ob_fingerprint(a) == obs._ob_fingerprint(a_again)
    assert obs._ob_fingerprint(a) != obs._ob_fingerprint(b)


def test_prod_host_and_no_auth() -> None:
    assert obs.PROD_BASE_URL == "https://external-api.kalshi.com/trade-api/v2"
    src = obs.__doc__ or ""
    assert "Unauthenticated" in src or "unauthenticated" in src
