"""Independent, Pydantic-validated agent-visible tool capabilities."""

from app.vnext.tools.definition import ToolDefinition, ToolHandler
from app.vnext.tools.registry import ToolRegistry

__all__ = ["ToolDefinition", "ToolHandler", "ToolRegistry"]
