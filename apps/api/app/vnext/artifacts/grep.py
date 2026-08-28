"""Generic bounded literal search over stored canonical artifact content."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactRef
from .store import ArtifactStore


class ArtifactGrepMatch(BaseModel):
    """One searchable scalar leaf inside a canonical artifact."""

    model_config = ConfigDict(extra="forbid")

    ref: ArtifactRef
    path: str
    preview: str


class ArtifactGrepResult(BaseModel):
    """A bounded set of generic canonical content observations."""

    model_config = ConfigDict(extra="forbid")

    matches: list[ArtifactGrepMatch] = Field(default_factory=list)
    returned: int
    truncated: bool


class ArtifactGrepper:
    """Search scalar leaves without interpreting artifact-specific domain data."""

    MAX_PATTERN_LENGTH = 256
    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100
    MAX_PREVIEW_LENGTH = 200

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def grep(
        self,
        pattern: str,
        artifact_types: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> ArtifactGrepResult:
        _validate_search(pattern, limit)
        normalized_pattern = pattern.casefold()
        matches: list[ArtifactGrepMatch] = []

        async for ref in self._store.iter_refs(artifact_types):
            artifact = await self._store.get(ref)
            payload = _serialize_artifact(artifact)
            for path, value in _scalar_leaves(payload):
                match_index = value.casefold().find(normalized_pattern)
                if match_index < 0:
                    continue
                matches.append(
                    ArtifactGrepMatch(
                        ref=ref,
                        path=path,
                        preview=_preview(value, match_index),
                    )
                )
                if len(matches) > limit:
                    return ArtifactGrepResult(
                        matches=matches[:limit],
                        returned=limit,
                        truncated=True,
                    )

        return ArtifactGrepResult(
            matches=matches,
            returned=len(matches),
            truncated=False,
        )


def _validate_search(pattern: str, limit: int) -> None:
    if not pattern or pattern.isspace():
        raise ValueError("artifact grep pattern must not be empty")
    if len(pattern) > ArtifactGrepper.MAX_PATTERN_LENGTH:
        raise ValueError(
            f"artifact grep pattern must be at most {ArtifactGrepper.MAX_PATTERN_LENGTH} characters"
        )
    if limit < 1 or limit > ArtifactGrepper.MAX_LIMIT:
        raise ValueError(
            f"artifact grep limit must be between 1 and {ArtifactGrepper.MAX_LIMIT}"
        )


def _serialize_artifact(artifact: object) -> dict[str, Any]:
    if not isinstance(artifact, BaseModel):
        raise TypeError("stored artifact must be a Pydantic model")
    payload = artifact.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("serialized artifact must be an object")
    return payload


def _scalar_leaves(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key or "." in key:
                continue
            child_path = f"{path}.{key}" if path else key
            yield from _scalar_leaves(child, child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}.{index}" if path else str(index)
            yield from _scalar_leaves(child, child_path)
        return
    if isinstance(value, (str, int, float, bool)) and not isinstance(value, type(None)):
        yield path, _scalar_text(value)


def _scalar_text(value: str | int | float | bool) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _preview(value: str, match_index: int) -> str:
    if len(value) <= ArtifactGrepper.MAX_PREVIEW_LENGTH:
        return value

    marker_length = 1
    available = ArtifactGrepper.MAX_PREVIEW_LENGTH - (2 * marker_length)
    start = max(0, match_index - (available // 2))
    end = min(len(value), start + available)
    start = max(0, end - available)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(value) else ""
    return f"{prefix}{value[start:end]}{suffix}"


__all__ = ["ArtifactGrepMatch", "ArtifactGrepResult", "ArtifactGrepper"]
