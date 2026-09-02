"""Contracts for session-local externalization of game.detail responses."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.vnext.artifacts import ArtifactReader, SessionArtifactStore, ToolResponseExternalizer
from app.vnext.capabilities.game_detail import GameDetailService
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.common import ProviderObject
from app.vnext.providers.opendota.models import OpenDotaGameDetailDocument
from app.vnext.tools.domain.game import register_game_tools
from app.vnext.tools.registry import ToolRegistry

FETCHED_AT = datetime(2026, 9, 3, tzinfo=timezone.utc)


class StubOpenDota:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document

    async def get_game_detail(self, match_id: int) -> ProviderObject[OpenDotaGameDetailDocument]:
        return ProviderObject(
            item=OpenDotaGameDetailDocument.model_validate(self.document),
            fetched_at=FETCHED_AT,
        )


def _large_payload(match_id: int) -> dict[str, object]:
    return {
        "match_id": match_id,
        "leagueid": 123,
        "players": [{"hero_id": 11, "future_field": "x" * 13_000}],
        "future_top_level": {"x": 1},
    }


def _registry(document: dict[str, object]) -> tuple[ToolRegistry, SessionArtifactStore]:
    store = SessionArtifactStore()
    registry = ToolRegistry()
    register_game_tools(
        registry,
        GameDetailService(StubOpenDota(document)),  # type: ignore[arg-type]
        ToolResponseExternalizer(store),
    )
    return registry, store


def test_game_detail_large_response_uses_fresh_opaque_ref_and_root_paths() -> None:
    registry, store = _registry(_large_payload(8960577698))

    async def exercise():
        first = await registry.execute(
            ToolCall(id="first", name="game.detail", arguments={"valve_game_id": 8960577698})
        )
        second = await registry.execute(
            ToolCall(id="second", name="game.detail", arguments={"valve_game_id": 8960577698})
        )
        reader = ArtifactReader(store)
        value = await reader.read(first.content["artifact_ref"], "facts.future_top_level")
        return first, second, value

    first, second, value = asyncio.run(exercise())

    assert first.status == "ok"
    assert first.content["artifact_ref"].startswith("artifact:tool:")
    assert first.content["artifact_ref"] != second.content["artifact_ref"]
    assert first.content["facts"]["sections"]["players"] == {"kind": "collection", "count": 1}
    assert value.value == {"x": 1}


def test_game_detail_small_response_stays_inline() -> None:
    registry, _ = _registry({"match_id": 42, "leagueid": 0, "players": []})

    result = asyncio.run(
        registry.execute(ToolCall(id="small", name="game.detail", arguments={"valve_game_id": 42}))
    )

    assert result.status == "ok"
    assert result.content["artifact_ref"] is None
    assert result.content["facts"] == {"match_id": 42, "leagueid": 0, "players": []}
