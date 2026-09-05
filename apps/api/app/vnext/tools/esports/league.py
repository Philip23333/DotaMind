"""Model-facing league search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.league import (
    LeagueSearchInput,
    LeagueSearchResult,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

LeagueSearchHandler = Callable[[LeagueSearchInput], Awaitable[LeagueSearchResult]]

LEAGUE_SEARCH_DESCRIPTION = """\
Search Dota 2 leagues.

A league is the top-level identity of a recurring competition, such as
The International or DreamLeague.

Use this tool to resolve a competition name to a league ID.

A league can contain multiple series representing different seasons or
editions. If the user refers to a specific year, season, or edition, first
resolve the league here and use the returned league ID with the series
capability when it is available.

Use id when the exact league ID is already known.
"""


def register_league_tool(registry: ToolRegistry, search: LeagueSearchHandler) -> None:
    async def handler(args: LeagueSearchInput) -> LeagueSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.league.search",
            description=LEAGUE_SEARCH_DESCRIPTION,
            input_model=LeagueSearchInput,
            output_model=LeagueSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "league"},
        )
    )


__all__ = [
    "LEAGUE_SEARCH_DESCRIPTION",
    "LeagueSearchHandler",
    "register_league_tool",
]
