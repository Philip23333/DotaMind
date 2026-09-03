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
    path: str | None = Field(
        default=None,
        description=(
            "Dotted path to read. Use an exact nested path for one value, such as "
            "rows.3.results, or a parent collection such as rows when several adjacent "
            "complete rows are needed."
        ),
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Start index when the selected path is a list. For example, path='rows', "
            "offset=0, limit=6 reads six complete adjacent rows in one call."
        ),
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=(
            "Maximum items from the selected list. Prefer one bounded parent-list read over "
            "many sibling reads when several adjacent rows are required."
        ),
    )

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
                "When _artifact_path is already provided, use mode='read' directly. "
                "Outline is only needed when the document structure is unknown. "
                "Choose the narrowest useful read granularity. If you need one nested value from "
                "one row, read that exact path, such as rows.3.results. If you need the same "
                "evidence across several adjacent rows, prefer reading the parent rows collection "
                "once with offset/limit instead of issuing many sibling reads such as "
                "rows.0.results, rows.0.opponents, rows.1.results, rows.1.opponents. The stored "
                "artifact contains the complete logical tool response, so a parent row/list read "
                "can expose data replaced by _artifact_path pointers in the bounded preview. "
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
