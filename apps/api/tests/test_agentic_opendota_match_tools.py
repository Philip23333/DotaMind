from __future__ import annotations

from app.agentic.models import ToolResult
from app.agentic.tools.opendota_match_tools import match_draft_evidence, match_summary_evidence
from app.integrations.opendota.matches import normalize_match_draft, normalize_match_summary


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


def test_match_summary_normalization_and_evidence_require_ten_players() -> None:
    data = normalize_match_summary(_raw_match(), 8943244303)
    assert data["valve_match_id"] == 8943244303
    assert data["match_id"] == 8943244303
    assert len(data["players"]) == 10
    result = ToolResult(
        tool_call_id="s1",
        tool="opendota.match_summary",
        status="ok",
        data=data,
        latency_ms=1,
    )
    assert {item.kind for item in match_summary_evidence(result)} == {
        "match_result",
        "player_scoreboard",
        "match_parse_status",
    }

    data["players"] = data["players"][:9]
    assert "player_scoreboard" not in {item.kind for item in match_summary_evidence(result)}


def test_empty_draft_is_ok_data_but_produces_no_evidence() -> None:
    data = normalize_match_draft({"picks_bans": []}, 8943244303)
    result = ToolResult(
        tool_call_id="d1",
        tool="opendota.match_draft",
        status="ok",
        data=data,
        latency_ms=1,
    )
    assert data["draft"] == []
    assert data["match"]["match_id"] == 8943244303
    assert match_draft_evidence(result) == []


def test_draft_evidence_accepts_non_fixed_length_pick_ban_rows() -> None:
    data = normalize_match_draft(_raw_match(), 8943244303)
    result = ToolResult(
        tool_call_id="d2",
        tool="opendota.match_draft",
        status="ok",
        data=data,
        latency_ms=1,
    )
    evidence = match_draft_evidence(result)
    assert len(evidence) == 1
    assert evidence[0].kind == "match_draft"
