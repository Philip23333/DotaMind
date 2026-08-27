"""Thin agent-visible team capability definitions."""

from __future__ import annotations

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, TeamRef
from app.vnext.domain.teams.models import TeamGetResult, TeamSearchResult
from app.vnext.domain.teams.service import TeamService
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class TeamSearchInput(DomainModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class TeamGetDetailInput(DomainModel):
    team_ref: TeamRef = Field(
        description=(
            "Complete TeamRef object returned by another tool. Pass it unchanged: "
            "{\"team_ref\":{\"value\":\"team:0123456789abcdef01234567\"}}. "
            "Do not pass a bare string or JSON-encode the object into a string."
        )
    )


def register_team_tools(registry: ToolRegistry, service: TeamService) -> None:
    async def search(args: TeamSearchInput) -> TeamSearchResult:
        return await service.search(args.query, limit=args.limit)

    async def get_detail(args: TeamGetDetailInput) -> TeamGetResult:
        return await service.get(args.team_ref)

    registry.register(
        ToolDefinition(
            name="teams.search",
            description=(
                "Search professional Dota 2 teams by name. Returns bounded normalized "
                "candidates and preserves ambiguity."
            ),
            input_model=TeamSearchInput,
            output_model=TeamSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="teams.get_detail",
            description=(
                "Return normalized source facts and the available players for one resolved "
                "TeamRef."
            ),
            input_model=TeamGetDetailInput,
            output_model=TeamGetResult,
            handler=get_detail,
            parallel_safe=True,
        )
    )


__all__ = ["TeamGetDetailInput", "TeamSearchInput", "register_team_tools"]
