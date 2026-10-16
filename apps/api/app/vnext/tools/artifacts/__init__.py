"""Model-facing artifact retrieval capabilities."""

from .query import register_artifact_query_tool
from .retrieval import register_artifact_tools

__all__ = ["register_artifact_tools", "register_artifact_query_tool"]
