"""Thin agent-visible player capability definitions."""

from __future__ import annotations

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, PlayerRef
from app.vnext.domain.players.models import PlayerGetResult, PlayerSearchResult
from app.vnext.domain.players.service import PlayerService
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class PlayerSearchInput(DomainModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class PlayerGetDetailInput(DomainModel):
    player_ref: PlayerRef = Field(
        description=(
            "Complete PlayerRef object returned by another tool. Pass it unchanged: "
            "{\"player_ref\":{\"value\":\"player:0123456789abcdef01234567\"}}. "
            "Do not pass a bare string or JSON-encode the object into a string."
        )
    )


def register_player_tools(registry: ToolRegistry, service: PlayerService) -> None:
    async def search(args: PlayerSearchInput) -> PlayerSearchResult:
        return await service.search(args.query, limit=args.limit)

    async def get_detail(args: PlayerGetDetailInput) -> PlayerGetResult:
        return await service.get(args.player_ref)

    registry.register(
        ToolDefinition(
            name="players.search",
            description=(
                "Search professional Dota 2 players by nickname or name. Returns normalized "
                "candidates including current-team identity when available and preserves ambiguity."
            ),
            input_model=PlayerSearchInput,
            output_model=PlayerSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="players.get_detail",
            description=(
                "Return normalized source facts and current-team identity for one resolved "
                "PlayerRef."
            ),
            input_model=PlayerGetDetailInput,
            output_model=PlayerGetResult,
            handler=get_detail,
            parallel_safe=True,
        )
    )


__all__ = ["PlayerGetDetailInput", "PlayerSearchInput", "register_player_tools"]
