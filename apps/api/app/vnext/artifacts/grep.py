"""Generic bounded literal search inside one referenced document."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .externalize import serialized_size
from .limits import DEFAULT_ARTIFACT_LIMITS
from .manuals import ManualResolver
from .retrieval import ArtifactReadValidationError
from .store import ArtifactNotFoundError, SessionArtifactStore


class ArtifactGrepMatch(BaseModel):
    """One matching member or scalar inside one referenced document."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    path: str
    preview: str
    value_type: Literal["object", "array", "string", "number", "boolean", "null"]


class ArtifactGrepResult(BaseModel):
    """A bounded set of generic document observations."""

    model_config = ConfigDict(extra="forbid")

    matches: list[ArtifactGrepMatch] = Field(default_factory=list)
    offset: int
    limit: int
    returned: int
    next_offset: int | None
    truncated: bool


class ArtifactGrepper:
    """Discover member names and scalar values without business interpretation."""

    MAX_PATTERN_LENGTH = 256
    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100
    MAX_PREVIEW_LENGTH = 200

    def __init__(
        self,
        store: SessionArtifactStore,
        manuals: ManualResolver | None = None,
        *,
        observation_max_bytes: int = DEFAULT_ARTIFACT_LIMITS.observation_max_bytes,
    ) -> None:
        self._store = store
        self._manuals = manuals
        self._max_bytes = observation_max_bytes

    async def grep(
        self,
        ref: str,
        pattern: str,
        limit: int = DEFAULT_LIMIT,
        *,
        offset: int = 0,
    ) -> ArtifactGrepResult:
        _validate_search(pattern, limit, offset)
        normalized_pattern = pattern.casefold()
        if ref.startswith("manual:"):
            if self._manuals is None:
                raise ArtifactNotFoundError(f"artifact not found: {ref}")
            document = {"content": self._manuals.read(ref)}
        else:
            document = await self._store.get(ref)
        # As for query, caller cancellation does not forcibly stop this worker.
        return await asyncio.to_thread(
            _grep_document, ref, document, normalized_pattern, limit, offset, self._max_bytes
        )


def _grep_document(
    ref: str,
    payload: Any,
    normalized_pattern: str,
    limit: int,
    offset: int,
    max_bytes: int,
) -> ArtifactGrepResult:
    matches: list[ArtifactGrepMatch] = []
    more = False
    for index, match in enumerate(_matching_nodes(ref, payload, normalized_pattern)):
        if index < offset:
            continue
        if len(matches) == limit:
            more = True
            break
        matches.append(match)
    while True:
        returned = len(matches)
        result = ArtifactGrepResult(
            matches=matches,
            offset=offset,
            limit=limit,
            returned=returned,
            next_offset=offset + returned if more else None,
            truncated=more,
        )
        if serialized_size(result.model_dump(mode="json")) <= max_bytes:
            return result
        if len(matches) <= 1:
            raise ArtifactReadValidationError(
                "grep match or result envelope exceeds observation byte limit; "
                "use a more specific pattern"
            )
        matches.pop()
        more = True


def _matching_nodes(ref: str, payload: Any, normalized_pattern: str) -> Iterator[ArtifactGrepMatch]:
    for path, member, value in _document_nodes(payload):
        member_matches = member is not None and normalized_pattern in member.casefold()
        scalar = not isinstance(value, (dict, list))
        text = _scalar_text(value) if scalar else ""
        match_index = text.casefold().find(normalized_pattern)
        if not member_matches and (not scalar or match_index < 0):
            continue
        yield ArtifactGrepMatch(
            ref=ref,
            path=path,
            preview=(
                _preview(text, max(0, match_index))
                if scalar
                else f"{_value_type(value)} ({len(value)} items)"
            ),
            value_type=_value_type(value),
        )


def _validate_search(pattern: str, limit: int, offset: int) -> None:
    if not isinstance(pattern, str) or not pattern or pattern.isspace():
        raise ArtifactReadValidationError("artifact grep pattern must not be blank")
    if len(pattern) > ArtifactGrepper.MAX_PATTERN_LENGTH:
        raise ArtifactReadValidationError(
            f"artifact grep pattern must be at most {ArtifactGrepper.MAX_PATTERN_LENGTH} characters"
        )
    if type(limit) is not int or not 1 <= limit <= ArtifactGrepper.MAX_LIMIT:
        raise ArtifactReadValidationError(
            f"artifact grep limit must be between 1 and {ArtifactGrepper.MAX_LIMIT}"
        )
    if type(offset) is not int or offset < 0:
        raise ArtifactReadValidationError("artifact grep offset must be a nonnegative integer")


def _document_nodes(
    value: Any, path: str = "", member: str | None = None
) -> Iterator[tuple[str, str | None, Any]]:
    yield path, member, value
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key or "." in key:
                raise ArtifactReadValidationError(
                    "artifact grep requires nonempty string member names without dots "
                    "for read-compatible paths"
                )
            child_path = f"{path}.{key}" if path else key
            yield from _document_nodes(child, child_path, key)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}.{index}" if path else str(index)
            yield from _document_nodes(child, child_path)
        return


def _value_type(
    value: Any,
) -> Literal["object", "array", "string", "number", "boolean", "null"]:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return "number"


def _scalar_text(value: str | int | float | bool | None) -> str:
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
