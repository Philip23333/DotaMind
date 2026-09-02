"""Bounded model observations for complete PandaScore search responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.vnext.artifacts import (
    ArtifactRef,
    ArtifactStore,
    EsportsSearchResultArtifact,
    esports_search_result_artifact_ref,
)
from app.vnext.providers.pandascore.query import PandaScoreNativeResult

if TYPE_CHECKING:
    from .esports import EsportsSearchInput

INLINE_RESULT_MAX_BYTES = 12 * 1024
MAX_PREVIEW_BYTES = 12 * 1024
MAX_PREVIEW_ROWS = 10
MAX_PREVIEW_ROW_BYTES = 3 * 1024
MAX_INLINE_COLLECTION_ITEMS = 3
MAX_INLINE_NESTED_BYTES = 1024
MAX_PREVIEW_DEPTH = 2
MAX_INLINE_STRING_BYTES = 1024


class EsportsSearchArtifactError(RuntimeError):
    """A complete large search response could not be made recoverable."""

    def __init__(self, *, resource: str, scope: str) -> None:
        super().__init__("esports search artifact could not be stored")
        self.details = {"source": "pandascore", "resource": resource, "scope": scope}


@dataclass(frozen=True, slots=True)
class EsportsSearchObservation:
    resource: str
    scope: str
    rows: list[dict[str, Any]]
    has_more: bool | None
    truncated: bool
    artifact_ref: ArtifactRef | None
    total_rows: int | None


class EsportsSearchObservationBuilder:
    """Persist oversized source responses and project a generic bounded preview."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._artifact_store = artifact_store

    async def build(
        self,
        result: PandaScoreNativeResult,
        query: EsportsSearchInput,
    ) -> EsportsSearchObservation:
        result_payload = {
            "resource": result.resource,
            "scope": result.scope,
            "rows": result.rows,
            "has_more": result.has_more,
        }
        if _serialized_size(result_payload) <= INLINE_RESULT_MAX_BYTES:
            return EsportsSearchObservation(
                resource=result.resource,
                scope=result.scope,
                rows=result.rows,
                has_more=result.has_more,
                truncated=False,
                artifact_ref=None,
                total_rows=None,
            )

        query_payload = query.model_dump(mode="json")
        ref = esports_search_result_artifact_ref(query_payload)
        artifact = EsportsSearchResultArtifact(
            fetched_at=result.fetched_at,
            query=query_payload,
            result=result_payload,
        )
        try:
            await self._artifact_store.put(ref, artifact)
        except Exception as exc:
            raise EsportsSearchArtifactError(
                resource=result.resource,
                scope=result.scope,
            ) from exc

        return EsportsSearchObservation(
            resource=result.resource,
            scope=result.scope,
            rows=_build_rows_preview(
                result.rows,
                resource=result.resource,
                scope=result.scope,
                has_more=result.has_more,
                artifact_ref=ref,
            ),
            has_more=result.has_more,
            truncated=True,
            artifact_ref=ref,
            total_rows=len(result.rows),
        )


def _build_rows_preview(
    rows: list[dict[str, Any]],
    *,
    resource: str,
    scope: str,
    has_more: bool | None,
    artifact_ref: ArtifactRef,
) -> list[dict[str, Any]]:
    preview_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:MAX_PREVIEW_ROWS]):
        preview = _build_preview(row, f"result.rows.{index}", depth=0)
        assert isinstance(preview, dict)
        candidate = [*preview_rows, preview]
        if _serialized_size(
            {
                "resource": resource,
                "scope": scope,
                "rows": candidate,
                "has_more": has_more,
                "truncated": True,
                "total_rows": len(rows),
                "artifact_ref": artifact_ref.model_dump(mode="json"),
            }
        ) > MAX_PREVIEW_BYTES:
            break
        preview_rows.append(preview)
    return preview_rows


def _build_preview(value: Any, path: str, *, depth: int) -> Any:
    if _is_scalar(value):
        return _bounded_scalar(value)
    if isinstance(value, list):
        if (
            depth < MAX_PREVIEW_DEPTH
            and len(value) <= MAX_INLINE_COLLECTION_ITEMS
            and all(_is_scalar(item) for item in value)
            and _serialized_size(value) <= MAX_INLINE_NESTED_BYTES
        ):
            return [_bounded_scalar(item) for item in value]
        return {"_artifact_path": path, "_count": len(value)}
    if isinstance(value, dict):
        if depth >= MAX_PREVIEW_DEPTH or (
            depth > 0 and _serialized_size(value) > MAX_INLINE_NESTED_BYTES
        ):
            return {"_artifact_path": path}
        preview = {
            key: _build_preview(child, f"{path}.{key}", depth=depth + 1)
            for key, child in _ordered_items(value)
        }
        mapping_budget = MAX_PREVIEW_ROW_BYTES if depth == 0 else MAX_INLINE_NESTED_BYTES
        return _bound_mapping(preview, mapping_budget)
    return {"_artifact_path": path}


def _ordered_items(value: dict[str, Any]) -> list[tuple[str, Any]]:
    items = list(value.items())
    return [item for item in items if _is_scalar(item[1])] + [
        item for item in items if not _is_scalar(item[1])
    ]


def _bound_mapping(value: dict[str, Any], budget: int) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key, child in _ordered_items(value):
        candidate = {**bounded, key: child}
        if _serialized_size(candidate) > budget:
            break
        bounded[key] = child
    return bounded


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _bounded_scalar(value: Any) -> Any:
    if not isinstance(value, str) or len(value.encode("utf-8")) <= MAX_INLINE_STRING_BYTES:
        return value
    truncated = value.encode("utf-8")[:MAX_INLINE_STRING_BYTES].decode("utf-8", errors="ignore")
    return truncated + "…"


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    )


__all__ = [
    "EsportsSearchArtifactError",
    "EsportsSearchObservation",
    "EsportsSearchObservationBuilder",
    "INLINE_RESULT_MAX_BYTES",
    "MAX_INLINE_COLLECTION_ITEMS",
    "MAX_PREVIEW_BYTES",
    "MAX_PREVIEW_DEPTH",
    "MAX_PREVIEW_ROWS",
]
