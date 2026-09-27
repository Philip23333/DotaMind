"""Model-facing lookup for one existing Valve game record."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameDetailHandler = Callable[[GameDetailInput], Awaitable[GameDetailResult]]

GAME_DETAIL_DESCRIPTION = """\
Look up one existing Dota 2 game by its positive Valve single-game ID. The ID
may come from player.recent_games or be explicitly supplied by the user; do not
pass a PandaScore match, series, or game ID. Returns the OpenDota source record
and whatever basic or extended data is currently available, but not necessarily
a complete event timeline. Missing process data does not mean an event did not
occur, and this tool does not request replay parsing. Large results are stored
as an Artifact and can be read by a narrower data path when needed.
"""


def register_game_detail_tool(registry: ToolRegistry, lookup: GameDetailHandler) -> None:
    async def handler(args: GameDetailInput) -> GameDetailResult:
        return await lookup(args)

    registry.register(
        ToolDefinition(
            name="game.detail",
            description=GAME_DETAIL_DESCRIPTION,
            input_model=GameDetailInput,
            output_model=GameDetailResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "game", "provider": "opendota"},
        )
    )


__all__ = ["GAME_DETAIL_DESCRIPTION", "GameDetailHandler", "register_game_detail_tool"]
