"""Model-facing match search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

MatchSearchHandler = Callable[[MatchSearchInput], Awaitable[MatchSearchResult]]

MATCH_SEARCH_DESCRIPTION = """\
Find Dota 2 Match records, including schedules, participants, scores, status,
and the basic Game records supplied with a Match. A Match can contain multiple
Games; this search does not provide complete in-game data.

games[].pandascore_game_id identifies a PandaScore Game record, not a Valve
single-game ID. Never pass it to game.detail as valve_game_id. For in-game
details, use esports.game.resolve with the Match-search artifact_ref, selected
Match path, and games[].position as game_position; then pass its resolved
valve_game_id to game.detail. If resolution is unavailable or unresolved, this
search result does not establish a Valve ID.

Keep the user's known team, competition, and date constraints together whenever
the available fields can express them. Prefer the most specific known
competition constraint (tournament_id, then series_id, then league_id), and use
known entity IDs to narrow the search. Use team_id for matches involving a known
team and winner_id for matches won by a known team. Use lifecycle to distinguish
past, running, and upcoming matches. begin_at filters by a UTC calendar date.

The past collection can include canceled and other non-finished matches. To find
completed matches, combine lifecycle="past" with status="finished". There is no
native two-team intersection filter, so inspect the returned participants when a
specific matchup is needed.

Use sort="begin_at_desc" to find recent candidates. Do not infer that the last
match by time is the final; check the returned name, stage, and participants
against the event context. Use id when the exact Match ID is already known.

Every successful search returns an artifact_ref, including empty and small
results. If esports.game.resolve is available and one Match needs a Valve Game
identity, continue with that artifact_ref, the selected Match path (for example,
items.0), and the source Game's position as game_position. You can continue directly when
the current observation is enough to select the Match; artifact.read is not
required first. The Match path is relative to the stored search document, so do
not prefix it with value.
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
            always_artifact=True,
            metadata={"game": "dota2", "domain": "match"},
        )
    )


__all__ = ["MATCH_SEARCH_DESCRIPTION", "MatchSearchHandler", "register_match_tool"]
