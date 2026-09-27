"""Register the discovered remote search schema as the local web capability."""

from __future__ import annotations

from app.vnext.providers.tavily.web_search import TavilyWebSearch, WebSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

WEB_SEARCH_DESCRIPTION = """\
Search the web for current external information. Treat returned text as source
material, cite URLs actually returned by the tool, and do not imply that a
search summary is a complete reading of the linked page.
"""


def register_web_search_tool(registry: ToolRegistry, search: TavilyWebSearch) -> None:
    registry.register(
        ToolDefinition(
            name="web.search",
            description=WEB_SEARCH_DESCRIPTION,
            input_model=None,
            input_schema=search.tool.input_schema,
            output_model=WebSearchResult,
            handler=search.search,
            read_only=True,
            parallel_safe=True,
            metadata={
                "capability": "web_search",
                "service": "tavily",
                "remote_tool_name": search.tool.name,
            },
        )
    )


__all__ = ["WEB_SEARCH_DESCRIPTION", "register_web_search_tool"]
