"""Model-facing single-game resolution tool using a Match Artifact continuation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.game_resolution import (
    EsportsGameResolutionResult,
    EsportsGameResolveInput,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameResolutionHandler = Callable[
    [EsportsGameResolveInput], Awaitable[EsportsGameResolutionResult]
]

GAME_RESOLUTION_DESCRIPTION = """\
Resolve the Valve identity of one Game within a Match returned by
esports.match.search. Use the Match-search Artifact from the current session.
match_path selects a Match in the stored search document (for example,
items.0 selects the first Match); game_position selects that Match's source Game
position (for example, 4 selects position 4). These values are independent. The
path is relative to the stored document even when the inline observation nests
the results under value, so pass items.0 without a value. prefix.

Only status="resolved" confirms the returned valve_game_id as this Game's
identity; that Valve ID can be passed to game.detail. An unresolved result is
not a confirmed identity: inspect its reason and evidence, and do not choose an
ID from candidate evidence yourself. This tool confirms identity and may fetch
candidate game details as evidence. It does not automatically invoke the
game.detail tool. The returned Artifact stores target selection, League
selection, candidate assessments, timing differences, participant associations,
winner comparisons, and unresolved reasons. Raw Match context, full League
collections and match lists, and candidate game details are internal reads and
are not stored in this result. Use game.detail with the confirmed valve_game_id
to retrieve game facts.

Confirmed mappings are not retained across separate calls, so this tool does
not guarantee whole-Match consistency across separate resolutions.
"""


def register_game_resolution_tool(
    registry: ToolRegistry,
    resolve: GameResolutionHandler,
) -> None:
    async def handler(
        args: EsportsGameResolveInput,
    ) -> EsportsGameResolutionResult:
        return await resolve(args)

    registry.register(
        ToolDefinition(
            name="esports.game.resolve",
            description=GAME_RESOLUTION_DESCRIPTION,
            input_model=EsportsGameResolveInput,
            output_model=EsportsGameResolutionResult,
            handler=handler,
            read_only=True,
            parallel_safe=False,
            always_artifact=True,
            metadata={"game": "dota2", "domain": "game_resolution"},
        )
    )


__all__ = [
    "GAME_RESOLUTION_DESCRIPTION",
    "GameResolutionHandler",
    "register_game_resolution_tool",
]
