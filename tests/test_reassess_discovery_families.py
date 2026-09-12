"""Offline observation checks: source boundaries and event-balanced ranking."""

import importlib
from pathlib import Path

import pytest


def test_public_observer_counts_and_event_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    observer = importlib.import_module("reassess_discovery_families")
    monkeypatch.setattr(observer, "_TARGETS", (
        ("KXNFLGAME-SYNTHETIC-A", "synthetic-nfl-a"),
        ("KXMLBGAME-SYNTHETIC-B", "synthetic-mlb-b"),
    ))
    requests: list[str] = []
    copies = 1

    def get_event(url: str) -> dict[str, object]:
        requests.append(url)
        title = "Synthetic Alpha Beta game"
        if "external-api.kalshi.com" in url:
            ticker = url.split("/events/")[1].split("?")[0]
            return {"event_ticker": ticker, "series_ticker": ticker.split("-")[0],
                    "title": title, "markets": [
                        {"ticker": ticker + f"-CHILD{i}", "event_ticker": ticker,
                         "title": title, "status": "active", "floor_strike": 7.5}
                        for i in range(copies)]}
        slug = url.rsplit("/", 1)[1]
        league = "nfl" if "nfl" in slug else "mlb"
        sport = "football" if league == "nfl" else "baseball"
        markets = [{"slug": slug + suffix, "question": title, "comboEnabled": True,
                    "marketType": family, "sportsMarketType": f"{sport}_team_full_game_{kind}",
                    "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_" + v2,
                    "line": 7.5, "closed": False}
                   for suffix, family, kind, v2 in [
                       ("-winner", "moneyline", "winner", "MONEYLINE"),
                       ("-total", "totals", "total", "TOTAL"),
                       ("-spread", "spreads", "spread", "SPREAD")]]
        return {"slug": slug, "title": title, "markets": markets,
                "tags": [{"league": {"name": league.upper(), "slug": league}}]}

    monkeypatch.setattr(observer, "_get_event", get_event)
    first = observer.observe()
    assert len(requests) == 8
    assert all("/events/" in url and "book" not in url for url in requests)
    d = first["diagnostics"]
    assert d["family_policy"]["mlb_total_exclusions"] == 1
    assert d["family_incompatible_excluded"] == 3
    assert d["comparisons_considered"] == 36
    assert d["counts_reconcile"] is True
    assert first["ordinary_polymarket_families_retained_after_combo"][
        "baseball_team_full_game_total"] == 1
    assert len(first["research_ranking"]) == 3
    copies = 5
    second = observer.observe()
    assert {r["family"]: r["research_priority_score"] for r in first["research_ranking"]} == {
        r["family"]: r["research_priority_score"] for r in second["research_ranking"]}
    assert all(r["distinct_event_overlaps"] == 1 for r in second["research_ranking"])
