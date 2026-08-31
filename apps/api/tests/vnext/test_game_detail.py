"""Contracts for source-backed detailed recorded-game retrieval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.vnext.artifacts import (
    ArtifactReader,
    MemoryArtifactStore,
    game_detail_artifact_ref,
)
from app.vnext.capabilities.game_detail import GameDetailRequest, GameDetailService
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.common import ProviderObject
from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaHTTPError,
    OpenDotaProviderError,
    OpenDotaSchemaError,
    OpenDotaTimeoutError,
)
from app.vnext.providers.opendota.models import OpenDotaGameDetailDocument
from app.vnext.tools.domain.game import register_game_tools
from app.vnext.tools.registry import ToolRegistry

FETCHED_AT = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _payload(match_id: int, *, professional: bool = True) -> dict[str, object]:
    return {
        "match_id": match_id,
        "leagueid": 123 if professional else 0,
        "radiant_team": {"team_id": 1, "name": "Radiant"} if professional else None,
        "dire_team": {"team_id": 2, "name": "Dire"} if professional else None,
        "teamfights": [{"start": 10, "end": 20}],
        "objectives": [{"type": "CHAT_MESSAGE_FIRSTBLOOD"}],
        "chat": [{"time": 3, "key": "glhf"}],
        "radiant_gold_adv": [0, 50],
        "players": [
            {
                "hero_id": 11,
                "gold_t": [600, 700],
                "obs_log": [{"time": 8, "type": "obs"}],
                "some_future_opendota_field": 123,
            }
        ],
        "some_future_top_level_field": {"x": 1},
    }


def _adapter(handler) -> OpenDotaAdapter:  # type: ignore[no-untyped-def]
    return OpenDotaAdapter(
        base_url="https://opendota.test/api",
        transport=httpx.MockTransport(handler),
    )


class StubOpenDota:
    def __init__(
        self, document: dict[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self.document = document
        self.error = error
        self.requested_match_ids: list[int] = []

    async def get_game_detail(self, match_id: int) -> ProviderObject[OpenDotaGameDetailDocument]:
        self.requested_match_ids.append(match_id)
        if self.error is not None:
            raise self.error
        assert self.document is not None
        return ProviderObject(
            item=OpenDotaGameDetailDocument.model_validate(self.document),
            fetched_at=FETCHED_AT,
        )


class FailingStore(MemoryArtifactStore):
    async def put(self, ref, artifact) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("store unavailable")


def _registry(service: GameDetailService) -> ToolRegistry:
    registry = ToolRegistry()
    register_game_tools(registry, service)
    return registry


def test_game_detail_schema_is_exact_and_non_positive_ids_are_invalid() -> None:
    registry = _registry(GameDetailService(StubOpenDota(_payload(1)), MemoryArtifactStore()))  # type: ignore[arg-type]
    schema = next(tool.input_schema for tool in registry.schemas() if tool.name == "game.detail")

    assert set(schema["properties"]) == {"valve_game_id"}
    assert schema["required"] == ["valve_game_id"]
    assert schema["properties"]["valve_game_id"]["exclusiveMinimum"] == 0

    result = asyncio.run(
        registry.execute(ToolCall(id="invalid", name="game.detail", arguments={"valve_game_id": 0}))
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"


def test_game_detail_externalizes_complete_source_document_and_preserves_future_fields() -> None:
    match_id = 8960577698
    payload = _payload(match_id)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=payload)

    adapter = _adapter(handler)
    store = MemoryArtifactStore()
    service = GameDetailService(adapter, store)

    async def exercise():
        try:
            result = await service.detail(GameDetailRequest(valve_game_id=match_id))
            top_level = await ArtifactReader(store).read(
                result.artifact_ref,
                "facts.some_future_top_level_field",
            )
            nested = await ArtifactReader(store).read(
                result.artifact_ref,
                "facts.players.0.some_future_opendota_field",
            )
            return result, top_level, nested
        finally:
            await adapter.aclose()

    result, top_level, nested = asyncio.run(exercise())

    assert calls == [f"/api/matches/{match_id}"]
    assert result.source == "opendota"
    assert result.valve_game_id == match_id
    assert result.artifact_ref == game_detail_artifact_ref(match_id)
    assert result.facts["sections"]["players"] == {"kind": "collection", "count": 1}
    assert top_level.value == {"x": 1}
    assert nested.value == 123
    artifact = asyncio.run(store.get(result.artifact_ref))
    assert artifact.artifact_type == "game_detail"
    assert artifact.schema_version == "1"


@pytest.mark.parametrize("professional", [False, True])
def test_game_detail_uses_one_artifact_contract_for_public_and_professional_games(
    professional: bool,
) -> None:
    match_id = 1001 if professional else 1002
    service = GameDetailService(
        StubOpenDota(_payload(match_id, professional=professional)),  # type: ignore[arg-type]
        MemoryArtifactStore(),
    )

    result = asyncio.run(service.detail(GameDetailRequest(valve_game_id=match_id)))

    assert result.artifact_ref.artifact_type == "game_detail"
    assert result.artifact_ref.schema_version == "1"
    assert result.facts["leagueid"] == (123 if professional else 0)


def test_game_detail_reuses_a_stable_artifact_reference_for_the_same_valve_id() -> None:
    match_id = 2001
    upstream = StubOpenDota(_payload(match_id))
    service = GameDetailService(upstream, MemoryArtifactStore())  # type: ignore[arg-type]

    first = asyncio.run(service.detail(GameDetailRequest(valve_game_id=match_id)))
    second = asyncio.run(service.detail(GameDetailRequest(valve_game_id=match_id)))

    assert upstream.requested_match_ids == [match_id, match_id]
    assert first.artifact_ref == second.artifact_ref == game_detail_artifact_ref(match_id)


def test_game_detail_maps_returned_identity_mismatch_to_provider_error() -> None:
    requested_id = 3001

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(3002))

    adapter = _adapter(handler)
    registry = _registry(GameDetailService(adapter, MemoryArtifactStore()))

    async def exercise():
        try:
            return await registry.execute(
                ToolCall(
                    id="mismatch", name="game.detail", arguments={"valve_game_id": requested_id}
                )
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert result.error is not None
    assert result.error.code == "provider_error"
    assert result.error.details == {"source": "opendota", "valve_game_id": requested_id}


@pytest.mark.parametrize(
    "error",
    [
        OpenDotaTimeoutError("timeout"),
        OpenDotaHTTPError(503, "/matches/4001"),
        OpenDotaSchemaError("schema"),
    ],
)
def test_game_detail_maps_opendota_failures_to_provider_error(error: OpenDotaProviderError) -> None:
    match_id = 4001
    registry = _registry(
        GameDetailService(StubOpenDota(error=error), MemoryArtifactStore())  # type: ignore[arg-type]
    )

    result = asyncio.run(
        registry.execute(
            ToolCall(id="provider", name="game.detail", arguments={"valve_game_id": match_id})
        )
    )
    assert result.error is not None
    assert result.error.code == "provider_error"
    assert result.error.details == {"source": "opendota", "valve_game_id": match_id}


def test_game_detail_maps_artifact_write_failure_to_artifact_error() -> None:
    match_id = 5001
    registry = _registry(
        GameDetailService(StubOpenDota(_payload(match_id)), FailingStore())  # type: ignore[arg-type]
    )

    result = asyncio.run(
        registry.execute(
            ToolCall(id="artifact", name="game.detail", arguments={"valve_game_id": match_id})
        )
    )
    assert result.error is not None
    assert result.error.code == "artifact_error"
    assert result.error.details == {"source": "opendota", "valve_game_id": match_id}
