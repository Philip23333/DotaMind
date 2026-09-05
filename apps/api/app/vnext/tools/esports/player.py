"""Model-facing player search tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.player import PlayerSearchInput, PlayerSearchResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

PlayerSearchHandler = Callable[[PlayerSearchInput], Awaitable[PlayerSearchResult]]

PLAYER_SEARCH_DESCRIPTION = """\
Search Dota 2 players.

Use this tool to resolve a professional player name or real name to a player ID.

Use team_id to find players currently associated with a known team. Use
active=true when the user specifically asks for active or current players.
The result may include the player's current team; use that team ID with team or
match capabilities when needed.

name is the player's professional name or handle. first_name and last_name
refer to real-name fields. Use id when the exact player ID is already known.
"""


def register_player_tool(registry: ToolRegistry, search: PlayerSearchHandler) -> None:
    async def handler(args: PlayerSearchInput) -> PlayerSearchResult:
        return await search(args)

    registry.register(
        ToolDefinition(
            name="esports.player.search",
            description=PLAYER_SEARCH_DESCRIPTION,
            input_model=PlayerSearchInput,
            output_model=PlayerSearchResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "player"},
        )
    )


__all__ = [
    "PLAYER_SEARCH_DESCRIPTION",
    "PlayerSearchHandler",
    "register_player_tool",
]
