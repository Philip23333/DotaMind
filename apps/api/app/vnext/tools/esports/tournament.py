"""Model-facing tournament search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.tournament import (
    TournamentSearchInput,
    TournamentSearchResult,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

TournamentSearchHandler = Callable[[TournamentSearchInput], Awaitable[TournamentSearchResult]]
TOURNAMENT_SEARCH_DESCRIPTION = """\
Search Dota 2 tournaments.

A Tournament is a competition grouping or stage under a Series in the source
hierarchy. Common examples include Group Stage and Playoffs.

Use series_id to constrain the search when the Series is known. You do not need
to query League and Series in a fixed sequence when the available context is
already sufficient.

Use name to find a Tournament grouping or stage, and id when the exact
Tournament ID is known.

The final may not have its own Tournament record. Locate a Match using the
returned records and Match details instead of assuming a separate final stage
exists.
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
