"""Default LLM-facing tool registry.

The clean-slate vNext surface starts from generic Artifact tools. Domain tools
are registered explicitly as they are rebuilt behind stable capability contracts.
"""

from __future__ import annotations

from app.agentic.tools.artifact_tools import register_artifact_tools
from app.agentic.tools.registry import ToolRegistry
from app.core.config import Settings


def build_default_tool_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    register_artifact_tools(registry, settings)
    return registry


__all__ = ["build_default_tool_registry"]
