"""Model-facing detailed recorded-game capability."""

from typing import Any

from app.vnext.artifacts import ToolResponseExternalizer
from app.vnext.capabilities.game_detail import (
    GameDetailRequest,
    GameDetailResult,
    GameDetailService,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameDetailInput = GameDetailRequest


def register_game_tools(
    registry: ToolRegistry,
    service: GameDetailService,
    externalizer: ToolResponseExternalizer,
) -> None:
    async def detail(args: GameDetailInput) -> GameDetailResult:
        payload = await service.detail(args)
        response = payload.model_dump(mode="json")
        externalized = await externalizer.externalize(response)
        return GameDetailResult(
            source=payload.source,
            valve_game_id=payload.valve_game_id,
            facts=(
                _bounded_game_observation(payload.facts)
                if externalized.spilled
                else payload.facts
            ),
            artifact_ref=externalized.artifact_ref,
        )

    registry.register(
        ToolDefinition(
            name="game.detail",
            description=(
                "Fetch detailed facts for one recorded Dota game identified by its Valve game ID. "
                "Large responses return a bounded observation plus a temporary artifact_ref. "
                "Use artifact.read or artifact.grep with that exact ref to inspect omitted data."
            ),
            input_model=GameDetailInput,
            output_model=GameDetailResult,
            handler=detail,
            parallel_safe=True,
        )
    )


def _bounded_game_observation(document: dict[str, Any]) -> dict[str, Any]:
    observation: dict[str, Any] = {}
    sections: dict[str, dict[str, Any]] = {}
    for key, value in list(document.items())[:32]:
        if isinstance(value, dict):
            sections[key] = {"kind": "object", "fields": len(value)}
        elif isinstance(value, list):
            sections[key] = {"kind": "collection", "count": len(value)}
        elif isinstance(value, str):
            observation[key] = value[:256] + ("…" if len(value) > 256 else "")
        else:
            observation[key] = value
    if sections:
        observation["sections"] = sections
    if len(document) > 32:
        observation["observation_truncated"] = True
    return observation


__all__ = ["GameDetailInput", "register_game_tools"]
