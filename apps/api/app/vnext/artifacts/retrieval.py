"""Bounded retrieval capabilities for stored canonical artifacts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactRef, game_summary_artifact_ref
from .store import ArtifactStore

ArtifactType = Literal["game_summary"]


class ArtifactPathNotFoundError(LookupError):
    """Raised when a canonical artifact path cannot be traversed."""


class ArtifactReadValidationError(ValueError):
    """Raised when a read request violates bounded retrieval rules."""


class ArtifactSearchResult(BaseModel):
    """References found for a bounded set of canonical Valve match IDs."""

    model_config = ConfigDict(extra="forbid")

    refs: list[ArtifactRef] = Field(default_factory=list)
    missing_valve_match_ids: list[int] = Field(default_factory=list)


class ArtifactReadResult(BaseModel):
    """A serialized outline or bounded value from one canonical artifact."""

    model_config = ConfigDict(extra="forbid")

    ref: ArtifactRef
    path: str | None
    value: Any
    offset: int | None = None
    limit: int | None = None
    total: int | None = None
    truncated: bool = False


class ArtifactSearcher:
    """Find existing GameSummary artifact references without reading content."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def search(
        self,
        artifact_type: ArtifactType,
        valve_match_ids: list[int],
    ) -> ArtifactSearchResult:
        if artifact_type != "game_summary":
            raise ValueError(f"unsupported artifact type: {artifact_type}")
        if len(valve_match_ids) > 100:
            raise ValueError("at most 100 valve match IDs may be searched")

        refs: list[ArtifactRef] = []
        missing: list[int] = []
        seen: set[int] = set()
        for valve_match_id in valve_match_ids:
            if valve_match_id in seen:
                continue
            seen.add(valve_match_id)
            ref = game_summary_artifact_ref(valve_match_id)
            if self._store.exists(ref):
                refs.append(ref)
            else:
                missing.append(valve_match_id)
        return ArtifactSearchResult(refs=refs, missing_valve_match_ids=missing)


class ArtifactReader:
    """Read serialized, bounded views from stored canonical artifacts."""

    MAX_LIMIT = 100

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def read(
        self,
        ref: ArtifactRef,
        path: str | None = None,
        offset: int = 0,
        limit: int = 50,
        *,
        pagination_requested: bool | None = None,
    ) -> ArtifactReadResult:
        if pagination_requested is None:
            pagination_requested = offset != 0 or limit != 50
        _validate_pagination(offset, limit)
        if path is None and pagination_requested:
            raise ArtifactReadValidationError(
                "pagination is only valid when the final value is a list"
            )

        artifact = self._store.get(ref)
        payload = _serialize_artifact(artifact)
        value = _outline(payload) if path is None else _resolve_path(payload, path)
        if isinstance(value, list):
            end = offset + limit
            return ArtifactReadResult(
                ref=ref,
                path=path,
                value=value[offset:end],
                offset=offset,
                limit=limit,
                total=len(value),
                truncated=end < len(value),
            )
        if pagination_requested:
            raise ArtifactReadValidationError(
                "pagination is only valid when the final value is a list"
            )
        return ArtifactReadResult(ref=ref, path=path, value=value)


def _validate_pagination(offset: int, limit: int) -> None:
    if offset < 0:
        raise ArtifactReadValidationError("offset must be non-negative")
    if limit < 1 or limit > ArtifactReader.MAX_LIMIT:
        raise ArtifactReadValidationError(
            f"limit must be between 1 and {ArtifactReader.MAX_LIMIT}"
        )


def _serialize_artifact(artifact: object) -> dict[str, Any]:
    if not isinstance(artifact, BaseModel):
        raise TypeError("stored artifact must be a Pydantic model")
    payload = artifact.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("serialized artifact must be an object")
    return payload


def _outline(payload: dict[str, Any]) -> dict[str, Any]:
    outline: dict[str, Any] = {}
    sections: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            sections[key] = {"kind": "object"}
        elif isinstance(value, list):
            sections[key] = {"kind": "collection", "count": len(value)}
        else:
            outline[key] = value
    outline["sections"] = sections
    return outline


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    if not path or any(segment == "" for segment in path.split(".")):
        raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")

    current: Any = payload
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")
            current = current[segment]
            continue
        if isinstance(current, list):
            if not segment.isascii() or not segment.isdecimal():
                raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")
            index = int(segment)
            if index >= len(current):
                raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")
            current = current[index]
            continue
        raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")
    return current


__all__ = [
    "ArtifactPathNotFoundError",
    "ArtifactReadResult",
    "ArtifactReadValidationError",
    "ArtifactReader",
    "ArtifactSearchResult",
    "ArtifactSearcher",
]
