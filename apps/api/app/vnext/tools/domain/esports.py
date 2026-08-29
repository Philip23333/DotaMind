"""Thin model-facing esports discovery capability."""

from typing import Literal

from pydantic import Field

from app.vnext.capabilities.esports import EsportsSearchResult, EsportsSearchService
from app.vnext.domain.common.models import DomainModel
from app.vnext.domain.source import SourceLocator
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class EsportsSearchInput(DomainModel):
    query: str | None = None
    within: SourceLocator | None = None
    teams: list[str] = Field(default_factory=list, max_length=2)
    time_scope: Literal["upcoming", "recent", "running", "all"] = "all"
    limit: int = Field(default=10, ge=1, le=50)


def register_esports_tools(registry: ToolRegistry, service: EsportsSearchService) -> None:
    async def search(args: EsportsSearchInput) -> EsportsSearchResult:
        return await service.search(
            query=args.query,
            within=args.within,
            teams=args.teams,
            time_scope=args.time_scope,
            limit=args.limit,
        )

    registry.register(
        ToolDefinition(
            name="esports.search",
            description=(
                "Search professional Dota 2 esports source facts. Use within with a returned "
                "league, series, or match locator to continue source-local navigation. Each "
                "record contains bounded structural facts and, when externalized, an ArtifactRef "
                "for the complete validated source document."
            ),
            input_model=EsportsSearchInput,
            output_model=EsportsSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )


__all__ = ["EsportsSearchInput", "register_esports_tools"]
