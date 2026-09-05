from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.team import TeamItem, TeamSearchInput, TeamSearchResult
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_team_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {"filter": {"id": 1647}},
        {"search": {"name": "Team Liquid"}},
        {"range": {"modified_at": "today"}},
        {"sort": "name"},
        {"slug": "team-liquid"},
        {"modified_at": "2026-09-01"},
        {"videogame_id": 4},
        {"players": []},
        {"player_id": 1669},
    ],
)
def test_team_search_input_rejects_provider_fields(arguments) -> None:
    with pytest.raises(ValueError):
        TeamSearchInput.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"id": 1647},
        {"name": "Team Liquid"},
        {"acronym": "TL"},
        {"id": 1647, "name": "Team Liquid", "acronym": "TL", "page": 2, "limit": 50},
    ],
)
def test_team_search_input_accepts_only_semantic_fields(arguments) -> None:
    TeamSearchInput.model_validate(arguments)


def test_team_search_schema_is_semantic_and_closed() -> None:
    registry = ToolRegistry()

    async def search(_query: TeamSearchInput) -> TeamSearchResult:
        return TeamSearchResult(items=[], page=1, limit=20)

    register_team_tool(registry, search)
    schema = registry.schemas()[0]
    rendered = json.dumps(schema.input_schema, ensure_ascii=False)

    assert {"id", "name", "acronym", "page", "limit"}.issubset(
        schema.input_schema["properties"]
    )
    for forbidden in ("slug", "modified_at", "videogame_id", "players"):
        assert forbidden not in schema.input_schema["properties"]
    for forbidden in ("filter[", "search[", "range["):
        assert forbidden not in rendered


def test_team_search_returns_team_identity() -> None:
    seen: list[TeamSearchInput] = []
    registry = ToolRegistry()

    async def search(query: TeamSearchInput) -> TeamSearchResult:
        seen.append(query)
        return TeamSearchResult(
            items=[TeamItem(id=1647, name="Team Liquid", acronym="TL", location="NL")],
            page=query.page,
            limit=query.limit,
        )

    register_team_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="team-call",
                name="esports.team.search",
                arguments={"name": "Team Liquid", "acronym": "TL"},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "items": [
            {"id": 1647, "name": "Team Liquid", "acronym": "TL", "location": "NL"}
        ],
        "page": 1,
        "limit": 20,
    }
    assert seen[0].name == "Team Liquid"
    assert seen[0].acronym == "TL"
