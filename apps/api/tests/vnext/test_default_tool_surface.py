"""Default model-visible vNext tool surface contracts."""

import asyncio
import json

from app.vnext.capabilities.esports.game_resolution import EsportsGameResolutionResult
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
)
from app.vnext.llm.protocol import ToolCall


def test_default_registry_exposes_only_current_capabilities() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    tool_names = {tool.name for tool in registry.schemas()}
    assert tool_names == {
        "math.calculate",
        "artifact.grep",
        "artifact.read",
        "artifact.query",
        "esports.league.search",
        "esports.series.search",
        "esports.tournament.search",
        "esports.series.teams",
        "esports.match.search",
        "esports.team.search",
        "esports.player.search",
        "catalog.lookup",
    }
    assert "game_summary" not in json.dumps(
        [tool.model_dump(mode="json") for tool in registry.schemas()]
    )
    assert "esports.game.resolve" not in tool_names


def test_opt_in_registry_registers_resolution_and_keeps_game_detail() -> None:
    async def match_search(_query) -> MatchSearchResult:
        return MatchSearchResult(items=[], page=1, limit=20)

    async def game_detail(_query: GameDetailInput) -> GameDetailResult:
        raise AssertionError("tool registration must not call services")

    class ResolutionService:
        async def resolve(self, *_args, **_kwargs) -> EsportsGameResolutionResult:
            raise AssertionError("tool registration must not call services")

    settings = VNextSettings(
        game_resolution_enabled=True,
        pandascore_token="configured-token",
        opendota_enabled=True,
    )
    registry_services = VNextServices(
        match_search=match_search,
        game_detail=game_detail,
        game_resolution=ResolutionService(),  # type: ignore[arg-type]
    )
    registry = build_vnext_registry(registry_services, settings=settings)

    names = {tool.name for tool in registry.schemas()}
    assert "esports.match.search" in names
    assert "esports.game.resolve" in names
    assert "game.detail" in names

    default_registry = build_vnext_registry(
        registry_services,
        settings=VNextSettings(),
    )
    assert "esports.game.resolve" not in {tool.name for tool in default_registry.schemas()}


def test_artifact_grep_requires_one_exact_ref() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    result = asyncio.run(
        registry.execute(
            ToolCall(id="corpus", name="artifact.grep", arguments={"pattern": "anything"})
        )
    )

    assert result.error is not None
    assert result.error.code == "invalid_arguments"
