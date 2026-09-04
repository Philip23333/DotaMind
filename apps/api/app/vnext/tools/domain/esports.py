"""Temporary generic PandaScore-backed esports discovery fallback."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

from .esports_observation import EsportsSearchObservationBuilder
from .esports_resources import register_esports_resource_tools


class EsportsSearchInput(DomainModel):
    resource: Literal["serie", "tournament", "team", "player"] = Field(
        description=(
            "Temporary generic fallback for esports resources not yet split into typed tools. "
            "Use esports.league.search for league and esports.match.search for match."
        )
    )
    scope: Literal["all", "past", "running", "upcoming"] = Field(
        default="all",
        description=(
            "Selects the provider lifecycle endpoint. 'past' means the provider's past lifecycle "
            "collection; it does not imply a resource-specific finished state. 'running' and "
            "'upcoming' likewise select lifecycle collections. It is not a relative-time or "
            "'most recent' selector."
        ),
    )
    filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Exact native filtering for this temporary fallback. Fields remain resource-specific; "
            "use the corresponding manual before a nontrivial fallback query."
        ),
    )
    search: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Provider text-search fields for the selected fallback resource. It is not a "
            "replacement for exact native filter fields."
        ),
    )
    range: dict[str, list[Any]] | None = Field(
        default=None,
        description="Native range constraints for the selected fallback resource.",
    )
    sort: list[str] | None = Field(
        default=None,
        description=(
            "Native sort must be an array of strings. 'field' is ascending and '-field' is "
            "descending; fields must be supported by the selected fallback resource."
        ),
    )
    page: int = Field(default=1, ge=1, description="One-based provider result-page number.")
    page_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Provider-side rows returned for this call. Keep it small when possible.",
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
        description=(
            "True means this model-facing response is only a bounded preview of the complete "
            "logical tool result. When true, inline rows are not necessarily all returned rows; "
            "returned_rows refers to the complete logical result for this call; do not infer "
            "totals, exhaustive lists, 'all matches', or 'there were N' from the preview alone. "
            "Use artifact_ref and any provided _artifact_path to inspect the complete result "
            "before exhaustive claims. False means the logical result is represented completely "
            "inline."
        ),
    )
    artifact_ref: str | None = Field(
        default=None,
        description="Opaque ref to this call's complete logical response when truncated is true. "
        "Use artifact.read or artifact.grep with this exact ref.",
    )
    returned_rows: int = Field(
        ge=0,
        description="Number of rows in the complete logical result returned by this query, "
        "including rows omitted from a truncated model-facing preview.",
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
            "Temporary generic fallback for serie, tournament, team, and player discovery while "
            "the resource-shaped esports tool surface is introduced. Do not use it for league or "
            "match; use esports.league.search or esports.match.search instead. Fallback fields "
            "remain resource-specific and are validated against generated PandaScore capabilities."
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
    register_esports_resource_tools(registry, executor, observation_builder)
    registry.register(build_esports_search_tool(executor, observation_builder))


__all__ = [
    "EsportsSearchInput",
    "EsportsSearchOutput",
    "build_esports_search_tool",
    "register_esports_tools",
]
