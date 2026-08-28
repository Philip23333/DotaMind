from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.vnext.artifacts import ArtifactRef, GameSummaryArtifactProducer, MemoryArtifactStore
from app.vnext.artifacts.game_summary import GameSummaryArtifact
from app.vnext.artifacts.game_summary_builder import GameSummaryBuilder
from app.vnext.identity import AbilityResolver, HeroResolver, ItemResolver
from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaGameConstructionAdapter,
    OpenDotaHTTPError,
    OpenDotaSchemaError,
)

MATCH_ID = 8123456789


def _source_payload(*, radiant_score: int = 10) -> dict[str, Any]:
    return {
        "match_id": MATCH_ID,
        "start_time": 1_700_000_000,
        "duration": 2400,
        "radiant_win": True,
        "game_mode": 22,
        "lobby_type": 1,
        "radiant_team": {"team_id": 15, "name": "Radiant Team"},
        "dire_team": {"team_id": 2163, "name": "Dire Team"},
        "radiant_score": radiant_score,
        "dire_score": 20,
        "players": [
            {
                "account_id": 123456,
                "name": "Player",
                "personaname": "Persona",
                "player_slot": 0,
                "hero_id": 1,
                "level": 20,
                "kills": 12,
                "deaths": 3,
                "assists": 15,
                "last_hits": 201,
                "denies": 10,
                "net_worth": 18000,
                "gold_per_min": 600,
                "xp_per_min": 700,
                "item_0": 0,
                "item_1": 1,
                "purchase_log": [{"time": 120, "key": "blink"}],
                "ability_upgrades_arr": [
                    {"ability": 101, "level": 1, "time": 0},
                ],
            }
        ],
    }


def _builder() -> GameSummaryBuilder:
    return GameSummaryBuilder(
        hero_resolver=HeroResolver({1: "Anti-Mage"}),
        item_resolver=ItemResolver(
            {1: "Blink Dagger"},
            item_key_to_id={"blink": 1, "item_blink": 1},
        ),
        ability_resolver=AbilityResolver({101: "Mana Break"}),
    )


class RecordingStore(MemoryArtifactStore):
    def __init__(self) -> None:
        super().__init__()
        self.put_count = 0

    async def put(self, ref: ArtifactRef, artifact: GameSummaryArtifact) -> None:
        self.put_count += 1
        await super().put(ref, artifact)


class FailingBuilder:
    def build(self, context: object) -> GameSummaryArtifact:
        raise RuntimeError("build failed")


class ReidentifiedBuilder:
    def build(self, context: object) -> GameSummaryArtifact:
        artifact = _builder().build(context)
        return artifact.model_copy(
            update={
                "game": artifact.game.model_copy(update={"valve_match_id": 999}),
            }
        )


def _producer(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    store: MemoryArtifactStore | None = None,
    builder: GameSummaryBuilder | FailingBuilder | ReidentifiedBuilder | None = None,
) -> tuple[GameSummaryArtifactProducer, OpenDotaAdapter, MemoryArtifactStore]:
    adapter = OpenDotaAdapter(
        base_url="https://opendota.test/api",
        transport=httpx.MockTransport(handler),
    )
    resolved_store = store if store is not None else MemoryArtifactStore()
    producer = GameSummaryArtifactProducer(
        opendota=adapter,
        construction_adapter=OpenDotaGameConstructionAdapter(),
        builder=builder or _builder(),
        store=resolved_store,
    )
    return producer, adapter, resolved_store


def test_producer_fetches_builds_stores_and_derives_deterministic_ref() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_source_payload(), request=request)

    producer, adapter, store = _producer(handler)

    async def exercise() -> ArtifactRef:
        try:
            return await producer.produce(MATCH_ID)
        finally:
            await adapter.aclose()

    ref = asyncio.run(exercise())

    assert ref == ArtifactRef(
        id="game_summary:3:8123456789",
        artifact_type="game_summary",
        schema_version="3",
    )
    assert asyncio.run(store.exists(ref))
    artifact = asyncio.run(store.get(ref))
    assert artifact.game.valve_match_id == MATCH_ID
    assert artifact.artifact_type == "game_summary"
    assert artifact.schema_version == "3"
    assert artifact.game.winner == "radiant"
    assert artifact.players[0].hero.name == "Anti-Mage"
    assert artifact.players[0].stats.kills == 12
    assert artifact.players[0].items.inventory[1].name == "Blink Dagger"


def test_producer_derives_ref_from_the_completed_artifact_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_source_payload(), request=request)

    producer, adapter, store = _producer(handler, builder=ReidentifiedBuilder())

    async def exercise() -> ArtifactRef:
        try:
            return await producer.produce(MATCH_ID)
        finally:
            await adapter.aclose()

    ref = asyncio.run(exercise())

    assert ref == ArtifactRef(
        id="game_summary:3:999",
        artifact_type="game_summary",
        schema_version="3",
    )
    assert asyncio.run(store.exists(ref))
    assert asyncio.run(store.get(ref)).game.valve_match_id == 999


def test_producer_always_fetches_and_overwrites_the_same_deterministic_ref() -> None:
    payloads = [_source_payload(radiant_score=10), _source_payload(radiant_score=20)]
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=payloads.pop(0), request=request)

    producer, adapter, store = _producer(handler)

    async def exercise() -> tuple[ArtifactRef, ArtifactRef]:
        try:
            return await producer.produce(MATCH_ID), await producer.produce(MATCH_ID)
        finally:
            await adapter.aclose()

    ref1, ref2 = asyncio.run(exercise())

    assert request_count == 2
    assert ref1 == ref2
    assert asyncio.run(store.get(ref2)).teams.radiant.score == 20


def test_producer_does_not_put_when_fetch_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    store = RecordingStore()
    producer, adapter, _ = _producer(handler, store=store)

    async def exercise() -> None:
        try:
            await producer.produce(MATCH_ID)
        finally:
            await adapter.aclose()

    with pytest.raises(OpenDotaHTTPError):
        asyncio.run(exercise())
    assert store.put_count == 0


def test_producer_does_not_put_when_response_match_identity_mismatches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"match_id": 4567}, request=request)

    store = RecordingStore()
    producer, adapter, _ = _producer(handler, store=store)

    async def exercise() -> None:
        try:
            await producer.produce(MATCH_ID)
        finally:
            await adapter.aclose()

    with pytest.raises(OpenDotaSchemaError):
        asyncio.run(exercise())
    assert store.put_count == 0


def test_producer_does_not_put_or_delete_old_artifact_when_build_fails() -> None:
    payloads = [_source_payload(radiant_score=10), _source_payload(radiant_score=20)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads.pop(0), request=request)

    store = RecordingStore()
    producer, adapter, _ = _producer(handler, store=store)

    async def exercise() -> tuple[ArtifactRef, GameSummaryArtifact]:
        first_ref = await producer.produce(MATCH_ID)
        first_artifact = await store.get(first_ref)
        failing_producer = GameSummaryArtifactProducer(
            opendota=adapter,
            construction_adapter=OpenDotaGameConstructionAdapter(),
            builder=FailingBuilder(),
            store=store,
        )
        with pytest.raises(RuntimeError, match="build failed"):
            await failing_producer.produce(MATCH_ID)
        return first_ref, first_artifact

    try:
        first_ref, first_artifact = asyncio.run(exercise())
    finally:
        asyncio.run(adapter.aclose())

    assert store.put_count == 1
    assert asyncio.run(store.get(first_ref)) is first_artifact
    assert asyncio.run(store.get(first_ref)).teams.radiant.score == 10
