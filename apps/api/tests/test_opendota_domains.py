import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.matches import normalize_match_summary
from app.integrations.opendota.teams import OpenDotaTeams
from app.integrations.opendota.transport import OpenDotaTransport


def test_hero_domain_preserves_role_inference_and_enrichment() -> None:
    hero = {
        "localized_name": "Mars",
        "roles": ["Nuker"],
        "pub_pick": 100_000,
        "pro_pick": 30,
        "pro_win": 18,
        "pro_ban": 20,
        "5_pick": 100,
        "5_win": 55,
        "6_pick": 100,
        "6_win": 50,
        "7_pick": 100,
        "7_win": 52,
        "8_pick": 100,
        "8_win": 53,
    }

    enriched = OpenDotaHeroes.enrich(hero)

    assert enriched is not None
    assert enriched["role"] == "offlane"
    assert enriched["win_rate"] == 0.525
    assert enriched["pick_rate"] == 0.1
    assert enriched["pro_presence"] == 0.6


def test_team_domain_preserves_report_calculation() -> None:
    transport = OpenDotaTransport("https://api.opendota.test")
    heroes = OpenDotaHeroes(transport)
    teams = OpenDotaTeams(transport, heroes)
    now = int(time.time())
    teams.get_matches = AsyncMock(
        return_value=[
            {
                "match_id": 1,
                "start_time": now,
                "radiant": True,
                "radiant_win": True,
                "duration": 1800,
                "opposing_team_name": "Alpha",
            },
            {
                "match_id": 2,
                "start_time": now,
                "radiant": False,
                "radiant_win": True,
                "duration": 2400,
                "opposing_team_name": "Beta",
            },
        ]
    )
    teams.get_players = AsyncMock(
        return_value=[
            {"name": "Former Player", "is_current_team_member": False},
            {"name": "Player One", "is_current_team_member": True},
        ]
    )
    teams.aggregate_heroes = AsyncMock(
        return_value=[
            {
                "hero_id": 1,
                "localized_name": "Puck",
                "games_played": 2,
                "wins": 1,
            }
        ]
    )

    report = asyncio.run(
        teams.get_report_data(
            "Example Team",
            days=30,
            resolved_team={"team_id": 42, "name": "Example Team", "rating": 1200},
        )
    )

    assert report is not None
    assert report["recent_record"] == "1-1 in last 2 matches"
    assert report["matches_in_window"] == 2
    assert report["match_details_analyzed"] == 2
    assert report["data_freshness"] == {
        "latest_match_time": now,
        "latest_match_at": datetime.fromtimestamp(now, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "sample_window_days": 30,
        "matches_in_window": 2,
        "match_details_analyzed": 2,
        "opendota_cache_hits": 0,
        "opendota_cache_misses": 0,
    }
    assert report["signature_heroes"] == ["Puck"]
    assert report["hero_pool_depth"] == 1
    assert report["draft_flexibility"] == 0.04
    assert report["patch_adaptation_score"] == 27
    assert report["key_players"] == ["Player One"]
    assert report["recent_win_rate"] == 0.5


def test_team_domain_uses_full_window_and_default_detail_sample() -> None:
    transport = OpenDotaTransport("https://api.opendota.test")
    teams = OpenDotaTeams(transport, OpenDotaHeroes(transport))
    now = int(time.time())
    matches = [
        {
            "match_id": match_id,
            "start_time": now,
            "radiant": True,
            "radiant_win": match_id % 2 == 0,
            "duration": 1800,
        }
        for match_id in range(75)
    ]
    teams.get_matches = AsyncMock(return_value=matches)
    teams.get_players = AsyncMock(return_value=[])
    teams.aggregate_heroes = AsyncMock(return_value=[])

    report = asyncio.run(
        teams.get_report_data(
            "Example Team",
            days=30,
            resolved_team={"team_id": 42, "name": "Example Team"},
        )
    )

    assert report is not None
    assert report["matches_in_window"] == 75
    assert report["match_details_analyzed"] == 50
    assert report["data_freshness"]["sample_window_days"] == 30
    assert report["data_freshness"]["matches_in_window"] == 75
    assert report["data_freshness"]["match_details_analyzed"] == 50
    assert report["recent_record"] == "38-37 in last 75 matches"
    detail_matches = teams.aggregate_heroes.await_args.args[0]
    assert len(detail_matches) == 50


def test_team_domain_caps_requested_detail_sample_at_100() -> None:
    transport = OpenDotaTransport("https://api.opendota.test")
    teams = OpenDotaTeams(
        transport,
        OpenDotaHeroes(transport),
        max_detail_sample_size=500,
    )
    now = int(time.time())
    matches = [
        {
            "match_id": match_id,
            "start_time": now,
            "radiant": True,
            "radiant_win": True,
            "duration": 1800,
        }
        for match_id in range(120)
    ]
    teams.get_matches = AsyncMock(return_value=matches)
    teams.get_players = AsyncMock(return_value=[])
    teams.aggregate_heroes = AsyncMock(return_value=[])

    report = asyncio.run(
        teams.get_report_data(
            "Example Team",
            days=30,
            detail_sample_size=500,
            resolved_team={"team_id": 42, "name": "Example Team"},
        )
    )

    assert report is not None
    assert report["matches_in_window"] == 120
    assert report["match_details_analyzed"] == 100
    detail_matches = teams.aggregate_heroes.await_args.args[0]
    assert len(detail_matches) == 100


def test_team_domain_limits_match_detail_concurrency() -> None:
    transport = OpenDotaTransport("https://api.opendota.test")
    heroes = OpenDotaHeroes(transport)
    teams = OpenDotaTeams(transport, heroes, detail_concurrency=2)
    active = 0
    max_active = 0

    async def get_match_detail(_match_id: int) -> dict:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"players": [], "radiant_win": True}

    teams.get_match_detail = get_match_detail
    heroes.name_map = AsyncMock(return_value={})

    asyncio.run(
        teams.aggregate_heroes(
            [{"match_id": match_id, "radiant": True} for match_id in range(8)]
        )
    )

    assert max_active == 2


def test_match_domain_preserves_parsed_player_progress_fields() -> None:
    summary = normalize_match_summary(
        {
            "version": 22,
            "players": [
                {
                    "purchase_log": [{"time": -89, "key": "tango"}],
                    "ability_upgrades_arr": [5154],
                    "neutral_item_history": [
                        {"time": 526, "item_neutral": "item_tango"}
                    ],
                }
            ],
        },
        8943244303,
    )
    player = summary["players"][0]

    assert player["purchase_timeline"][0]["time_seconds"] == -89
    assert player["ability_upgrade_sequence"][0]["level"] == 1
    assert player["inventory"]["neutral_history"][0]["time_seconds"] == 526
