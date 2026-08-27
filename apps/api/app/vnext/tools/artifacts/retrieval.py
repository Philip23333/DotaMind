"""Thin agent-visible artifact retrieval tool definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.vnext.artifacts import (
    ArtifactReader,
    ArtifactReadResult,
    ArtifactSearcher,
    ArtifactSearchResult,
)
from app.vnext.artifacts.models import ArtifactRef
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class ArtifactSearchInput(DomainModel):
    artifact_type: Literal["game_summary"]
    valve_match_ids: list[int] = Field(max_length=100)


class ArtifactReadInput(DomainModel):
    ref: ArtifactRef = Field(
        description=(
            "Exact ArtifactRef object returned by artifact.search. Pass the whole object "
            "unchanged; do not pass its id as a bare string or JSON-encode the object."
        )
    )
    path: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


def register_artifact_tools(
    registry: ToolRegistry,
    searcher: ArtifactSearcher,
    reader: ArtifactReader,
) -> None:
    def search(args: ArtifactSearchInput) -> ArtifactSearchResult:
        return searcher.search(args.artifact_type, args.valve_match_ids)

    def read(args: ArtifactReadInput) -> ArtifactReadResult:
        fields_set = args.model_fields_set
        return reader.read(
            args.ref,
            path=args.path,
            offset=args.offset,
            limit=args.limit,
            pagination_requested=bool({"offset", "limit"} & fields_set),
        )

    registry.register(
        ToolDefinition(
            name="artifact.search",
            description=(
                "Find stored GameSummary artifacts by canonical Valve match ID. "
                "Returns references and missing IDs in input order; does not produce "
                "or read artifacts."
            ),
            input_model=ArtifactSearchInput,
            output_model=ArtifactSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="artifact.read",
            description=(
                "Read a bounded serialized view of an exact canonical artifact reference. "
                "Use the returned ArtifactRef object directly. Supports structural dotted paths "
                "and bounded list slices only."
            ),
            input_model=ArtifactReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            parallel_safe=True,
        )
    )


__all__ = ["ArtifactReadInput", "ArtifactSearchInput", "register_artifact_tools"]
