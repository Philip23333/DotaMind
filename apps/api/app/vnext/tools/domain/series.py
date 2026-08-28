"""Thin agent-visible series tool definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, SeriesRef
from app.vnext.domain.matches.models import MatchStatus, SeriesMatchesResult
from app.vnext.domain.series.models import SeriesSearchResult
from app.vnext.domain.series.service import SeriesService
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class SeriesSearchInput(DomainModel):
    query: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1900, le=2200)
    limit: int = Field(default=10, ge=1, le=50)


class SeriesListMatchesInput(DomainModel):
    series_ref: SeriesRef = Field(
        description=(
            "Series reference object returned by series.search. Pass the whole "
            "object unchanged. Correct: {\"series_ref\":{\"value\":"
            "\"series:0123456789abcdef01234567\"}}. Incorrect: "
            "{\"series_ref\":\"series:...\"}."
        )
    )
    time_scope: Literal["upcoming", "recent", "running", "all"] = "all"
    status: MatchStatus | None = None
    limit: int = Field(default=10, ge=1, le=50)


def register_series_tools(
    registry: ToolRegistry,
    service: SeriesService,
) -> None:
    async def search(args: SeriesSearchInput) -> SeriesSearchResult:
        return await service.search(args.query, year=args.year, limit=args.limit)

    async def list_matches(args: SeriesListMatchesInput) -> SeriesMatchesResult:
        return await service.list_matches(
            args.series_ref,
            time_scope=args.time_scope,
            status=args.status,
            limit=args.limit,
        )

    registry.register(
        ToolDefinition(
            name="series.search",
            description=(
                "Search professional Dota 2 series by name and optional year. "
                "Returns normalized candidates and preserves ambiguity."
            ),
            input_model=SeriesSearchInput,
            output_model=SeriesSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="series.list_matches",
            description=(
                "List bounded matches for a SeriesRef returned by series.search. "
                "Use the returned reference object directly."
            ),
            input_model=SeriesListMatchesInput,
            output_model=SeriesMatchesResult,
            handler=list_matches,
            parallel_safe=True,
        )
    )


__all__ = [
    "SeriesListMatchesInput",
    "SeriesSearchInput",
    "register_series_tools",
]
