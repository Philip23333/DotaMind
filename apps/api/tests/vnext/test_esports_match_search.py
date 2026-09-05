from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.composition import VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_match_tool
from app.vnext.tools.registry import ToolRegistry


def test_match_search_input_is_closed_and_bounded() -> None:
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"filter": {"id": 1}})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"search": {"name": "final"}})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"range": {"begin_at": "today"}})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"serie_id": 1})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"opponent_id": 1})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"page": 0})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"limit": 101})


def test_match_search_tool_schema_exposes_only_semantic_fields() -> None:
    registry = ToolRegistry()

    async def search(_query: MatchSearchInput) -> MatchSearchResult:
        return MatchSearchResult(items=[], page=1, limit=20)

    register_match_tool(registry, search)
    schema = json.dumps(registry.schemas()[0].model_dump(mode="json"), ensure_ascii=False)

    assert "esports.match.search" in schema
    assert "filter[" not in schema
    assert "search[" not in schema
    assert "range[" not in schema
    assert "serie_id" not in schema
    assert "opponent_id" not in schema
    assert "league_id" in schema
    assert "series_id" in schema
    assert "tournament_id" in schema


def test_match_search_tool_validates_and_returns_contract_output() -> None:
    seen: list[MatchSearchInput] = []
    registry = ToolRegistry()

    async def search(query: MatchSearchInput) -> MatchSearchResult:
        seen.append(query)
        return MatchSearchResult(items=[], page=query.page, limit=query.limit)

    register_match_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="call-1",
                name="esports.match.search",
                arguments={"tournament_id": 3, "lifecycle": "past", "limit": 5},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {"items": [], "page": 1, "limit": 5}
    assert seen[0].tournament_id == 3


def test_default_vnext_registry_contains_artifacts_and_esports_search_tools() -> None:
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
