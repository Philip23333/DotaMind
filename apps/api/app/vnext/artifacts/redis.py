"""Redis-backed retention store for versioned canonical artifacts."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from redis.exceptions import RedisError

from .game_summary import GameSummaryArtifact
from .game_summary_v4 import GameSummaryArtifactV4
from .models import ArtifactRef
from .protocol import Artifact
from .store import (
    ArtifactNotFoundError,
    ArtifactStoreUnavailableError,
    ArtifactTypeMismatchError,
    validate_artifact_reference,
)


class RedisArtifactStore:
    """Store supported canonical artifacts with fixed retention in Redis."""

    STORAGE_SCHEMA_VERSION = 1
    DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
    _ARTIFACT_MODELS: dict[tuple[str, str], type[BaseModel]] = {
        ("game_summary", "3"): GameSummaryArtifact,
        ("game_summary", "4"): GameSummaryArtifactV4,
    }

    def __init__(self, client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("artifact TTL must be greater than zero")
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
        validate_artifact_reference(ref, artifact)
        if not isinstance(artifact, BaseModel):
            raise TypeError("RedisArtifactStore only supports Pydantic artifacts")
        envelope = {
            "storage_schema_version": self.STORAGE_SCHEMA_VERSION,
            "ref": ref.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
        }
        await self._redis_call(
            lambda: self._client.set(
                self.key_for(ref),
                json.dumps(envelope, separators=(",", ":")),
                ex=self._ttl_seconds,
            )
        )

    async def get(self, ref: ArtifactRef) -> Artifact:
        payload = await self._redis_call(lambda: self._client.get(self.key_for(ref)))
        if payload is None:
            raise ArtifactNotFoundError(f"artifact not found: {ref.id!r}")
        envelope = self._decode_envelope(payload)
        stored_ref = ArtifactRef.model_validate(envelope["ref"])
        if stored_ref != ref:
            raise ArtifactTypeMismatchError(
                f"stored artifact metadata does not match requested reference: {ref.id!r}"
            )
        artifact_model = self._ARTIFACT_MODELS.get(
            (stored_ref.artifact_type, stored_ref.schema_version)
        )
        if artifact_model is None:
            raise ArtifactTypeMismatchError(
                "unsupported stored artifact metadata: "
                f"type={stored_ref.artifact_type!r}, schema_version={stored_ref.schema_version!r}"
            )
        artifact = artifact_model.model_validate(envelope["artifact"])
        validate_artifact_reference(stored_ref, artifact)
        return artifact

    async def exists(self, ref: ArtifactRef) -> bool:
        return bool(await self._redis_call(lambda: self._client.exists(self.key_for(ref))))

    @classmethod
    def key_for(cls, ref: ArtifactRef) -> str:
        return f"dotamind:vnext:artifact:v{cls.STORAGE_SCHEMA_VERSION}:{ref.id}"

    @staticmethod
    def _decode_envelope(payload: str | bytes) -> dict[str, Any]:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("stored artifact envelope must be an object")
        if decoded.get("storage_schema_version") != RedisArtifactStore.STORAGE_SCHEMA_VERSION:
            raise ValueError("unsupported artifact storage schema version")
        if not isinstance(decoded.get("ref"), dict) or not isinstance(
            decoded.get("artifact"), dict
        ):
            raise ValueError("stored artifact envelope is incomplete")
        return decoded

    async def _redis_call(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await operation()
        except (RedisError, OSError) as exc:
            raise ArtifactStoreUnavailableError(
                "artifact storage is temporarily unavailable"
            ) from exc


__all__ = ["RedisArtifactStore"]
