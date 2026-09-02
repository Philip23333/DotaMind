"""Model-facing PandaScore-backed esports discovery capability."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class EsportsSearchInput(DomainModel):
    resource: Literal["league", "serie", "tournament", "match", "team", "player"]
    scope: Literal["all", "past", "running", "upcoming"] = "all"
    filter: dict[str, Any] | None = None
    search: dict[str, Any] | None = None
    range: dict[str, list[Any]] | None = None
    sort: list[str] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class EsportsSearchOutput(DomainModel):
    resource: str
    scope: str
    rows: list[dict[str, Any]]
    has_more: bool | None = None


def build_esports_search_tool(executor: PandaScoreNativeQueryExecutor) -> ToolDefinition:
    async def search(args: EsportsSearchInput) -> EsportsSearchOutput:
        result = await executor.execute(args.model_dump(exclude_none=True))
        return EsportsSearchOutput(
            resource=result.resource,
            scope=result.scope,
            rows=result.rows,
            has_more=result.has_more,
        )

    return ToolDefinition(
        name="esports.search",
        description=(
            "Search Dota 2 esports data using native query capabilities. Choose a resource and "
            "optionally use its supported filter, search, range, sort, lifecycle scope, and "
            "pagination fields. Different resources support different fields; unsupported fields "
            "or scopes return structured alternatives so the query can be corrected. When unsure "
            "about supported fields, read manual:pandascore:index with artifact.read."
        ),
        input_model=EsportsSearchInput,
        output_model=EsportsSearchOutput,
        handler=search,
    )


def register_esports_tools(
    registry: ToolRegistry, executor: PandaScoreNativeQueryExecutor
) -> None:
    registry.register(build_esports_search_tool(executor))


__all__ = [
    "EsportsSearchInput",
    "EsportsSearchOutput",
    "build_esports_search_tool",
    "register_esports_tools",
]
