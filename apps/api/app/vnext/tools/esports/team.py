"""Model-facing team search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.team import TeamSearchInput, TeamSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

TeamSearchHandler = Callable[[TeamSearchInput], Awaitable[TeamSearchResult]]

TEAM_SEARCH_DESCRIPTION = """\
Search Dota 2 teams.

Use this tool to resolve a team name or acronym to a team ID.

Use name for names such as "Team Liquid". Use acronym for common competitive
abbreviations such as "LGD" or "OG". Once a team ID is known, use it with match
search to find that team's matches, or with player search to find players
currently associated with the team.

Use id when the exact team ID is already known.
"""


def register_team_tool(registry: ToolRegistry, search: TeamSearchHandler) -> None:
    async def handler(args: TeamSearchInput) -> TeamSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.team.search",
            description=TEAM_SEARCH_DESCRIPTION,
            input_model=TeamSearchInput,
            output_model=TeamSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "team"},
        )
    )


__all__ = ["TEAM_SEARCH_DESCRIPTION", "TeamSearchHandler", "register_team_tool"]
