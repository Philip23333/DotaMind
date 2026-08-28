"""Generic, TTL-aligned membership storage for canonical artifact corpora."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from .models import ArtifactRef
from .store import ArtifactStoreUnavailableError


class ArtifactScopeRef(BaseModel):
    """Opaque locator for an artifact corpus; its meaning is owned by callers."""

    model_config = ConfigDict(frozen=True)
    value: str = Field(min_length=1)


class ArtifactScopeStore(Protocol):
    async def add(self, scope: ArtifactScopeRef, artifact_ref: ArtifactRef) -> None:
        """Record membership and refresh the scope retention TTL."""

    def iter_refs(self, scope: ArtifactScopeRef) -> AsyncIterator[ArtifactRef]:
        """Yield retained members without refreshing their TTL."""


class MemoryArtifactScopeStore:
    """Process-lifetime generic scope membership for local composition."""

    def __init__(self) -> None:
        self._members: dict[str, dict[str, ArtifactRef]] = {}

    async def add(self, scope: ArtifactScopeRef, artifact_ref: ArtifactRef) -> None:
        self._members.setdefault(scope.value, {})[artifact_ref.id] = artifact_ref

    async def iter_refs(self, scope: ArtifactScopeRef) -> AsyncIterator[ArtifactRef]:
        for ref in sorted(self._members.get(scope.value, {}).values(), key=lambda item: item.id):
            yield ref


class RedisArtifactScopeStore:
    """Redis Set implementation that stores complete canonical ArtifactRef JSON."""

    KEY_PREFIX = "dotamind:vnext:artifact-scope:v1:"
    DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("artifact scope TTL must be greater than zero")
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def add(self, scope: ArtifactScopeRef, artifact_ref: ArtifactRef) -> None:
        key = self.key_for(scope)
        member = json.dumps(artifact_ref.model_dump(mode="json"), separators=(",", ":"))
        try:
            await self._client.sadd(key, member)
            await self._client.expire(key, self._ttl_seconds)
        except (RedisError, OSError) as exc:
            raise ArtifactStoreUnavailableError(
                "artifact scope storage is temporarily unavailable"
            ) from exc

    async def iter_refs(self, scope: ArtifactScopeRef) -> AsyncIterator[ArtifactRef]:
        try:
            members = await self._client.smembers(self.key_for(scope))
        except (RedisError, OSError) as exc:
            raise ArtifactStoreUnavailableError(
                "artifact scope storage is temporarily unavailable"
            ) from exc
        refs: dict[str, ArtifactRef] = {}
        for member in members:
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            ref = ArtifactRef.model_validate(json.loads(member))
            refs[ref.id] = ref
        for ref in sorted(refs.values(), key=lambda item: item.id):
            yield ref

    @classmethod
    def key_for(cls, scope: ArtifactScopeRef) -> str:
        return f"{cls.KEY_PREFIX}{scope.value}"


__all__ = [
    "ArtifactScopeRef",
    "ArtifactScopeStore",
    "MemoryArtifactScopeStore",
    "RedisArtifactScopeStore",
]
