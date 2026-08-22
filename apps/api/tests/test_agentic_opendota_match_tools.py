from __future__ import annotations

from app.agentic.models import QueryContext, ToolResult
from app.agentic.tools.opendota_match_tools import (
    DotaExtractMatchPlayerProgressInput,
    extract_match_player_progress,
    match_details_evidence,
    match_player_progress_evidence,
)
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
    assert summary["players"][0]["hero_image_path"] == "/api/v1/assets/dota/heroes/80.png"
    assert summary["players"][0]["final_items"]["item_0"] == 1
    assert summary["players"][0]["final_item_details"]["item_0"] == {
        "item_id": 1,
        "item_name_en": item.name_en,
        "item_name_zh": item.name_zh,
        "item_catalog_status": "resolved",
        "item_image_path": "/api/v1/assets/dota/items/1.png",
    }
    assert summary["players"][0]["neutral_item_detail"] == {
        "item_id": 3,
        "item_name_en": catalog.get_item(3).name_en,
        "item_name_zh": catalog.get_item(3).name_zh,
        "item_catalog_status": "resolved",
        "item_image_path": "/api/v1/assets/dota/items/3.png",
    }
    assert summary["players"][0]["backpack_item_details"]["item_0"] == {
        "item_id": 2,
        "item_name_en": catalog.get_item(2).name_en,
        "item_name_zh": catalog.get_item(2).name_zh,
        "item_catalog_status": "resolved",
        "item_image_path": "/api/v1/assets/dota/items/2.png",
    }
    assert draft["draft"][1]["hero_name_en"] == picked_hero.name_en
    assert draft["draft"][1]["hero_name_zh"] == picked_hero.name_zh
    assert draft["draft"][1]["hero_image_path"] == "/api/v1/assets/dota/heroes/85.png"
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

    scoreboard_player = next(
        item for item in evidence if item.kind == "player_scoreboard"
    ).value["players"][0]
    assert scoreboard_player["inventory"]["main"][0]["item_id"] == 1
    assert scoreboard_player["purchase_event_count"] == 0
    assert scoreboard_player["ability_upgrade_count"] == 0
    assert scoreboard_player["talent_selection_count"] == 0
    assert "purchase_timeline" not in scoreboard_player
    assert "ability_upgrade_sequence" not in scoreboard_player
    assert "talent_selections" not in scoreboard_player

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
    assert player["hero_image_path"] is None
    assert player["final_item_details"]["item_0"] == {
        "item_id": 999999,
        "item_name_en": None,
        "item_name_zh": None,
        "item_catalog_status": "not_found",
        "item_image_path": None,
    }
    assert player["neutral_item_detail"] is None
    assert draft["draft"][0]["hero_name_en"] is None
    assert draft["draft"][0]["hero_catalog_status"] == "not_found"
    assert draft["draft"][0]["hero_image_path"] is None


def test_absent_catalog_ids_have_null_image_paths() -> None:
    summary = normalize_match_summary(
        {"players": [{"hero_id": None, "item_0": None}]},
        8943244303,
    )
    player = summary["players"][0]
    assert player["hero_catalog_status"] == "absent"
    assert player["hero_image_path"] is None
    assert player["final_item_details"] == {}


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


def test_player_progress_and_inventory_are_normalized_without_reordering() -> None:
    raw = _raw_match()
    raw["players"][0].update(
        {
            "purchase_log": [
                {"time": -89, "key": "tango", "charges": 3},
                {"time": 0, "key": "item_clarity"},
                {"time": 0, "key": "unknown_item"},
            ],
            "item_0": 44,
            "item_neutral": "item_tango",
            "item_neutral2": "item_clarity",
            "neutral_item_history": [
                {
                    "time": 526,
                    "item_neutral": "item_tango",
                    "item_neutral_enhancement": "item_clarity",
                }
            ],
            "ability_upgrades_arr": [
                5154,
                {"ability_id": 303},
                {"ability_id": 999999, "internal_name": "special_bonus_attributes"},
            ],
        }
    )

    summary = normalize_match_summary(raw, 8943244303)
    player = summary["players"][0]

    assert [event["time_seconds"] for event in player["purchase_timeline"]] == [-89, 0, 0]
    assert [event["item_key"] for event in player["purchase_timeline"]] == [
        "tango",
        "item_clarity",
        "unknown_item",
    ]
    assert player["purchase_timeline"][0]["item_id"] == 44
    assert player["purchase_timeline"][0]["charges"] == 3
    assert player["purchase_timeline"][2]["item_catalog_status"] == "not_found"
    assert player["inventory"]["main"][0]["item_id"] == 44
    assert player["inventory"]["main"][1:] == [None] * 5
    assert player["inventory"]["neutral"]["item"]["item_id"] == 44
    assert player["inventory"]["neutral"]["enhancement"]["item_catalog_status"] == (
        "resolved"
    )
    assert player["inventory"]["neutral_history"][0]["time_seconds"] == 526
    assert player["inventory"]["neutral_history"][0]["item"]["item_id"] == 44
    assert [row["level"] for row in player["ability_upgrade_sequence"]] == [1, 2, 3]
    assert [row["kind"] for row in player["ability_upgrade_sequence"]] == [
        "ability",
        "talent",
        "attribute_bonus",
    ]
    assert [row["level_taken"] for row in player["talent_selections"]] == [2]

    result = ToolResult(
        tool_call_id="progress",
        tool="opendota.match_details",
        status="ok",
        data={
            "valve_match_ids": [8943244303],
            "matches": [
                {
                    "valve_match_id": 8943244303,
                    "summary": summary,
                    "draft": normalize_match_draft(raw, 8943244303),
                }
            ],
        },
        latency_ms=1,
    )
    assert {
        item.kind for item in match_details_evidence(result)
    } == {
        "match_result",
        "player_scoreboard",
        "match_parse_status",
        "match_draft",
    }

    scoreboard_player = next(
        item for item in match_details_evidence(result) if item.kind == "player_scoreboard"
    ).value["players"][0]
    assert scoreboard_player["purchase_event_count"] == 3
    assert scoreboard_player["ability_upgrade_count"] == 3
    assert scoreboard_player["talent_selection_count"] == 1
    assert "purchase_timeline" not in scoreboard_player
    assert "ability_upgrade_sequence" not in scoreboard_player
    assert "talent_selections" not in scoreboard_player

    progress_result = extract_match_player_progress(
        DotaExtractMatchPlayerProgressInput(
            matches=result.data["matches"],
            player_query="Player 0",
            aspects=["purchase_timeline", "ability_upgrade_sequence", "talent_selections"],
        ),
        QueryContext(),
    )
    progress_tool_result = ToolResult(
        tool_call_id="progress_extract",
        tool="dota.extract_match_player_progress",
        status="ok",
        data=progress_result,
        latency_ms=0,
    )
    progress_evidence = {
        item.kind: item.value["players"][0]
        for item in match_player_progress_evidence(progress_tool_result)
    }
    assert {item.kind for item in match_details_evidence(result)}.isdisjoint(
        {"player_purchase_timeline", "player_skill_build", "player_talent_selection"}
    )
    assert set(progress_evidence["player_purchase_timeline"]) == {
        "name",
        "personaname",
        "player_slot",
        "hero_id",
        "hero_name_en",
        "hero_name_zh",
        "hero_image_path",
        "hero_catalog_status",
        "purchase_timeline",
    }
    assert set(progress_evidence["player_skill_build"]) == {
        "name",
        "personaname",
        "player_slot",
        "hero_id",
        "hero_name_en",
        "hero_name_zh",
        "hero_image_path",
        "hero_catalog_status",
        "ability_upgrade_sequence",
    }
    assert set(progress_evidence["player_talent_selection"]) == {
        "name",
        "personaname",
        "player_slot",
        "hero_id",
        "hero_name_en",
        "hero_name_zh",
        "hero_image_path",
        "hero_catalog_status",
        "talent_selections",
    }


def test_player_progress_transform_returns_only_requested_aspects() -> None:
    raw = _raw_match()
    raw["players"][0]["purchase_log"] = [{"time": 12, "key": "tango"}]
    summary = normalize_match_summary(raw, 8943244303)
    output = extract_match_player_progress(
        DotaExtractMatchPlayerProgressInput(
            matches=[{"valve_match_id": 8943244303, "summary": summary}],
            player_query="Player 0",
            aspects=["purchase_timeline", "purchase_timeline"],
        ),
        QueryContext(),
    )

    assert output["status"] == "resolved"
    row = output["matches"][0]
    assert row["player"]["name"] == "Player 0"
    assert "purchase_timeline" in row
    assert "ability_upgrade_sequence" not in row
    assert "talent_selections" not in row


def test_zero_valued_inventory_slots_are_empty() -> None:
    summary = normalize_match_summary(
        {
            "players": [
                {
                    "item_0": 0,
                    "backpack_0": "0",
                    "item_neutral": 0,
                    "item_neutral2": "0",
                }
            ]
        },
        8943244303,
    )

    inventory = summary["players"][0]["inventory"]
    assert inventory["main"][0] is None
    assert inventory["backpack"][0] is None
    assert inventory["neutral"] == {"item": None, "enhancement": None}


def test_unparsed_match_does_not_emit_player_progress_evidence() -> None:
    raw = _raw_match()
    raw["version"] = None
    raw["players"][0]["purchase_log"] = [{"time": 1, "key": "tango"}]
    raw["players"][0]["ability_upgrades_arr"] = [5154]
    summary = normalize_match_summary(raw, 8943244303)
    result = ToolResult(
        tool_call_id="unparsed",
        tool="opendota.match_details",
        status="ok",
        data={
            "valve_match_ids": [8943244303],
            "matches": [
                {
                    "valve_match_id": 8943244303,
                    "summary": summary,
                    "draft": normalize_match_draft(raw, 8943244303),
                }
            ],
        },
        latency_ms=1,
    )

    kinds = {item.kind for item in match_details_evidence(result)}
    assert "player_purchase_timeline" not in kinds
    assert "player_skill_build" not in kinds
    assert "player_talent_selection" not in kinds


def test_catalog_internal_name_lookup_is_exact_and_accepts_item_prefix() -> None:
    catalog = load_default_catalog_repository()
    assert catalog.get_item_by_internal_name("tango").item_id == 44
    assert catalog.get_item_by_internal_name("item_tango").item_id == 44

    try:
        catalog.get_item_by_internal_name("tang")
    except LookupError:
        pass
    else:
        raise AssertionError("internal-name lookup must not use fuzzy matching")


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
