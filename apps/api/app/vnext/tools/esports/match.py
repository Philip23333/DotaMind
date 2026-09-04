"""Model-facing match search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

MatchSearchHandler = Callable[[MatchSearchInput], Awaitable[MatchSearchResult]]

MATCH_SEARCH_DESCRIPTION = """\
Search Dota 2 matches.

Use this tool to find match schedules, opponents, results, scores, winners, and
match status. Matches belong to tournaments, series, and leagues and involve
teams. Use known entity IDs to narrow the search whenever possible.

Prefer the most specific known competition context:
tournament_id > series_id > league_id.

Use team_id to find matches involving a known team. Use lifecycle to distinguish
past, currently running, and upcoming matches.

When looking for the latest or final match in a known event, prefer the known
event ID with lifecycle="past" and sort="begin_at_desc" rather than relying only
on match-name search. Use id when the exact match ID is already known.
"""


def register_match_tool(registry: ToolRegistry, search: MatchSearchHandler) -> None:
    async def handler(args: MatchSearchInput) -> MatchSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.match.search",
            description=MATCH_SEARCH_DESCRIPTION,
            input_model=MatchSearchInput,
            output_model=MatchSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "match"},
        )
    )


__all__ = ["MATCH_SEARCH_DESCRIPTION", "MatchSearchHandler", "register_match_tool"]
