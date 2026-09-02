"""Bounded inspection of a manual or one session tool response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from .manuals import ManualResolver
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

    async def read(
        self,
        ref: str,
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

        if ref.startswith("manual:pandascore:"):
            if self._manuals is None:
                raise ArtifactNotFoundError(f"artifact not found: {ref}")
            if path not in (None, "content"):
                raise ArtifactPathNotFoundError(f"artifact path not found: {path!r}")
            return ArtifactReadResult(
                ref=ref,
                path=path,
                value=self._manuals.read(ref),
            )

        payload = await self._store.get(ref)
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


def _outline(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
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
]
