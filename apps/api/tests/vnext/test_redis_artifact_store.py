from __future__ import annotations

import asyncio
import json

import pytest

from app.vnext.artifacts import (
    ArtifactNotFoundError,
    ArtifactStoreUnavailableError,
    ArtifactTypeMismatchError,
    RedisArtifactStore,
    game_summary_artifact_ref,
)
from app.vnext.artifacts.game_summary_v4 import GameSummaryArtifactV4


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def scan(self, *, cursor: int, match: str) -> tuple[int, list[str]]:
        assert cursor == 0
        prefix = match.removesuffix("*")
        return 0, list(reversed([key for key in self.values if key.startswith(prefix)]))


class UnavailableRedis:
    async def get(self, key: str) -> None:
        raise OSError("connection refused")


def _artifact(match_id: int = 8960577698) -> GameSummaryArtifactV4:
    return GameSummaryArtifactV4(game={"valve_match_id": match_id}, teams={})


def test_redis_store_round_trips_v4_with_a_versioned_key_and_fixed_ttl() -> None:
    client = FakeRedis()
    store = RedisArtifactStore(client, ttl_seconds=600)
    ref = game_summary_artifact_ref(8960577698, schema_version="4")

    asyncio.run(store.put(ref, _artifact()))

    key = "dotamind:vnext:artifact:v1:game_summary:4:8960577698"
    assert client.expirations[key] == 600
    envelope = json.loads(client.values[key])
    assert envelope["storage_schema_version"] == 1
    assert envelope["ref"] == ref.model_dump()
    assert asyncio.run(store.get(ref)).game.valve_match_id == 8960577698
    assert asyncio.run(store.exists(ref)) is True


def test_redis_get_and_exists_do_not_refresh_ttl() -> None:
    client = FakeRedis()
    store = RedisArtifactStore(client, ttl_seconds=600)
    ref = game_summary_artifact_ref(8960577698, schema_version="4")
    asyncio.run(store.put(ref, _artifact()))
    key = store.key_for(ref)

    asyncio.run(store.get(ref))
    asyncio.run(store.exists(ref))

    assert client.expirations[key] == 600


def test_redis_store_reports_missing_and_unavailable_distinctly() -> None:
    ref = game_summary_artifact_ref(8960577698, schema_version="4")

    with pytest.raises(ArtifactNotFoundError):
        asyncio.run(RedisArtifactStore(FakeRedis()).get(ref))
    with pytest.raises(ArtifactStoreUnavailableError):
        asyncio.run(RedisArtifactStore(UnavailableRedis()).get(ref))


def test_redis_store_rejects_mismatched_stored_reference_metadata() -> None:
    client = FakeRedis()
    store = RedisArtifactStore(client)
    ref = game_summary_artifact_ref(8960577698, schema_version="4")
    asyncio.run(store.put(ref, _artifact()))
    envelope = json.loads(client.values[store.key_for(ref)])
    envelope["ref"]["schema_version"] = "3"
    client.values[store.key_for(ref)] = json.dumps(envelope)

    with pytest.raises(ArtifactTypeMismatchError):
        asyncio.run(store.get(ref))


def test_redis_store_iterates_retained_refs_with_scan_and_type_filtering() -> None:
    client = FakeRedis()
    store = RedisArtifactStore(client)
    first = game_summary_artifact_ref(100, schema_version="4")
    second = game_summary_artifact_ref(200, schema_version="4")
    asyncio.run(store.put(second, _artifact(200)))
    asyncio.run(store.put(first, _artifact(100)))

    async def collect(artifact_types: list[str] | None = None):
        return [ref async for ref in store.iter_refs(artifact_types)]

    assert asyncio.run(collect()) == [first, second]
    assert asyncio.run(collect(["other"])) == []
