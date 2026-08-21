from __future__ import annotations

from app.agentic.models import ToolResult
from app.agentic.tools.opendota_match_tools import match_details_evidence
from app.integrations.opendota.matches import normalize_match_draft, normalize_match_summary
from app.integrations.valve.catalog_repository import load_default_catalog_repository


def _raw_match() -> dict:
    players = [
        {
            "player_slot": index * 2**8,
            "account_id": index + 1,
            "personaname": f"Player {index}",
            "hero_id": index + 1,
            "kills": 1,
            "deaths": 2,
            "assists": 3,
            "last_hits": 10,
            "denies": 1,
            "gold_per_min": 500,
            "xp_per_min": 600,
            "level": 20,
            "net_worth": 12000,
            "hero_damage": 1000,
            "tower_damage": 100,
            "hero_healing": 10,
            "item_0": 1,
            "backpack_0": 2,
            "item_neutral": 3,
        }
        for index in range(10)
    ]
    return {
        "start_time": 1,
        "duration": 3227,
        "radiant_win": True,
        "radiant_score": 20,
        "dire_score": 10,
        "players": players,
        "version": 22,
        "replay_url": "https://replay.invalid/1",
        "picks_bans": [
            {"order": 0, "is_pick": False, "team": 0, "hero_id": 112},
            {"order": 1, "is_pick": True, "team": 1, "hero_id": 3},
        ],
    }


def test_match_details_evidence_requires_ten_players() -> None:
    raw = _raw_match()
    raw["players"][0]["hero_id"] = 80
    raw["picks_bans"][1]["hero_id"] = 85
    summary = normalize_match_summary(raw, 8943244303)
    draft = normalize_match_draft(raw, 8943244303)
    catalog = load_default_catalog_repository()
    hero = catalog.get_hero(80)
    picked_hero = catalog.get_hero(85)
    item = catalog.get_item(1)
    data = {
        "valve_match_ids": [8943244303],
        "matches": [{"valve_match_id": 8943244303, "summary": summary, "draft": draft}],
    }
    assert summary["valve_match_id"] == 8943244303
    assert summary["match_id"] == 8943244303
    assert len(summary["players"]) == 10
    assert summary["players"][0]["hero_name_en"] == hero.name_en
    assert summary["players"][0]["hero_name_zh"] == hero.name_zh
    assert summary["players"][0]["hero_catalog_status"] == "resolved"
    assert summary["players"][0]["final_items"]["item_0"] == 1
    assert summary["players"][0]["final_item_details"]["item_0"] == {
        "item_id": 1,
        "item_name_en": item.name_en,
        "item_name_zh": item.name_zh,
        "item_catalog_status": "resolved",
    }
    assert summary["players"][0]["neutral_item_detail"] == {
        "item_id": 3,
        "item_name_en": catalog.get_item(3).name_en,
        "item_name_zh": catalog.get_item(3).name_zh,
        "item_catalog_status": "resolved",
    }
    assert draft["draft"][1]["hero_name_en"] == picked_hero.name_en
    assert draft["draft"][1]["hero_name_zh"] == picked_hero.name_zh
    result = ToolResult(
        tool_call_id="s1",
        tool="opendota.match_details",
        status="ok",
        data=data,
        latency_ms=1,
    )
    evidence = match_details_evidence(result)
    assert {item.kind for item in evidence} == {
        "match_result",
        "player_scoreboard",
        "match_parse_status",
        "match_draft",
    }
    assert next(item for item in evidence if item.kind == "player_scoreboard").value[
        "catalog_snapshot"
    ] == summary["catalog_snapshot"]
    assert next(item for item in evidence if item.kind == "match_draft").value[
        "catalog_snapshot"
    ] == draft["catalog_snapshot"]

    data["matches"][0]["summary"]["players"] = data["matches"][0]["summary"]["players"][:9]
    assert "player_scoreboard" not in {item.kind for item in match_details_evidence(result)}


def test_unknown_or_empty_catalog_ids_do_not_gain_invented_names() -> None:
    raw = _raw_match()
    raw["players"][0].update({"hero_id": 999999, "item_0": 999999, "item_neutral": 0})
    raw["picks_bans"][0]["hero_id"] = 999999

    summary = normalize_match_summary(raw, 8943244303)
    draft = normalize_match_draft(raw, 8943244303)

    player = summary["players"][0]
    assert player["hero_name_en"] is None
    assert player["hero_name_zh"] is None
    assert player["hero_catalog_status"] == "not_found"
    assert player["final_item_details"]["item_0"] == {
        "item_id": 999999,
        "item_name_en": None,
        "item_name_zh": None,
        "item_catalog_status": "not_found",
    }
    assert player["neutral_item_detail"] is None
    assert draft["draft"][0]["hero_name_en"] is None
    assert draft["draft"][0]["hero_catalog_status"] == "not_found"


def test_empty_draft_is_ok_data_but_produces_no_evidence() -> None:
    draft = normalize_match_draft({"picks_bans": []}, 8943244303)
    result = ToolResult(
        tool_call_id="d1",
        tool="opendota.match_details",
        status="ok",
        data={
            "valve_match_ids": [8943244303],
            "matches": [
                {
                    "valve_match_id": 8943244303,
                    "summary": normalize_match_summary({}, 8943244303),
                    "draft": draft,
                }
            ],
        },
        latency_ms=1,
    )
    assert draft["draft"] == []
    assert draft["match"]["match_id"] == 8943244303
    assert "match_draft" not in {item.kind for item in match_details_evidence(result)}


def test_draft_evidence_accepts_non_fixed_length_pick_ban_rows() -> None:
    draft = normalize_match_draft(_raw_match(), 8943244303)
    result = ToolResult(
        tool_call_id="d2",
        tool="opendota.match_details",
        status="ok",
        data={
            "valve_match_ids": [8943244303],
            "matches": [
                {
                    "valve_match_id": 8943244303,
                    "summary": normalize_match_summary({}, 8943244303),
                    "draft": draft,
                }
            ],
        },
        latency_ms=1,
    )
    evidence = match_details_evidence(result)
    assert "match_draft" in {item.kind for item in evidence}
