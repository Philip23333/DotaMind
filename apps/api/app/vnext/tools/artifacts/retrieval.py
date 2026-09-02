"""Thin agent-visible artifact retrieval tool definitions."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactGrepResult,
    ArtifactReader,
    ArtifactReadResult,
    ArtifactScopeRef,
)
from app.vnext.artifacts.models import ArtifactRef
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class ArtifactReadInput(DomainModel):
    ref: ArtifactRef | str = Field(
        description=(
            "Exact ArtifactRef object returned by a capability or artifact.grep. "
            "Pass the whole object unchanged. The only supported string references are "
            "documented static manuals such as manual:pandascore:index."
        )
    )
    path: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class ArtifactGrepInput(DomainModel):
    pattern: str = Field(
        min_length=1,
        max_length=ArtifactGrepper.MAX_PATTERN_LENGTH,
        description="Case-insensitive literal text to find in canonical artifact scalar values.",
    )
    artifact_types: list[str] | None = Field(
        default=None,
        description="Optional generic artifact-type restriction; omit to search the whole corpus.",
    )
    scope: ArtifactScopeRef | None = Field(
        default=None,
        description="Optional opaque corpus scope. It only constrains stored artifact search.",
    )
    ref: str | None = Field(
        default=None,
        description=(
            "Optional documented static manual reference. When set, search only that "
            "read-only document."
        ),
    )
    limit: int = Field(
        default=ArtifactGrepper.DEFAULT_LIMIT,
        ge=1,
        le=ArtifactGrepper.MAX_LIMIT,
    )

    @field_validator("pattern")
    @classmethod
    def _reject_blank_pattern(cls, value: str) -> str:
        if value.isspace():
            raise ValueError("pattern must not be blank")
        return value


def register_artifact_tools(
    registry: ToolRegistry,
    reader: ArtifactReader,
    grepper: ArtifactGrepper,
) -> None:
    async def read(args: ArtifactReadInput) -> ArtifactReadResult:
        fields_set = args.model_fields_set
        return await reader.read(
            args.ref,
            path=args.path,
            offset=args.offset,
            limit=args.limit,
            pagination_requested=bool({"offset", "limit"} & fields_set),
        )

    async def grep(args: ArtifactGrepInput) -> ArtifactGrepResult:
        return await grepper.grep(
            args.pattern,
            args.artifact_types,
            args.limit,
            args.scope,
            args.ref,
        )

    registry.register(
        ToolDefinition(
            name="artifact.grep",
            description=(
                "Find case-insensitive literal text in stored artifact content. "
                "A documented static manual ref can be searched directly. "
                "Returns bounded artifact-reference and structural-path observations "
                "without fetching or producing artifacts."
            ),
            input_model=ArtifactGrepInput,
            output_model=ArtifactGrepResult,
            handler=grep,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="artifact.read",
            description=(
                "Read a bounded serialized view of an exact ArtifactRef returned by another "
                "capability, or a documented static manual ref. Source documents keep complete "
                "provider-shaped facts under the facts field. Supports structural dotted paths "
                "and bounded list slices only."
            ),
            input_model=ArtifactReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            parallel_safe=True,
        )
    )


__all__ = [
    "ArtifactGrepInput",
    "ArtifactReadInput",
    "register_artifact_tools",
]
