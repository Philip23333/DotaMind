"""Model-facing detailed recorded-game capability."""

from app.vnext.capabilities.game_detail import (
    GameDetailRequest,
    GameDetailResult,
    GameDetailService,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameDetailInput = GameDetailRequest


def register_game_tools(registry: ToolRegistry, service: GameDetailService) -> None:
    async def detail(args: GameDetailInput) -> GameDetailResult:
        return await service.detail(args)

    registry.register(
        ToolDefinition(
            name="game.detail",
            description=(
                "Fetch detailed facts for one recorded Dota game identified by its Valve game ID. "
                "Returns a bounded observation plus an ArtifactRef to the complete validated game "
                "document."
            ),
            input_model=GameDetailInput,
            output_model=GameDetailResult,
            handler=detail,
            parallel_safe=True,
        )
    )


__all__ = ["GameDetailInput", "register_game_tools"]
