import asyncio
import time

from app.agentic.models import QueryContext, ToolCall
from app.agentic.tools import ToolExecutor, ToolRegistry
from app.agentic.tools.opendota_tools import register_opendota_tools
from app.core.config import Settings


class FakeTransport:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    def cache_stats(self) -> dict[str, int]:
        return {"hits": 0, "misses": 0}


class FakeHeroes:
    async def get_stats_for_role(self, role: str, *, min_pub_pick: int) -> list[dict]:
        return [{"hero": "Mars", "role": role, "pub_pick": min_pub_pick}]


class FakeTeams:
    detail_sample_size = 50
    max_detail_sample_size = 100

    async def get_all(self) -> list[dict]:
        return [
            {"team_id": 1, "name": "BetBoom Team", "tag": "BB", "rating": 1200},
            {"team_id": 2, "name": "BoomBoys", "tag": "BB", "rating": 1000},
        ]

    async def get_matches(self, _team_id: int) -> list[dict]:
        now = int(time.time())
        return [
            {
                "match_id": 11,
                "start_time": now,
                "radiant": True,
                "radiant_win": True,
            },
            {
                "match_id": 12,
                "start_time": now - 90 * 86400,
                "radiant": True,
                "radiant_win": False,
            },
        ]

    async def get_players(self, _team_id: int) -> list[dict]:
        return [
            {"name": "Current", "is_current_team_member": True},
            {"name": "Former", "is_current_team_member": False},
        ]

    async def aggregate_heroes(self, matches: list[dict]) -> list[dict]:
        return [{"hero_id": 1, "localized_name": "Anti-Mage", "games_played": len(matches)}]


def test_opendota_resolve_team_reports_resolution(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", _fake_clients)
    result = asyncio.run(
        _execute("opendota.resolve_team", {"query": "BetBoom Team"})
    )

    assert result.status == "ok"
    assert result.data["status"] == "resolved"
    assert result.data["team"]["team_id"] == 1


def test_opendota_team_recent_matches_returns_window_summary(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", _fake_clients)
    result = asyncio.run(
        _execute("opendota.team_recent_matches", {"team_id": 1, "days": 30})
    )

    assert result.status == "ok"
    assert result.data["matches_in_window"] == 1
    assert result.data["wins"] == 1
    assert result.data["recent_record"] == "1-0 in last 1 matches"
    assert result.data["latest_match_at"]


def test_opendota_team_players_supports_current_only(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", _fake_clients)
    result = asyncio.run(
        _execute("opendota.team_players", {"team_id": 1, "current_only": True})
    )

    assert result.status == "ok"
    assert result.data["player_count"] == 1
    assert result.data["players"][0]["name"] == "Current"


def test_opendota_team_heroes_returns_detail_sample_count(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", _fake_clients)
    result = asyncio.run(
        _execute(
            "opendota.team_heroes",
            {
                "matches": [{"match_id": 1}, {"match_id": 2}, {"match_id": 3}],
                "detail_sample_size": 2,
            },
        )
    )

    assert result.status == "ok"
    assert result.data["match_details_analyzed"] == 2
    assert result.data["heroes"][0]["games_played"] == 2


def test_opendota_hero_stats_by_role_returns_records(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", _fake_clients)
    result = asyncio.run(
        _execute("opendota.hero_stats_by_role", {"role": "offlane", "min_pub_pick": 50})
    )

    assert result.status == "ok"
    assert result.data["role"] == "offlane"
    assert result.data["hero_count"] == 1


def test_opendota_tool_error_is_exposed_without_mock(monkeypatch) -> None:
    class BrokenTeams(FakeTeams):
        async def get_matches(self, _team_id: int) -> list[dict]:
            raise RuntimeError("opendota down")

    def broken_clients(_settings):
        return FakeTransport(), FakeHeroes(), BrokenTeams()

    monkeypatch.setattr("app.agentic.tools.opendota_tools._clients", broken_clients)
    result = asyncio.run(
        _execute("opendota.team_recent_matches", {"team_id": 1, "days": 30})
    )

    assert result.status == "error"
    assert result.error
    assert "opendota down" in result.error
    assert result.source is None


async def _execute(tool: str, args: dict) -> object:
    registry = ToolRegistry()
    register_opendota_tools(registry, Settings(opendota_base_url="https://opendota.test"))
    return await ToolExecutor(registry).execute(
        ToolCall(id="t1", tool=tool, args=args),
        QueryContext(),
    )


def _fake_clients(_settings):
    return FakeTransport(), FakeHeroes(), FakeTeams()
