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
        description=(
            "Entity level to query. league = competition brand/family; serie = a specific "
            "edition or season of that league; tournament = a stage, group, or bracket within "
            "a serie; match = one match series between opponents; team/player = participant "
            "entities. Example: for 'TI 2026 Group Stage', league is 'The International', "
            "serie is the 2026 edition, tournament is 'Group Stage', and match is an individual "
            "group-stage match such as 'Round 1: VSN vs TR'. This illustrates entity levels, "
            "not a fixed query workflow. Fields are resource-specific; do not assume a field "
            "works for another resource or invent fields."
        )
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
        description="Native sort must be an array of strings. 'field' is ascending and '-field' "
        "is descending; example: ['-begin_at']. Do not pass '-begin_at' as a string or use "
        "'begin_at desc'; fields must be supported by the resource.",
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
    returned_rows: int = Field(
        ge=0,
        description="Row count in this call's complete logical response, whether rows remain "
        "inline or are externalized. Combine with has_more to reason about later provider pages.",
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
            "fields or assume fields transfer between resources. Choose resource by entity level: "
            "league -> serie -> tournament -> match. filter, search, range, and sort "
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
