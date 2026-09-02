"""Model-facing PandaScore-backed esports discovery capability."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

from .esports_observation import EsportsSearchObservationBuilder


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
    truncated: bool = False
    artifact_ref: str | None = None
    total_rows: int | None = None


def build_esports_search_tool(
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> ToolDefinition:
    async def search(args: EsportsSearchInput) -> EsportsSearchOutput:
        result = await executor.execute(args.model_dump(exclude_none=True))
        observation = await observation_builder.build(result)
        return EsportsSearchOutput(
            resource=observation.resource,
            scope=observation.scope,
            rows=observation.rows,
            has_more=observation.has_more,
            truncated=observation.truncated,
            artifact_ref=observation.artifact_ref,
            total_rows=observation.total_rows,
        )

    return ToolDefinition(
        name="esports.search",
        description=(
            "Search Dota 2 esports data using native query capabilities. Choose a resource and "
            "optionally use its supported filter, search, range, sort, lifecycle scope, and "
            "pagination fields. Different resources support different fields; unsupported fields "
            "or scopes return structured alternatives so the query can be corrected. When unsure "
            "about supported fields, read manual:pandascore:index with artifact.read. "
            "Large results may be returned as bounded previews with an artifact_ref; "
            "use artifact.read or artifact.grep to inspect omitted data."
        ),
        input_model=EsportsSearchInput,
        output_model=EsportsSearchOutput,
        handler=search,
    )


def register_esports_tools(
    registry: ToolRegistry,
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> None:
    registry.register(build_esports_search_tool(executor, observation_builder))


__all__ = [
    "EsportsSearchInput",
    "EsportsSearchOutput",
    "build_esports_search_tool",
    "register_esports_tools",
]
