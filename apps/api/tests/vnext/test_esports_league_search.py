from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.league import (
    LeagueItem,
    LeagueSearchInput,
    LeagueSearchResult,
)
from app.vnext.composition import VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_league_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {"filter": {"id": 4106}},
        {"search": {"name": "The International"}},
        {"slug": "the-international"},
        {"year": 2026},
        {"series_id": 10828},
        {"sort": "modified_at_desc"},
    ],
)
def test_league_search_input_rejects_provider_and_edition_fields(arguments) -> None:
    with pytest.raises(ValueError):
        LeagueSearchInput.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [{}, {"name": "The International"}, {"id": 4106}, {"page": 2, "limit": 50}],
)
def test_league_search_input_accepts_only_semantic_fields(arguments) -> None:
    LeagueSearchInput.model_validate(arguments)


def test_league_search_schema_is_semantic_and_closed() -> None:
    registry = ToolRegistry()

    async def search(_query: LeagueSearchInput) -> LeagueSearchResult:
        return LeagueSearchResult(items=[], page=1, limit=20)

    register_league_tool(registry, search)
    schema = registry.schemas()[0]
    rendered = json.dumps(schema.model_dump(mode="json"), ensure_ascii=False)

    assert {"id", "name", "page", "limit"}.issubset(
        schema.input_schema["properties"]
    )
    for forbidden in (
        "filter[",
        "search[",
        "slug",
        "modified_at",
        "serie_id",
        "PandaScore",
    ):
        assert forbidden not in rendered


def test_league_search_returns_resolved_league_identity() -> None:
    seen: list[LeagueSearchInput] = []
    registry = ToolRegistry()

    async def search(query: LeagueSearchInput) -> LeagueSearchResult:
        seen.append(query)
        return LeagueSearchResult(
            items=[LeagueItem(id=4106, name="The International")],
            page=query.page,
            limit=query.limit,
        )

    register_league_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="league-call",
                name="esports.league.search",
                arguments={"name": "The International"},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "items": [{"id": 4106, "name": "The International"}],
        "page": 1,
        "limit": 20,
    }
    assert seen[0].name == "The International"


def test_default_vnext_registry_includes_league_and_match_search() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    assert {tool.name for tool in registry.list()} == {
        "artifact.grep",
        "artifact.read",
        "esports.league.search",
        "esports.series.search",
        "esports.tournament.search",
        "esports.match.search",
        "esports.team.search",
        "esports.player.search",
    }
