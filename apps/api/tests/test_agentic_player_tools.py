"""Tests for the player tools (stratz.player_profile /
player_recent_matches / player_hero_performance).

FakePlayers stands in for the integration layer (mirroring the FakeHeroes
pattern in test_agentic_stratz_tools.py) and records the last call kwargs so
the handler-level bracket translation (basic_to_bracket_ids ->
bracketIds 0-8; basic_to_rank_ids -> rankIds 0-80), the days window, and
match_take can be asserted. Evidence extractors are exercised via synthetic
ToolResult inputs.
"""
import asyncio

from app.agentic.models import QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.tools import ToolExecutor
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


class FakeTransport:
    def __init__(self, graphql_url: str, token: str) -> None:
        self.graphql_url = graphql_url
        self.token = token

    async def aclose(self) -> None:
        return None


def _registry(token: str | None):
    return build_default_tool_registry(
        Settings(
            stratz_graphql_url="https://stratz.test/graphql",
            stratz_token=token,
        )
    )


class FakePlayers:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.last_profile_id = None
        self.last_recent_kwargs: dict | None = None
        self.last_hero_kwargs: dict | None = None

    async def get_profile(self, steam_account_id: int) -> dict:
        self.last_profile_id = steam_account_id
        return {
            "steam_account_id": steam_account_id,
            "found": True,
            "name": "TestPlayer",
            "avatar": None,
            "season_rank": 80,
            "pro_name": None,
            "match_count": 1000,
            "win_count": 600,
            "imp": 5,
            "first_match_date": 1500000000,
            "last_match_date": 1800000000,
        }

    async def get_recent_matches(
        self,
        steam_account_id: int,
        *,
        bracket_ids=None,
        position_ids=None,
        start_date_time=None,
        take=20,
    ) -> list[dict]:
        self.last_recent_kwargs = dict(
            bracket_ids=bracket_ids,
            position_ids=position_ids,
            start_date_time=start_date_time,
            take=take,
        )
        # Newest-first (integration layer sorts); one win, one loss.
        return [
            {
                "match_id": 2, "start_time": 200, "win": False, "is_radiant": True,
                "hero_id": 7, "kills": 1, "deaths": 2, "assists": 3,
                "gold_per_minute": 400, "experience_per_minute": 500,
                "duration": 2000, "lobby_type": "RANKED", "game_mode": "ALL_PICK",
                "position": "POSITION_1", "lane": None, "role": None,
                "level": 18, "last_hits": 100, "denies": 10, "imp": 5,
            },
            {
                "match_id": 1, "start_time": 100, "win": True, "is_radiant": False,
                "hero_id": 8, "kills": 5, "deaths": 1, "assists": 4,
                "gold_per_minute": 600, "experience_per_minute": 700,
                "duration": 2100, "lobby_type": "RANKED", "game_mode": "ALL_PICK",
                "position": "POSITION_2", "lane": None, "role": None,
                "level": 20, "last_hits": 200, "denies": 20, "imp": 10,
            },
        ]

    async def get_hero_performance(
        self,
        steam_account_id: int,
        *,
        rank_ids=None,
        position_ids=None,
        start_date_time=None,
        end_date_time=None,
        match_take=None,
        hero_row_take=50,
    ) -> list[dict]:
        self.last_hero_kwargs = dict(
            rank_ids=rank_ids,
            position_ids=position_ids,
            start_date_time=start_date_time,
            end_date_time=end_date_time,
            match_take=match_take,
            hero_row_take=hero_row_take,
        )
        # Varied samples; handler derives win_rate, applies min_match_count +
        # selection. hero 3 (1 game) is below the default min_match_count=3.
        return [
            {"hero_id": 1, "win_count": 3, "match_count": 3, "kda": 5.0,
             "avg_kills": 5, "avg_deaths": 1, "avg_assists": 4, "duration": 2000,
             "imp": 10, "gold_per_minute": 600, "experience_per_minute": 700,
             "last_played_date_time": 1800},
            {"hero_id": 2, "win_count": 2, "match_count": 4, "kda": 3.0,
             "avg_kills": 4, "avg_deaths": 2, "avg_assists": 3, "duration": 2000,
             "imp": 5, "gold_per_minute": 500, "experience_per_minute": 600,
             "last_played_date_time": 1700},
            {"hero_id": 3, "win_count": 1, "match_count": 1, "kda": 4.0,
             "avg_kills": 3, "avg_deaths": 1, "avg_assists": 3, "duration": 2000,
             "imp": 7, "gold_per_minute": 550, "experience_per_minute": 650,
             "last_played_date_time": 1600},
            {"hero_id": 4, "win_count": 0, "match_count": 5, "kda": 1.0,
             "avg_kills": 2, "avg_deaths": 5, "avg_assists": 2, "duration": 2000,
             "imp": -5, "gold_per_minute": 400, "experience_per_minute": 500,
             "last_played_date_time": 1500},
            {"hero_id": 5, "win_count": 4, "match_count": 5, "kda": 4.5,
             "avg_kills": 6, "avg_deaths": 2, "avg_assists": 5, "duration": 2000,
             "imp": 8, "gold_per_minute": 580, "experience_per_minute": 680,
             "last_played_date_time": 1400},
        ]


def _patch_players(monkeypatch) -> FakePlayers:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    fake = FakePlayers(FakeTransport("https://stratz.test/graphql", "token"))
    monkeypatch.setattr(
        "app.agentic.tools.stratz_tools.StratzPlayers", lambda transport: fake
    )
    return fake


# --- handlers ---


def test_player_profile_handler_returns_profile(monkeypatch) -> None:
    _patch_players(monkeypatch)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="prof",
                tool="stratz.player_profile",
                args={"steam_account_id": 853634884},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    profile = result.data["profile"]
    assert profile["found"] is True
    assert profile["match_count"] == 1000
    assert profile["win_count"] == 600
    assert result.data["filters"]["steam_account_id"] == 853634884


def test_player_recent_matches_translates_bracket_and_summarizes(monkeypatch) -> None:
    fake = _patch_players(monkeypatch)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="recent",
                tool="stratz.player_recent_matches",
                args={"steam_account_id": 853634884, "take": 20, "days": 7},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    # bracket LEGEND_ANCIENT -> bracketIds [5, 6] (0-8 space)
    assert fake.last_recent_kwargs["bracket_ids"] == [5, 6]
    assert fake.last_recent_kwargs["start_date_time"] is not None  # days=7 applied
    summary = result.data["summary"]
    assert summary["match_count"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert result.data["filters"]["bracket_ids"] == [5, 6]
    assert result.data["filters"]["days"] == 7
    assert "within last 7 days" in result.data["filters"]["meaning"]
    # newest-first preserved
    assert [m["match_id"] for m in result.data["matches"]] == [2, 1]


def test_player_hero_performance_strong_sorts_and_caps(monkeypatch) -> None:
    fake = _patch_players(monkeypatch)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="heroperf",
                tool="stratz.player_hero_performance",
                args={
                    "steam_account_id": 853634884,
                    "take": 3,
                    "match_take": 20,
                    "min_match_count": 2,
                    "selection_mode": "strong",
                },
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    # match_take flows to request.take; over-fetch in strong mode = max(3*3,50)=50
    assert fake.last_hero_kwargs["match_take"] == 20
    assert fake.last_hero_kwargs["hero_row_take"] == 50
    heroes = result.data["heroes"]
    # hero 3 (1 game) dropped by min_match_count=2; rest ranked by win_rate desc
    assert [h["hero_id"] for h in heroes] == [1, 5, 2]
    assert heroes[0]["win_rate"] == 1.0  # 3/3
    assert heroes[1]["win_rate"] == 0.8  # 4/5
    assert heroes[2]["win_rate"] == 0.5  # 2/4
    assert result.data["filters"]["win_rate_basis"] == "player_hero: winCount/matchCount"
    assert result.data["returned_hero_match_sum"] == 3 + 5 + 4


def test_player_hero_performance_translates_bracket_to_rank_ids(monkeypatch) -> None:
    fake = _patch_players(monkeypatch)

    asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="heroperf",
                tool="stratz.player_hero_performance",
                args={"steam_account_id": 853634884, "take": 5},
            ),
            QueryContext(bracket=["DIVINE_IMMORTAL"]),
        )
    )

    # DIVINE_IMMORTAL -> rankIds [70..74, 80] (LIVE-LOCKED 0-80 space)
    assert fake.last_hero_kwargs["rank_ids"] == [70, 71, 72, 73, 74, 80]


def test_player_hero_performance_popular_ranks_by_games(monkeypatch) -> None:
    _patch_players(monkeypatch)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="heroperf",
                tool="stratz.player_hero_performance",
                args={
                    "steam_account_id": 853634884,
                    "take": 3,
                    "min_match_count": 2,
                    "selection_mode": "popular",
                },
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    # popular: rank by match_count desc; heroes 4&5 (5 games) before 2 (4) before 1 (3)
    assert [h["hero_id"] for h in result.data["heroes"]] == [4, 5, 2]


# --- evidence extractors (synthetic ToolResult) ---


def test_player_profile_evidence_threads_basis() -> None:
    from app.agentic.tools.stratz_tools import player_profile_evidence

    tool_result = ToolResult(
        tool_call_id="prof",
        tool="stratz.player_profile",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "steam_account_id": 853634884,
            "profile": {
                "found": True, "name": "TestPlayer", "avatar": None,
                "season_rank": 80, "pro_name": None,
                "match_count": 1000, "win_count": 600, "imp": 5,
                "last_match_date": 1800000000,
            },
            "filters": {"steam_account_id": 853634884},
        },
    )

    evidence = player_profile_evidence(tool_result)
    assert [e.kind for e in evidence] == ["player_identity"]
    item = evidence[0]
    assert item.value["global_win_rate"] == 0.6
    assert item.value["win_rate_basis"] == "player_global: winCount/matchCount"
    # provenance threaded into filters too
    assert item.value["filters"]["win_rate_basis"] == "player_global: winCount/matchCount"


def test_player_recent_matches_evidence_uses_native_isvictory() -> None:
    from app.agentic.tools.stratz_tools import player_recent_matches_evidence

    tool_result = ToolResult(
        tool_call_id="recent",
        tool="stratz.player_recent_matches",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "steam_account_id": 853634884,
            "matches": [
                {"match_id": 2, "hero_id": 7, "win": False, "kills": 1, "deaths": 2,
                 "assists": 3, "start_time": 200, "duration": 2000},
                {"match_id": 1, "hero_id": 8, "win": True, "kills": 5, "deaths": 1,
                 "assists": 4, "start_time": 100, "duration": 2100},
            ],
            "summary": {"match_count": 2, "wins": 1, "losses": 1, "latest_match_time": 200},
            "filters": {"steam_account_id": 853634884, "days": 7, "take": 20},
        },
    )

    evidence = player_recent_matches_evidence(tool_result)
    kinds = [e.kind for e in evidence]
    assert kinds.count("player_recent_match") == 2
    assert "player_recent_summary" in kinds
    assert "sample_size" in kinds
    # win relayed verbatim from native isVictory
    match_items = [e for e in evidence if e.kind == "player_recent_match"]
    assert {e.value["win"] for e in match_items} == {True, False}
    assert all(
        e.value["win_rate_basis"] == "stratz_native: MatchPlayerType.isVictory"
        for e in match_items
    )
    summary = next(e for e in evidence if e.kind == "player_recent_summary")
    assert summary.value["wins"] == 1
    assert summary.value["losses"] == 1
    assert summary.value["win_rate"] == 0.5


def test_player_hero_performance_evidence_relays_sample_knobs() -> None:
    from app.agentic.tools.stratz_tools import player_hero_performance_evidence

    tool_result = ToolResult(
        tool_call_id="heroperf",
        tool="stratz.player_hero_performance",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "steam_account_id": 853634884,
            "heroes": [
                {"hero_id": 1, "win_count": 3, "match_count": 3, "win_rate": 1.0,
                 "kda": 5.0, "gold_per_minute": 600, "experience_per_minute": 700,
                 "duration": 2000, "imp": 10, "last_played_date_time": 1800},
            ],
            "returned_hero_match_sum": 3,
            "filters": {
                "steam_account_id": 853634884, "match_take": 20, "days": None,
                "selection_mode": "strong",
                "win_rate_basis": "player_hero: winCount/matchCount",
            },
        },
    )

    evidence = player_hero_performance_evidence(tool_result)
    kinds = [e.kind for e in evidence]
    assert kinds.count("player_hero_performance") == 1
    assert "sample_size" in kinds
    item = evidence[0]
    assert item.value["win_rate"] == 1.0
    assert item.value["win_rate_basis"] == "player_hero: winCount/matchCount"
    assert item.value["filters"]["win_rate_basis"] == "player_hero: winCount/matchCount"
    sample = next(e for e in evidence if e.kind == "sample_size")
    # sample relays provider knobs verbatim; no invented aggregate beyond a sum
    assert sample.value["match_take"] == 20
    assert sample.value["returned_hero_count"] == 1
    assert sample.value["returned_hero_match_sum"] == 3
