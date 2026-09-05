"""Model-facing tournament search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.tournament import (
    TournamentSearchInput,
    TournamentSearchResult,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

TournamentSearchHandler = Callable[
    [TournamentSearchInput], Awaitable[TournamentSearchResult]
]

TOURNAMENT_SEARCH_DESCRIPTION = """\
Search Dota 2 tournaments.

A tournament is a competition stage within one series, such as Group Stage,
Playoffs, Swiss Stage, or Main Event.

Use series_id whenever the parent series is known.

Use name to find a stage within that series.

Prefer resolving the league and series first instead of searching tournament
names globally.

Use id when the exact tournament ID is already known.
"""


def register_tournament_tool(
    registry: ToolRegistry,
    search: TournamentSearchHandler,
) -> None:
    async def handler(args: TournamentSearchInput) -> TournamentSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.tournament.search",
            description=TOURNAMENT_SEARCH_DESCRIPTION,
            input_model=TournamentSearchInput,
            output_model=TournamentSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "tournament"},
        )
    )


__all__ = [
    "TOURNAMENT_SEARCH_DESCRIPTION",
    "TournamentSearchHandler",
    "register_tournament_tool",
]
