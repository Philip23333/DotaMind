"""Model-facing tournament search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.tournament import (
    TournamentRostersInput,
    TournamentRostersResult,
    TournamentSearchInput,
    TournamentSearchResult,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

TournamentSearchHandler = Callable[
    [TournamentSearchInput], Awaitable[TournamentSearchResult]
]
TournamentRostersHandler = Callable[
    [TournamentRostersInput], Awaitable[TournamentRostersResult]
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

TOURNAMENT_ROSTERS_DESCRIPTION = """\
Get tournament-time rosters for teams participating in one known Dota 2 tournament stage.

Use tournament_id from esports.tournament.search. Use team_id when the user asks
for one specific team's roster.

This returns the roster associated with that tournament, not the team's current contracted players.
Do not use esports.player.search(team_id=...) to reconstruct historical tournament rosters.

This capability does not prove the exact five players who actually played every
individual match.
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


def register_tournament_rosters_tool(
    registry: ToolRegistry,
    rosters: TournamentRostersHandler,
) -> None:
    async def handler(args: TournamentRostersInput) -> TournamentRostersResult:
        return await rosters(args)

    registry.register(
        ToolDefinition(
            name="esports.tournament.rosters",
            description=TOURNAMENT_ROSTERS_DESCRIPTION,
            input_model=TournamentRostersInput,
            output_model=TournamentRostersResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "tournament"},
        )
    )


__all__ = [
    "TOURNAMENT_SEARCH_DESCRIPTION",
    "TOURNAMENT_ROSTERS_DESCRIPTION",
    "TournamentRostersHandler",
    "TournamentSearchHandler",
    "register_tournament_rosters_tool",
    "register_tournament_tool",
]
