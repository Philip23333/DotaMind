"""Model-facing Steam-account profile lookup tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

PlayerProfileHandler = Callable[[PlayerProfileInput], Awaitable[PlayerProfileResult]]

PLAYER_PROFILE_DESCRIPTION = """\
Look up Dota 2 player profile information by numeric Steam32 account ID (also
called the Dota 2 Friend ID). Use only the account's unsigned 32-bit number.
This tool does not accept a nickname, SteamID64, Steam profile URL, or
PandaScore professional-player ID.

The profile contains source-provided account information and counters, not all
STRATZ player data. A result with found=false means STRATZ returned no usable
profile object for this lookup; it does not prove the account does not exist or
has never played Dota 2. retrieved_at is when DotaMind fetched this response,
not when STRATZ last updated the profile.
"""


def register_player_profile_tool(
    registry: ToolRegistry,
    lookup: PlayerProfileHandler,
) -> None:
    async def handler(args: PlayerProfileInput) -> PlayerProfileResult:
        return await lookup(args)

    registry.register(
        ToolDefinition(
            name="player.profile",
            description=PLAYER_PROFILE_DESCRIPTION,
            input_model=PlayerProfileInput,
            output_model=PlayerProfileResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "player", "provider": "stratz"},
        )
    )


__all__ = ["PLAYER_PROFILE_DESCRIPTION", "PlayerProfileHandler", "register_player_profile_tool"]
