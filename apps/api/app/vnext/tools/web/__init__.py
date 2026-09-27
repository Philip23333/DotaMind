"""Model-facing web search capability tools."""

from .search import WEB_SEARCH_DESCRIPTION, register_web_search_tool

__all__ = ["WEB_SEARCH_DESCRIPTION", "register_web_search_tool"]
