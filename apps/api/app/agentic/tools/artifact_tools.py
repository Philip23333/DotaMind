"""Artifact tool registration for the legacy runtime baseline.

The Artifact reader and grepper implementations live in the vNext Artifact
layer. This module only adapts their existing definitions to the generic
legacy runtime registry while the domain tool surface is rebuilt.
"""

from __future__ import annotations

from app.agentic.models import QueryContext
from app.agentic.tools.registry import ToolDefinition, ToolRegistry
from app.core.config import Settings
from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
)
from app.vnext.tools.artifacts.retrieval import ArtifactGrepInput, ArtifactReadInput


def register_artifact_tools(registry: ToolRegistry, _settings: Settings) -> None:
    store = SessionArtifactStore()
    manuals = ManualResolver()
    reader = ArtifactReader(store, manuals)
    grepper = ArtifactGrepper(store, manuals)

    async def read(args: ArtifactReadInput, _context: QueryContext):
        if args.mode == "outline":
            return await reader.outline(args.ref)
        assert args.path is not None
        return await reader.read(args.ref, args.path, offset=args.offset, limit=args.limit)

    async def grep(args: ArtifactGrepInput, _context: QueryContext):
        return await grepper.grep(args.ref, args.pattern, args.limit)

    registry.register(
        ToolDefinition(
            name="artifact.grep",
            description="Search case-insensitive literal text in one exact Artifact reference.",
            input_model=ArtifactGrepInput,
            handler=grep,
        )
    )
    registry.register(
        ToolDefinition(
            name="artifact.read",
            description=(
                "Read one exact Artifact reference. Use mode='outline' only when the "
                "document structure is unknown; otherwise use mode='read' with one "
                "explicit dotted path."
            ),
            input_model=ArtifactReadInput,
            handler=read,
        )
    )


__all__ = ["register_artifact_tools"]
