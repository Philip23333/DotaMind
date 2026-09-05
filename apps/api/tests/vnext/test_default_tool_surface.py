"""Default model-visible vNext tool surface contracts."""

import asyncio
import json

from app.vnext.composition import VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall


def test_default_registry_exposes_only_current_capabilities() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    tool_names = {tool.name for tool in registry.schemas()}
    assert tool_names == {
        "artifact.grep",
        "artifact.read",
        "esports.league.search",
        "esports.series.search",
        "esports.tournament.search",
        "esports.tournament.rosters",
        "esports.match.search",
        "esports.team.search",
        "esports.player.search",
    }
    assert "game_summary" not in json.dumps(
        [tool.model_dump(mode="json") for tool in registry.schemas()]
    )


def test_artifact_grep_requires_one_exact_ref() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    result = asyncio.run(
        registry.execute(
            ToolCall(id="corpus", name="artifact.grep", arguments={"pattern": "anything"})
        )
    )

    assert result.error is not None
    assert result.error.code == "invalid_arguments"
