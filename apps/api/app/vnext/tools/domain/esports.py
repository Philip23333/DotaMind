"""Model-facing esports discovery capability."""

from app.vnext.capabilities.esports import (
    EsportsSearchRequest,
    EsportsSearchResult,
    EsportsSearchService,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

EsportsSearchInput = EsportsSearchRequest


def register_esports_tools(registry: ToolRegistry, service: EsportsSearchService) -> None:
    async def search(args: EsportsSearchInput) -> EsportsSearchResult:
        return await service.search(args)

    registry.register(
        ToolDefinition(
            name="esports.search",
            description=(
                "Search professional Dota 2 esports entities by kind. Returned records "
                "contain bounded source facts and an ArtifactRef to the complete validated "
                "source document."
            ),
            input_model=EsportsSearchInput,
            output_model=EsportsSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )


__all__ = ["EsportsSearchInput", "register_esports_tools"]
