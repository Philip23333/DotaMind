from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.dtos import MatchDTO, MatchGameDTO, MatchParticipantDTO
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
        MatchSearchInput.model_validate({"match_type": "best_of"})
    with pytest.raises(ValueError):
        MatchSearchInput.model_validate({"winner_type": "Team"})
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
    assert "league_id" in schema
    assert "series_id" in schema
    assert "tournament_id" in schema
    assert "team_id" in schema
    assert "status" in schema
    assert "winner_id" in schema
    assert "opponent_id" not in schema
    assert "match_type" not in schema
    assert "winner_type" not in schema


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


def test_match_search_accepts_relationship_and_result_filters() -> None:
    query = MatchSearchInput(
        team_id=123,
        status="canceled",
        winner_id=456,
    )

    assert query.team_id == 123
    assert query.status == "canceled"
    assert query.winner_id == 456


def test_match_dtos_are_strict_and_have_frozen_fields() -> None:
    assert set(MatchParticipantDTO.model_fields) == {"team", "score"}
    assert set(MatchGameDTO.model_fields) == {
        "id",
        "position",
        "status",
        "begin_at",
        "end_at",
        "length",
        "winner_id",
        "complete",
        "forfeit",
    }
    assert set(MatchDTO.model_fields) == {
        "id",
        "name",
        "slug",
        "status",
        "match_type",
        "number_of_games",
        "begin_at",
        "end_at",
        "scheduled_at",
        "original_scheduled_at",
        "league_id",
        "series_id",
        "tournament_id",
        "participants",
        "winner_id",
        "winner",
        "games",
        "draw",
        "forfeit",
        "rescheduled",
    }

    match = MatchDTO(
        id=42,
        name="Grand Final",
        status="finished",
        draw=False,
        forfeit=False,
        rescheduled=False,
    )
    assert match.participants == []
    assert match.games == []
    assert match.winner is None
    assert match.league_id is None
    assert match.series_id is None
    assert match.tournament_id is None
    with pytest.raises(ValueError):
        MatchDTO(
            id=42,
            name="Grand Final",
            status="finished",
            draw=False,
            forfeit=False,
            rescheduled=False,
            opponents=[],
        )


def test_match_search_tool_returns_new_match_dto_shape() -> None:
    registry = ToolRegistry()

    async def search(query: MatchSearchInput) -> MatchSearchResult:
        return MatchSearchResult(
            items=[
                MatchDTO(
                    id=42,
                    name="Grand Final",
                    status="finished",
                    league_id=1,
                    series_id=2,
                    tournament_id=3,
                    draw=False,
                    forfeit=False,
                    rescheduled=False,
                )
            ],
            page=query.page,
            limit=query.limit,
        )

    register_match_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="match-dto-call",
                name="esports.match.search",
                arguments={"tournament_id": 3},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["items"] == [
        {
            "id": 42,
            "name": "Grand Final",
            "slug": None,
            "status": "finished",
            "match_type": None,
            "number_of_games": None,
            "begin_at": None,
            "end_at": None,
            "scheduled_at": None,
            "original_scheduled_at": None,
            "league_id": 1,
            "series_id": 2,
            "tournament_id": 3,
            "participants": [],
            "winner_id": None,
            "winner": None,
            "games": [],
            "draw": False,
            "forfeit": False,
            "rescheduled": False,
        }
    ]


def test_default_vnext_registry_contains_artifacts_and_esports_search_tools() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    assert {tool.name for tool in registry.list()} == {
        "artifact.grep",
        "artifact.read",
        "esports.league.search",
        "esports.series.search",
        "esports.tournament.search",
        "esports.series.teams",
        "esports.match.search",
        "esports.team.search",
        "esports.player.search",
    }
