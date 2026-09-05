from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.capabilities.esports.series import (
    SeriesItem,
    SeriesSearchInput,
    SeriesSearchResult,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_series_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {"filter": {"league_id": 4106}},
        {"search": {"name": "The International"}},
        {"range": {"year": {"gte": 2026}}},
        {"slug": "the-international-2026"},
        {"modified_at": "2026-09-01"},
        {"winner_id": 1},
        {"tournament_id": 21545},
        {"serie_id": 10828},
    ],
)
def test_series_search_input_rejects_provider_and_tournament_fields(arguments) -> None:
    with pytest.raises(ValueError):
        SeriesSearchInput.model_validate(arguments)


def test_series_search_input_accepts_closed_semantic_fields() -> None:
    query = SeriesSearchInput(
        id=10828,
        league_id=4106,
        name="The International",
        season="2026",
        year=2026,
        page=2,
        limit=50,
    )
    assert query.page == 2
    assert query.limit == 50


def test_series_search_schema_is_semantic_and_closed() -> None:
    registry = ToolRegistry()

    async def search(_query: SeriesSearchInput) -> SeriesSearchResult:
        return SeriesSearchResult(items=[], page=1, limit=20)

    register_series_tool(registry, search)
    schema = registry.schemas()[0]
    rendered = json.dumps(schema.model_dump(mode="json"), ensure_ascii=False)

    assert {
        "id",
        "league_id",
        "name",
        "season",
        "year",
        "page",
        "limit",
    }.issubset(schema.input_schema["properties"])
    for forbidden in (
        "filter[",
        "search[",
        "range[",
        "slug",
        "modified_at",
        "winner_id",
        "tournament_id",
        "serie_id",
        "PandaScore",
    ):
        assert forbidden not in rendered


def test_series_search_returns_edition_identity() -> None:
    registry = ToolRegistry()

    async def search(query: SeriesSearchInput) -> SeriesSearchResult:
        return SeriesSearchResult(
            items=[
                SeriesItem(
                    id=10828,
                    name="",
                    full_name="2026",
                    season="2026",
                    year=2026,
                )
            ],
            page=query.page,
            limit=query.limit,
        )

    register_series_tool(registry, search)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="series-call",
                name="esports.series.search",
                arguments={"league_id": 4106, "year": 2026},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["items"][0]["id"] == 10828
    assert result.content["items"][0]["full_name"] == "2026"
