import asyncio

from app.agentic.models import ToolCall
from app.agentic.tools import ToolExecutor
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


class FakeTransport:
    def __init__(self, graphql_url: str, token: str) -> None:
        self.graphql_url = graphql_url
        self.token = token

    async def aclose(self) -> None:
        return None


class FakeHeroes:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport

    async def lane_outcome(self, *args, **kwargs) -> list[dict]:
        return [
            {
                "hero_id": 86,
                "target_hero_id": args[0],
                "position": "POSITION_4",
                "match_count": 25,
                "match_win_rate": 0.6,
            }
        ]


def test_stratz_lane_outcome_tool_returns_records(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="lane",
                tool="stratz.lane_outcome",
                args={
                    "hero_id": 104,
                    "is_with": True,
                    "position_ids": ["POSITION_4"],
                },
            )
        )
    )

    assert result.status == "ok"
    assert result.data["hero_id"] == 104
    assert result.data["records"][0]["hero_id"] == 86


def test_stratz_lane_outcome_requires_token() -> None:
    result = asyncio.run(
        ToolExecutor(_registry(token=None)).execute(
            ToolCall(
                id="lane",
                tool="stratz.lane_outcome",
                args={"hero_id": 104, "is_with": True},
            )
        )
    )

    assert result.status == "error"
    assert result.error
    assert "METAMIND_STRATZ_TOKEN is required" in result.error


def _registry(token: str | None):
    return build_default_tool_registry(
        Settings(
            stratz_graphql_url="https://stratz.test/graphql",
            stratz_token=token,
        )
    )
