"""Model-facing series search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.series import SeriesSearchInput, SeriesSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

SeriesSearchHandler = Callable[[SeriesSearchInput], Awaitable[SeriesSearchResult]]

SERIES_SEARCH_DESCRIPTION = """\
Search Dota 2 series.

A series is one specific season or edition of a recurring league.

Use league_id when the parent league is already known.

Use year when the user refers to a specific yearly edition, such as
The International 2026.

Use season for season-style editions such as DreamLeague Season 28.

Use name only for a series-specific name. Do not use this tool to search for
tournament stages such as Group Stage or Playoffs.

Use id when the exact series ID is already known.
"""


def register_series_tool(registry: ToolRegistry, search: SeriesSearchHandler) -> None:
    async def handler(args: SeriesSearchInput) -> SeriesSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.series.search",
            description=SERIES_SEARCH_DESCRIPTION,
            input_model=SeriesSearchInput,
            output_model=SeriesSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "series"},
        )
    )


__all__ = [
    "SERIES_SEARCH_DESCRIPTION",
    "SeriesSearchHandler",
    "register_series_tool",
]
