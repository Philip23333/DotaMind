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
Resolve one Dota 2 game from a Match returned by esports.match.search.

Pass the Match-search artifact_ref and select one result with match_path such as
items.0. game_position is the source Match Game's position, not an array index.
The tool validates that the Artifact was produced by esports.match.search and
extracts the Match identity from the stored result. Do not provide provider IDs,
team dictionaries, timestamps, or matching budgets.

The result confirms a Valve game identity only when the collected evidence
supports it. Otherwise inspect its unresolved reason and evidence. Confirmed
game mappings are not retained across separate tool calls, so this tool does not
guarantee whole-Match consistency across multiple resolutions.
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
