"""Thin agent-visible artifact retrieval tool definitions."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactGrepResult,
    ArtifactReader,
    ArtifactReadResult,
)
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class ArtifactReadInput(DomainModel):
    ref: str = Field(
        description=(
            "Exact opaque reference returned by a tool, or a documented manual ref such as "
            "manual:pandascore:index."
        )
    )
    path: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class ArtifactGrepInput(DomainModel):
    ref: str = Field(
        description="Exact opaque tool response or documented manual reference to search."
    )
    pattern: str = Field(
        min_length=1,
        max_length=ArtifactGrepper.MAX_PATTERN_LENGTH,
        description="Case-insensitive literal text to find in the referenced document.",
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
            args.ref,
            args.pattern,
            args.limit,
        )

    registry.register(
        ToolDefinition(
            name="artifact.grep",
            description=(
                "Search case-insensitive literal text in exactly one opaque tool response ref or "
                "documented static manual ref."
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
                "Read a bounded serialized view of exactly one opaque tool response ref or "
                "documented static manual ref. Supports structural dotted paths and bounded list "
                "slices only."
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
