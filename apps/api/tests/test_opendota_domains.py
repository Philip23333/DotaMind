import asyncio
import time
from unittest.mock import AsyncMock

from app.integrations.opendota.heroes import OpenDotaHeroes
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
    teams.get_players = AsyncMock(return_value=[{"name": "Player One"}])
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
    assert report["signature_heroes"] == ["Puck"]
    assert report["hero_pool_depth"] == 1
    assert report["draft_flexibility"] == 0.04
    assert report["patch_adaptation_score"] == 27
    assert report["key_players"] == ["Player One"]
    assert report["recent_win_rate"] == 0.5
