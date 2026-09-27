"""Model-facing recent Dota 2 games for one Steam32 account."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.player.recent_games import (
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

PlayerRecentGamesHandler = Callable[[PlayerRecentGamesInput], Awaitable[PlayerRecentGamesResult]]

PLAYER_RECENT_GAMES_DESCRIPTION = """\
Return up to the requested number of recent Dota 2 games for an exact numeric
Steam32 account ID (not a SteamID64 value or player name). Results are ordered
newest first according to STRATZ's match-date ordering. The returned
valve_game_id is the single-game ID accepted by the game.detail contract.
Receiving fewer rows than requested does not prove that the player's history is
complete. A game with an empty players list is still a source match record;
without a target-player row, do not infer that player's hero, result, or
performance for that game.
"""


def register_player_recent_games_tool(
    registry: ToolRegistry,
    lookup: PlayerRecentGamesHandler,
) -> None:
    async def handler(args: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        return await lookup(args)

    registry.register(
        ToolDefinition(
            name="player.recent_games",
            description=PLAYER_RECENT_GAMES_DESCRIPTION,
            input_model=PlayerRecentGamesInput,
            output_model=PlayerRecentGamesResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "player", "provider": "stratz"},
        )
    )


__all__ = [
    "PLAYER_RECENT_GAMES_DESCRIPTION",
    "PlayerRecentGamesHandler",
    "register_player_recent_games_tool",
]
