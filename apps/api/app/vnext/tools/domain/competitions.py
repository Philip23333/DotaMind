"""Thin agent-visible competition tool definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import CompetitionRef, DomainModel
from app.vnext.domain.competitions.models import CompetitionSearchResult
from app.vnext.domain.competitions.service import CompetitionService
from app.vnext.domain.matches.models import CompetitionMatchesResult, MatchStatus
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class CompetitionSearchInput(DomainModel):
    query: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1900, le=2200)
    limit: int = Field(default=10, ge=1, le=50)


class CompetitionListMatchesInput(DomainModel):
    competition_ref: CompetitionRef = Field(
        description=(
            "Competition reference object returned by competitions.search. Pass the whole "
            "object unchanged. Correct: {\"competition_ref\":{\"value\":"
            "\"competition:0123456789abcdef01234567\"}}. Incorrect: "
            "{\"competition_ref\":\"competition:...\"}."
        )
    )
    time_scope: Literal["upcoming", "recent", "running", "all"] = "all"
    status: MatchStatus | None = None
    limit: int = Field(default=10, ge=1, le=50)


def register_competition_tools(
    registry: ToolRegistry,
    service: CompetitionService,
) -> None:
    async def search(args: CompetitionSearchInput) -> CompetitionSearchResult:
        return await service.search(args.query, year=args.year, limit=args.limit)

    async def list_matches(args: CompetitionListMatchesInput) -> CompetitionMatchesResult:
        return await service.list_matches(
            args.competition_ref,
            time_scope=args.time_scope,
            status=args.status,
            limit=args.limit,
        )

    registry.register(
        ToolDefinition(
            name="competitions.search",
            description=(
                "Search professional Dota 2 competitions by name and optional year. "
                "Returns normalized candidates and preserves ambiguity."
            ),
            input_model=CompetitionSearchInput,
            output_model=CompetitionSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="competitions.list_matches",
            description=(
                "List bounded matches for a CompetitionRef returned by competitions.search. "
                "Use the returned reference object directly."
            ),
            input_model=CompetitionListMatchesInput,
            output_model=CompetitionMatchesResult,
            handler=list_matches,
            parallel_safe=True,
        )
    )


__all__ = [
    "CompetitionListMatchesInput",
    "CompetitionSearchInput",
    "register_competition_tools",
]
