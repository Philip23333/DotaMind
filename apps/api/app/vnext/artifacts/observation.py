"""Deterministic bounded projections for externalized tool responses."""

from __future__ import annotations

from typing import Any

from .externalize import serialized_size

MAX_MODEL_TOOL_OBSERVATION_BYTES = 8 * 1024


def build_bounded_observation(
    payload: Any,
    *,
    artifact_ref: str,
    max_bytes: int = MAX_MODEL_TOOL_OBSERVATION_BYTES,
) -> dict[str, Any]:
    """Build a small structural view while preserving paths into ``payload``."""

    if max_bytes < 1:
        raise ValueError("max_bytes must be greater than zero")

    envelope = {
        "artifact_ref": artifact_ref,
        "externalized": True,
        "value": {},
    }
    value_budget = max(0, max_bytes - serialized_size(envelope))
    projected = _project_value(payload, "", value_budget)
    envelope["value"] = projected

    if serialized_size(envelope) <= max_bytes:
        return envelope

    if isinstance(projected, dict):
        projected = _trim_root(projected, envelope, max_bytes)
        envelope["value"] = projected
    return envelope


def _project_value(value: Any, path: str, budget: int) -> Any:
    if _is_scalar(value):
        if serialized_size(value) <= budget:
            return value
        return _pointer(path, "scalar")

    if isinstance(value, list):
        return _pointer(path, "collection", count=len(value))

    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            candidate = _project_value(child, child_path, budget)
            trial = {**projected, str(key): candidate}
            if serialized_size(trial) <= budget:
                projected[str(key)] = candidate
                continue

            pointer = _pointer(
                child_path,
                _kind(child),
                count=len(child) if isinstance(child, list) else None,
            )
            trial = {**projected, str(key): pointer}
            if serialized_size(trial) <= budget:
                projected[str(key)] = pointer
            else:
                break
        return projected

    return _pointer(path, "value")


def _trim_root(
    projected: dict[str, Any],
    envelope: dict[str, Any],
    max_bytes: int,
) -> dict[str, Any]:
    trimmed = dict(projected)
    while trimmed and serialized_size({**envelope, "value": trimmed}) > max_bytes:
        trimmed.pop(next(reversed(trimmed)))
    candidate = {
        **envelope,
        "value": {**trimmed, "_truncated": True},
    }
    if serialized_size(candidate) <= max_bytes:
        trimmed["_truncated"] = True
    return trimmed


def _pointer(path: str, kind: str, *, count: int | None = None) -> dict[str, Any]:
    pointer: dict[str, Any] = {"_artifact_path": path, "kind": kind}
    if count is not None:
        pointer["count"] = count
    return pointer


def _kind(value: Any) -> str:
    if isinstance(value, list):
        return "collection"
    if isinstance(value, dict):
        return "object"
    if _is_scalar(value):
        return "scalar"
    return "value"


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


__all__ = ["MAX_MODEL_TOOL_OBSERVATION_BYTES", "build_bounded_observation"]
