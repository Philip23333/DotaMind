"""Thin agent-visible artifact retrieval tool definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

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
    mode: Literal["outline", "read"] = Field(
        description="outline inspects root structure; read resolves one explicit dotted path."
    )
    path: str | None = None
    offset: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_mode_arguments(self) -> ArtifactReadInput:
        if self.mode == "outline":
            if self.path is not None or self.offset is not None or self.limit is not None:
                raise ValueError("outline mode does not accept path, offset, or limit")
            return self
        if self.path is None:
            raise ValueError("read mode requires path")
        return self


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
        if args.mode == "outline":
            return await reader.outline(args.ref)
        assert args.path is not None
        return await reader.read(args.ref, args.path, offset=args.offset, limit=args.limit)

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
                "Read one exact manual or temporary tool-response artifact. Use mode='outline' "
                "to inspect root structure; do not provide path, offset, or limit in outline mode. "
                "Use mode='read' with one required dotted path to read a value. If a tool response "
                "contains _artifact_path, copy it exactly into path with mode='read'. "
                "Offset and limit only slice the selected list value; they do not control "
                "overall artifact response size."
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
