from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.dtos import (
    TournamentDTO,
    TournamentParticipantDTO,
    TournamentRosterPlayerDTO,
)
from app.vnext.capabilities.esports.tournament import (
    TournamentSearchInput,
    TournamentSearchResult,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_tournament_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {"filter": {"serie_id": 10828}},
        {"search": {"name": "Group Stage"}},
        {"range": {"begin_at": {"gte": "2026-08-01"}}},
        {"league_id": 4106},
        {"slug": "group-stage"},
        {"serie_id": 10828},
        {"prizepool": "1000000"},
        {"tier": "s"},
    ],
)
def test_tournament_search_input_rejects_provider_and_shortcut_fields(arguments) -> None:
    with pytest.raises(ValueError):
        TournamentSearchInput.model_validate(arguments)


def test_tournament_search_input_accepts_closed_semantic_fields() -> None:
    query = TournamentSearchInput(
        id=21545,
        series_id=10828,
        name="Group Stage",
        page=2,
        limit=50,
    )
    assert query.series_id == 10828


def test_tournament_search_schema_is_semantic_and_closed() -> None:
    registry = ToolRegistry()

    async def search(_query: TournamentSearchInput) -> TournamentSearchResult:
        return TournamentSearchResult(items=[], page=1, limit=20)

    register_tournament_tool(registry, search)
    schema = registry.schemas()[0]
    rendered = json.dumps(schema.model_dump(mode="json"), ensure_ascii=False)

    assert {"id", "series_id", "name", "page", "limit"}.issubset(
        schema.input_schema["properties"]
    )
    for forbidden in (
        "filter[",
        "search[",
        "range[",
        "slug",
        "serie_id",
        "PandaScore",
    ):
        assert forbidden not in rendered


def test_tournament_dtos_are_strict_and_have_frozen_fields() -> None:
    assert set(TournamentRosterPlayerDTO.model_fields) == {
        "id",
        "name",
        "first_name",
        "last_name",
        "nationality",
        "slug",
    }
    assert set(TournamentParticipantDTO.model_fields) == {"team", "expected_roster"}
    assert set(TournamentDTO.model_fields) == {
        "id",
        "series_id",
        "league_id",
        "name",
        "type",
        "country",
        "region",
        "begin_at",
        "end_at",
        "winner_id",
        "tier",
        "prizepool",
        "has_bracket",
        "slug",
        "participants",
    }

    tournament = TournamentDTO(
        id=21545,
        series_id=10828,
        league_id=4106,
        name="Group Stage",
    )
    assert tournament.participants == []
    assert TournamentParticipantDTO(
        team={"id": 128329, "name": "Xtreme Gaming"}
    ).expected_roster == []
    with pytest.raises(ValueError):
        TournamentDTO(
            id=21545,
            series_id=10828,
            league_id=4106,
            name="Group Stage",
            matches=[],
        )
    with pytest.raises(ValueError):
        TournamentRosterPlayerDTO(id=1, name="Player", active=True)


def test_tournament_search_returns_stage_identity() -> None:
    registry = ToolRegistry()

    async def search(query: TournamentSearchInput) -> TournamentSearchResult:
        return TournamentSearchResult(
            items=[
                TournamentDTO(
                    id=21545,
                    series_id=10828,
                    league_id=4106,
                    name="Group Stage",
                )
            ],
            page=query.page,
            limit=query.limit,
        )

    register_tournament_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="tournament-call",
                name="esports.tournament.search",
                arguments={"series_id": 10828, "name": "Group Stage"},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "items": [
            {
                "id": 21545,
                "series_id": 10828,
                "league_id": 4106,
                "name": "Group Stage",
                "type": None,
                "country": None,
                "region": None,
                "begin_at": None,
                "end_at": None,
                "winner_id": None,
                "tier": None,
                "prizepool": None,
                "has_bracket": None,
                "slug": None,
                "participants": [],
            }
        ],
        "page": 1,
        "limit": 20,
    }
