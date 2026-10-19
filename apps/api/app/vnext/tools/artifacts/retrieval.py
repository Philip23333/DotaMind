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
from app.vnext.tools.definition import ToolAccess, ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class ArtifactReadInput(DomainModel):
    ref: str = Field(
        description=("Exact opaque reference returned by a tool, or a documented manual ref.")
    )
    mode: Literal["outline", "read"] = Field(
        description="outline inspects root structure; read resolves one explicit dotted path."
    )
    path: str | None = Field(
        default=None,
        description=(
            "Dotted path to a complete value or object, such as rows.3.results. "
            "Read a parent collection only when complete records are needed; use "
            "artifact.query to extract selected fields across records."
        ),
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Start index when the selected path is a list. For example, path='rows', "
            "offset=0, limit=6 requests up to six complete adjacent rows. "
            "Continue from the returned next_offset rather than offset plus limit."
        ),
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=(
            "Maximum logical items from the selected list; the actual number returned may be "
            "lower because of the configured model observation-size budget. Use a bounded "
            "parent-list read for complete adjacent records; use artifact.query when only "
            "selected fields across records are needed."
        ),
    )
    task_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Optional task-plan item key that owns this observation for checkpoint "
            "source selection. When omitted, the current task item is used. A completed "
            "item may be read again; reading does not reopen it. This key does not "
            "identify the Artifact's owner."
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
        strict=True,
        description="Maximum matches on this page; byte limits may return fewer complete matches.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        strict=True,
        description=(
            "Offset in matching nodes, not visited nodes or array indexes. Continue with "
            "next_offset from the previous page using the same ref and pattern."
        ),
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
            offset=args.offset,
        )

    registry.register(
        ToolDefinition(
            name="artifact.grep",
            description=(
                "Search case-insensitive literal text in exactly one opaque tool response ref or "
                "documented static manual ref. Recursively searches both JSON member names "
                "and scalar values, including null. Member names match at their own nodes, "
                "not complete path strings; an ancestor match does not repeat all descendants. "
                "Returns original read paths, value_type and previews; containers show type "
                "and direct item count only. Results are count- and byte-bounded: follow "
                "next_offset with the same ref/pattern, since returned may be below limit. "
                "Use grep to locate unknown fields/content, read for a complete value or object "
                "at a known path, and query to filter records or extract selected fields "
                "across records, even without a filter."
            ),
            input_model=ArtifactGrepInput,
            output_model=ArtifactGrepResult,
            handler=grep,
            parallel_safe=True,
            externalize_result=False,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )
    registry.register(
        ToolDefinition(
            name="artifact.read",
            description=(
                "Inspect document structure or read a complete value or object at a known path "
                "in one exact manual or temporary tool-response artifact. Use artifact.grep "
                "to locate unknown fields/content. Use artifact.query to filter records or "
                "extract selected fields across records, even without a filter; avoid reading "
                "complete records when only a few fields are needed. Use mode='outline' "
                "to inspect root structure; do not provide path, offset, or limit in outline mode. "
                "Use mode='read' with one required dotted path to read a value. If a tool response "
                "contains _artifact_path, copy it exactly into path with mode='read'. "
                "When _artifact_path is already provided, use mode='read' directly. "
                "Outline is only needed when the document structure is unknown. "
                "Choose the narrowest useful read granularity. If you need one nested value from "
                "one row, read that exact path, such as rows.3.results. If you need complete "
                "adjacent records, read their parent collection with offset/limit. If you need "
                "only selected fields across records, use artifact.query. The stored "
                "artifact contains the complete logical tool response, so a parent row/list read "
                "can expose data replaced by _artifact_path pointers in the bounded preview. "
                "Offset and limit bound a list logically, but artifact reads also have a "
                "configured "
                "model observation-size budget, so fewer complete items than limit may be "
                "returned. "
                "List results include returned (the actual item count) and next_offset. "
                "Continue with the same ref/path and offset=next_offset until it is null; "
                "do not advance by the requested limit. Both fields are null for non-list reads "
                "and outline mode. If one "
                "selected value or item is too large, read a narrower nested path."
            ),
            input_model=ArtifactReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            parallel_safe=True,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )


__all__ = [
    "ArtifactGrepInput",
    "ArtifactReadInput",
    "register_artifact_tools",
]
