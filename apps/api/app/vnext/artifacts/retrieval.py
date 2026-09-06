"""Bounded inspection of a manual or one session tool response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from .externalize import serialized_size
from .manuals import ManualResolver
from .observation import MAX_MODEL_TOOL_OBSERVATION_BYTES
from .store import ArtifactNotFoundError, SessionArtifactStore


class ArtifactPathNotFoundError(LookupError):
    """Raised when a canonical artifact path cannot be traversed."""


class ArtifactReadValidationError(ValueError):
    """Raised when a read request violates bounded retrieval rules."""


class ArtifactReadResult(BaseModel):
    """A serialized outline or bounded value from one referenced document."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    path: str | None
    value: Any
    offset: int | None = None
    limit: int | None = None
    total: int | None = None
    truncated: bool = False


class ArtifactReader:
    """Read a manual or a temporary tool response by exact opaque reference."""

    MAX_LIMIT = 100

    def __init__(
        self,
        store: SessionArtifactStore,
        manuals: ManualResolver | None = None,
    ) -> None:
        self._store = store
        self._manuals = manuals

    async def outline(self, ref: str) -> ArtifactReadResult:
        """Return a structural root view without reading a selected path."""

        if ref.startswith("manual:"):
            self._manual_content(ref)
            result = ArtifactReadResult(
                ref=ref,
                path=None,
                value={"paths": [{"path": "content", "kind": "text"}]},
            )
            return _fit_result_to_model_budget(result)
        result = ArtifactReadResult(ref=ref, path=None, value=_outline(await self._store.get(ref)))
        return _fit_result_to_model_budget(result)

    async def read(
        self,
        ref: str,
        path: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ArtifactReadResult:
        """Read one explicit path, slicing only when its final value is a list."""

        payload: Any
        if ref.startswith("manual:"):
            payload = {"content": self._manual_content(ref)}
        else:
            payload = await self._store.get(ref)
        value = _resolve_path(payload, path)
        pagination_requested = offset is not None or limit is not None
        if isinstance(value, list):
            resolved_offset = 0 if offset is None else offset
            resolved_limit = 50 if limit is None else limit
            _validate_pagination(resolved_offset, resolved_limit)
            end = resolved_offset + resolved_limit
            result = ArtifactReadResult(
                ref=ref,
                path=path,
                value=value[resolved_offset:end],
                offset=resolved_offset,
                limit=resolved_limit,
                total=len(value),
                truncated=end < len(value),
            )
            return _fit_list_result_to_model_budget(result)
        if pagination_requested:
            raise ArtifactReadValidationError(
                "pagination is only valid when the final value is a list"
            )
        return _fit_result_to_model_budget(ArtifactReadResult(ref=ref, path=path, value=value))

    def _manual_content(self, ref: str) -> str:
        if self._manuals is None:
            raise ArtifactNotFoundError(f"artifact not found: {ref}")
        return self._manuals.read(ref)


def _validate_pagination(offset: int, limit: int) -> None:
    if offset < 0:
        raise ArtifactReadValidationError("offset must be non-negative")
    if limit < 1 or limit > ArtifactReader.MAX_LIMIT:
        raise ArtifactReadValidationError(
            f"limit must be between 1 and {ArtifactReader.MAX_LIMIT}"
        )


def _fit_result_to_model_budget(result: ArtifactReadResult) -> ArtifactReadResult:
    """Ensure a successful artifact result fits the model observation budget."""

    if serialized_size(result.model_dump(mode="json")) <= MAX_MODEL_TOOL_OBSERVATION_BYTES:
        return result
    raise ArtifactReadValidationError(
        "selected artifact value exceeds the model observation budget; "
        "read a narrower nested path"
    )


def _fit_list_result_to_model_budget(result: ArtifactReadResult) -> ArtifactReadResult:
    """Drop only trailing complete list items until the result fits the budget."""

    if serialized_size(result.model_dump(mode="json")) <= MAX_MODEL_TOOL_OBSERVATION_BYTES:
        return result

    empty_result = result.model_copy(update={"value": [], "truncated": True})
    if serialized_size(empty_result.model_dump(mode="json")) > MAX_MODEL_TOOL_OBSERVATION_BYTES:
        return _fit_result_to_model_budget(empty_result)

    candidate = list(result.value)
    while candidate:
        fitted = result.model_copy(update={"value": candidate, "truncated": True})
        if serialized_size(fitted.model_dump(mode="json")) <= MAX_MODEL_TOOL_OBSERVATION_BYTES:
            return fitted
        candidate.pop()

    raise ArtifactReadValidationError(
        "selected artifact item exceeds the model observation budget; "
        "read a narrower nested path"
    )


def _outline(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    outline: dict[str, Any] = {}
    paths: list[dict[str, Any]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            paths.append({"path": key, "kind": "object"})
        elif isinstance(value, list):
            paths.append({"path": key, "kind": "collection", "count": len(value)})
        else:
            outline[key] = value
    outline["paths"] = paths
    return outline


def _resolve_path(payload: Any, path: str) -> Any:
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
]
