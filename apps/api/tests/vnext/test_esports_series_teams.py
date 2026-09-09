from __future__ import annotations

import asyncio

import pytest

from app.vnext.capabilities.esports.dtos import TeamRefDTO
from app.vnext.capabilities.esports.series import (
    SeriesTeamsInput,
    SeriesTeamsResult,
)
from app.vnext.composition import VNextServices, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_series_teams_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"series_id": 0},
        {"series_id": -1},
        {"series_id": 10828, "page": 0},
        {"series_id": 10828, "limit": 101},
        {"series_id": 10828, "team_id": 128329},
    ],
)
def test_series_teams_input_is_required_and_closed(arguments) -> None:
    with pytest.raises(ValueError):
        SeriesTeamsInput.model_validate(arguments)


def test_series_teams_schema_and_description_are_bounded() -> None:
    registry = ToolRegistry()

    async def teams(_query: SeriesTeamsInput) -> SeriesTeamsResult:
        return SeriesTeamsResult(items=[], page=1, limit=20)

    register_series_teams_tool(registry, teams)
    definition = registry.get("esports.series.teams")
    schema = definition.schema()

    assert set(schema.input_schema["properties"]) == {"series_id", "page", "limit"}
    assert schema.input_schema["required"] == ["series_id"]
    assert definition.metadata == {"game": "dota2", "domain": "series"}
    assert definition.read_only is True
    assert definition.parallel_safe is True
    assert definition.externalize_result is True
    assert "participating" in definition.description
    assert "team list" in definition.description


def test_series_teams_tool_returns_participant_team_contract() -> None:
    registry = ToolRegistry()

    async def teams(query: SeriesTeamsInput) -> SeriesTeamsResult:
        assert query.series_id == 10828
        assert query.page == 2
        assert query.limit == 3
        return SeriesTeamsResult(
            items=[
                TeamRefDTO(
                    id=128329,
                    name="Xtreme Gaming",
                    acronym="XG",
                    location="cn",
                )
            ],
            page=query.page,
            limit=query.limit,
        )

    register_series_teams_tool(registry, teams)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="series-teams-call",
                name="esports.series.teams",
                arguments={"series_id": 10828, "page": 2, "limit": 3},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "items": [
            {
                "id": 128329,
                "name": "Xtreme Gaming",
                "acronym": "XG",
                "location": "cn",
                "slug": None,
                "image_url": None,
            }
        ],
        "page": 2,
        "limit": 3,
        "anomalies": [],
    }


def test_series_teams_inherits_generic_externalization() -> None:
    teams = [
        TeamRefDTO(
            id=index,
            name=f"Team {index} {'x' * 200}",
        )
        for index in range(100)
    ]

    async def search_teams(query: SeriesTeamsInput) -> SeriesTeamsResult:
        return SeriesTeamsResult(items=teams, page=query.page, limit=query.limit)

    registry = build_vnext_registry(VNextServices(series_teams=search_teams))
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="large-series-teams",
                name="esports.series.teams",
                arguments={"series_id": 10828},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["value"]["items"] == {
        "_artifact_path": "items",
        "kind": "collection",
        "count": 100,
    }
    ref = result.content["artifact_ref"]
    read = asyncio.run(
        registry.execute(
            ToolCall(
                id="read-series-teams",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "items",
                    "offset": 0,
                    "limit": 3,
                },
            )
        )
    )

    assert read.status == "ok"
    assert read.content["total"] == 100
    assert read.content["value"] == [team.model_dump(mode="json") for team in teams[:3]]


def test_team_ref_dto_is_strict_with_optional_metadata() -> None:
    assert set(TeamRefDTO.model_fields) == {
        "id",
        "name",
        "acronym",
        "location",
        "slug",
        "image_url",
    }
    assert TeamRefDTO(id=128329, name="Xtreme Gaming").model_dump() == {
        "id": 128329,
        "name": "Xtreme Gaming",
        "acronym": None,
        "location": None,
        "slug": None,
        "image_url": None,
    }
    with pytest.raises(ValueError):
        TeamRefDTO(id=128329, name="Xtreme Gaming", players=[])
