"""Generic bounded literal search inside one referenced document."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .manuals import ManualResolver
from .store import ArtifactNotFoundError, SessionArtifactStore


class ArtifactGrepMatch(BaseModel):
    """One searchable scalar leaf inside one referenced document."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    path: str
    preview: str


class ArtifactGrepResult(BaseModel):
    """A bounded set of generic document observations."""

    model_config = ConfigDict(extra="forbid")

    matches: list[ArtifactGrepMatch] = Field(default_factory=list)
    returned: int
    truncated: bool


class ArtifactGrepper:
    """Search scalar leaves without interpreting a tool response."""

    MAX_PATTERN_LENGTH = 256
    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100
    MAX_PREVIEW_LENGTH = 200

    def __init__(
        self,
        store: SessionArtifactStore,
        manuals: ManualResolver | None = None,
    ) -> None:
        self._store = store
        self._manuals = manuals

    async def grep(
        self,
        ref: str,
        pattern: str,
        limit: int = DEFAULT_LIMIT,
    ) -> ArtifactGrepResult:
        _validate_search(pattern, limit)
        normalized_pattern = pattern.casefold()
        if ref.startswith("manual:pandascore:"):
            if self._manuals is None:
                raise ArtifactNotFoundError(f"artifact not found: {ref}")
            value = self._manuals.read(ref)
            match_index = value.casefold().find(normalized_pattern)
            matches = (
                [
                    ArtifactGrepMatch(
                        ref=ref,
                        path="content",
                        preview=_preview(value, match_index),
                    )
                ]
                if match_index >= 0
                else []
            )
            return ArtifactGrepResult(
                matches=matches,
                returned=len(matches),
                truncated=False,
            )
        return _grep_document(ref, await self._store.get(ref), normalized_pattern, limit)


def _grep_document(
    ref: str,
    payload: Any,
    normalized_pattern: str,
    limit: int,
) -> ArtifactGrepResult:
    matches: list[ArtifactGrepMatch] = []
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
