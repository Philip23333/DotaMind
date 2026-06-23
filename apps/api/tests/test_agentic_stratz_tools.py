import asyncio

from app.agentic.models import ToolCall
from app.agentic.registry import ToolExecutor
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import Settings


def test_default_registry_registers_stratz_hero_matchup_tool() -> None:
    registry = build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )

    names = [definition.name for definition in registry.list()]

    assert names == ["resolve_hero", "stratz.hero_vs_hero_matchup"]


def test_resolve_hero_tool_executes_from_default_registry() -> None:
    registry = build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )

    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="debug-1", tool="resolve_hero", args={"query": "LC"})
        )
    )

    assert result.status == "ok"
    assert result.source
    assert result.source.kind == "local_constants"
    assert result.data["status"] == "resolved"
    assert result.data["hero"]["hero_id"] == 104


def test_stratz_hero_matchup_tool_executes_with_fake_client(monkeypatch) -> None:
    class FakeTransport:
        def __init__(self, graphql_url: str, token: str) -> None:
            self.graphql_url = graphql_url
            self.token = token

        async def aclose(self) -> None:
            return None

    class FakeHeroes:
        def __init__(self, transport: FakeTransport) -> None:
            self.transport = transport

        async def hero_vs_hero_matchup(
            self,
            hero_id: int,
            *,
            take: int,
            week: int | None,
            bracket_basic_ids: list[str] | None,
            match_limit: int | None,
        ) -> dict:
            return {
                "hero_id": hero_id,
                "take": take,
                "week": week,
                "bracket_basic_ids": bracket_basic_ids,
                "match_limit": match_limit,
                "transport_url": self.transport.graphql_url,
            }

    monkeypatch.setattr("app.agentic.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.stratz_tools.StratzHeroes", FakeHeroes)

    registry = build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )
    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(
                id="debug-1",
                tool="stratz.hero_vs_hero_matchup",
                args={"hero_id": 25, "take": 3},
            )
        )
    )

    assert result.status == "ok"
    assert result.source
    assert result.source.name == "STRATZ"
    assert result.data["hero_id"] == 25
    assert result.data["take"] == 3
    assert result.data["transport_url"] == "https://api.stratz.test/graphql"


def test_stratz_hero_matchup_tool_requires_token() -> None:
    registry = build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token=None)
    )
    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(
                id="debug-1",
                tool="stratz.hero_vs_hero_matchup",
                args={"hero_id": 25},
            )
        )
    )

    assert result.status == "error"
    assert result.error
    assert "METAMIND_STRATZ_TOKEN is required" in result.error
