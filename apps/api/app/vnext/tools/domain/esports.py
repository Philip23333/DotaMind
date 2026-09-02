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
    resource: Literal["league", "serie", "tournament", "match", "team", "player"] = Field(
        description="Resource to query. Fields are resource-specific; do not assume a field works "
        "for another resource or invent fields."
    )
    scope: Literal["all", "past", "running", "upcoming"] = Field(
        default="all",
        description="Selects the provider lifecycle endpoint. It is not a relative-time or "
        "'most recent' selector; use supported sort fields for ordering.",
    )
    filter: dict[str, Any] | None = Field(
        default=None,
        description="Exact native filtering, commonly for IDs, relationships, and exact values. "
        "Only fields supported by this resource are allowed; filter is not interchangeable with "
        "provider text search.",
    )
    search: dict[str, Any] | None = Field(
        default=None,
        description="Provider text-search fields. It is not a replacement for exact native filter "
        "fields and only supports fields available for this resource.",
    )
    range: dict[str, list[Any]] | None = Field(
        default=None,
        description="Native range constraints. Each range field must be explicitly supported by "
        "the selected resource.",
    )
    sort: list[str] | None = Field(
        default=None,
        description="Native sort fields: 'field' is ascending and '-field' is descending. Use "
        "'-begin_at', not 'begin_at desc'; fields must be supported by the resource.",
    )
    page: int = Field(default=1, ge=1, description="One-based provider result-page number.")
    page_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Provider-side rows returned for this call. Keep it small when only a few "
        "results are needed.",
    )


class EsportsSearchOutput(DomainModel):
    resource: str = Field(description="The queried resource.")
    scope: str = Field(description="The lifecycle endpoint scope used for this call.")
    rows: list[dict[str, Any]] = Field(
        description="Complete rows for a small response, or a bounded preview for a large one. "
        "A preview _artifact_path can be copied directly to artifact.read with mode='read'."
    )
    has_more: bool | None = Field(
        default=None,
        description="Whether the provider reports a later page after this call's page.",
    )
    truncated: bool = Field(
        default=False,
        description="True only when model-facing rows are a bounded preview; it does not mean the "
        "provider omitted rows from this call.",
    )
    artifact_ref: str | None = Field(
        default=None,
        description="Opaque ref to this call's complete logical response when truncated is true. "
        "Use artifact.read or artifact.grep with this exact ref.",
    )
    returned_rows: int | None = Field(
        default=None,
        description="Row count in this call's complete logical response when a large response was "
        "externalized. Combine with has_more to reason about later provider pages.",
    )


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
            returned_rows=observation.returned_rows,
        )

    return ToolDefinition(
        name="esports.search",
        description=(
            "Search Dota 2 esports data through one resource-specific native query. Do not invent "
            "fields or assume fields transfer between resources. filter, search, range, and sort "
            "have distinct provider semantics and are not interchangeable. Prefer supported "
            "source-side filter, sort, and a small page_size to narrow a request. "
            "scope selects a lifecycle endpoint, not recency. A large result returns a bounded "
            "preview, not missing provider data. Its complete response is available through "
            "artifact_ref, and any _artifact_path can be read directly with artifact.read "
            "mode='read'."
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
