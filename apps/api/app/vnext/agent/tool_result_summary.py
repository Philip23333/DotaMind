"""Compact, generic summaries for local agent trace files."""

from __future__ import annotations

from typing import Any

_MAX_ITEMS = 10


def summarize_tool_result(tool_name: str, content: Any) -> dict[str, Any] | None:
    """Summarize a serialized tool result without persisting large bodies."""

    del tool_name
    if not isinstance(content, dict):
        return {"value_kind": _value_kind(content)}
    summary: dict[str, Any] = {
        "value_kind": "object",
        "field_count": len(content),
        "field_names": sorted(content)[:_MAX_ITEMS],
        "field_names_truncated": len(content) > _MAX_ITEMS,
    }
    if "ref" in content:
        summary["ref"] = _ref_summary(content["ref"])
    if "path" in content:
        summary["path"] = content["path"]
    value = content.get("value")
    if isinstance(value, list):
        summary["value_kind"] = "list"
        summary["count"] = len(value)
    elif value is not None:
        summary["value_kind"] = _value_kind(value)
    for name in ("offset", "limit", "total", "truncated"):
        if name in content:
            summary[name] = content[name]
    return summary


def _ref_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        name: value[name]
        for name in ("id", "artifact_type", "schema_version")
        if name in value
    }


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


__all__ = ["summarize_tool_result"]
