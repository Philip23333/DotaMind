"""Model-facing series search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.series import SeriesSearchInput, SeriesSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

SeriesSearchHandler = Callable[[SeriesSearchInput], Awaitable[SeriesSearchResult]]

SERIES_SEARCH_DESCRIPTION = """\
Search Dota 2 series.

A Series usually represents one season or edition of a recurring competition.
Source Series names can also contain a qualifier, region, or Play-In stage, so do
not infer a strict competition level from the name alone.

Use league_id when a known League provides useful context. Use year and season
to narrow an edition lookup, but do not assume either value identifies a unique
Series.

Use begin_at or end_at with {start, end} timestamps to filter series starting
or ending within a time window. Both endpoints must include a timezone (Z or
an offset). When both filters are supplied, both must match; this selects series
whose start and end each fall in their specified ranges, not all series active
during a window. Date filters combine with the other criteria and pagination.

Use name for fuzzy discovery and id when the exact Series ID is known. If a
known Series has a Tournament stage that needs to be found, use
esports.tournament.search with series_id. Do not re-query a parent object when
the available context is already sufficient.

Use esports.series.teams with series_id to find teams participating in a known
Series.
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
