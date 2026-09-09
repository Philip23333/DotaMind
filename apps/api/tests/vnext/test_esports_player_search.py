from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.dtos import PlayerDTO, PlayerRole, TeamRefDTO
from app.vnext.capabilities.esports.player import PlayerSearchInput, PlayerSearchResult
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_player_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {"filter": {"id": 1669}},
        {"search": {"name": "Ame"}},
        {"range": {"modified_at": "today"}},
        {"sort": "name"},
        {"slug": "ame"},
        {"modified_at": "2026-09-01"},
        {"videogame_id": 4},
        {"birthday": "2000-01-01"},
        {"age": 25},
        {"role": "carry"},
        {"nationality": "CN"},
    ],
)
def test_player_search_input_rejects_provider_fields(arguments) -> None:
    with pytest.raises(ValueError):
        PlayerSearchInput.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"id": 1669},
        {"team_id": 1647, "active": True},
        {"name": "Ame"},
        {"first_name": "Wang", "last_name": "Chunyu"},
        {
            "id": 1669,
            "team_id": 1647,
            "name": "Ame",
            "first_name": "Wang",
            "last_name": "Chunyu",
            "active": True,
            "page": 2,
            "limit": 50,
        },
    ],
)
def test_player_search_input_accepts_only_semantic_fields(arguments) -> None:
    PlayerSearchInput.model_validate(arguments)


def test_player_search_schema_is_semantic_and_closed() -> None:
    registry = ToolRegistry()

    async def search(_query: PlayerSearchInput) -> PlayerSearchResult:
        return PlayerSearchResult(items=[], page=1, limit=20)

    register_player_tool(registry, search)
    schema = registry.schemas()[0]
    rendered = json.dumps(schema.input_schema, ensure_ascii=False)

    assert {
        "id",
        "team_id",
        "name",
        "first_name",
        "last_name",
        "active",
        "page",
        "limit",
    }.issubset(schema.input_schema["properties"])
    for forbidden in (
        "slug",
        "modified_at",
        "videogame_id",
        "birthday",
        "age",
        "role",
        "nationality",
    ):
        assert forbidden not in schema.input_schema["properties"]
    for forbidden in ("filter[", "search[", "range["):
        assert forbidden not in rendered


def test_player_dto_has_frozen_fields_and_nullable_metadata() -> None:
    assert set(PlayerDTO.model_fields) == {
        "id",
        "name",
        "active",
        "role",
        "first_name",
        "last_name",
        "nationality",
        "slug",
        "image_url",
        "current_team",
    }
    item = PlayerDTO(id=1669, name="Ame", active=True)
    assert item.role is None
    assert item.current_team is None
    for extra_field in ("modified_at", "birthday"):
        with pytest.raises(ValueError):
            PlayerDTO(
                id=1669,
                name="Ame",
                active=True,
                **{extra_field: "today"},
            )

    mixed = PlayerDTO(
        id=1669,
        name="Ame",
        active=True,
        role=(PlayerRole.carry, PlayerRole.mid),
    )
    assert mixed.model_dump(mode="json")["role"] == ["carry", "mid"]


def test_player_search_returns_identity_and_current_team() -> None:
    seen: list[PlayerSearchInput] = []
    registry = ToolRegistry()

    async def search(query: PlayerSearchInput) -> PlayerSearchResult:
        seen.append(query)
        return PlayerSearchResult(
            items=[
                PlayerDTO(
                    id=1669,
                    name="Ame",
                    active=True,
                    role=(PlayerRole.mid,),
                    current_team=TeamRefDTO(
                        id=1647,
                        name="Team Liquid",
                        acronym="TL",
                    ),
                )
            ],
            page=query.page,
            limit=query.limit,
        )

    register_player_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="player-call",
                name="esports.player.search",
                arguments={"name": "Ame"},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["items"][0] == {
        "id": 1669,
        "name": "Ame",
        "active": True,
        "role": ["mid"],
        "first_name": None,
        "last_name": None,
        "nationality": None,
        "slug": None,
        "image_url": None,
        "current_team": {
            "id": 1647,
            "name": "Team Liquid",
            "acronym": "TL",
            "location": None,
            "slug": None,
            "image_url": None,
        },
    }
    assert result.content["anomalies"] == []
    assert seen[0].name == "Ame"
