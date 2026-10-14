"""Model-facing lookup for one existing Valve game record."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameDetailHandler = Callable[[GameDetailInput], Awaitable[GameDetailResult]]

GAME_DETAIL_DESCRIPTION = """\
Look up one existing Dota 2 Game by its positive Valve single-game ID. The ID
may be explicitly provided by the user, returned by player.recent_games, or
returned as valve_game_id by a resolved esports.game.resolve result. A PandaScore
Match, Series, or Game ID is not a Valve Game ID and cannot be passed here.

Returns the available OpenDota source record, which may include draft, player,
economy, or other match facts depending on the source record. Availability is
not guaranteed: missing fields do not mean an event did not occur or that a
value was zero. The result is not necessarily a complete event timeline, and
this tool does not request replay parsing. Large results are stored as an
Artifact and can be read by narrower paths when needed.

When analyzing a particular Steam32 account, locate its player row by exact
account_id; do not substitute a row based on nickname, hero, team, or slot.
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
