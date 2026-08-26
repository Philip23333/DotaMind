"""Compact, business-level summaries for local agent trace files."""

from __future__ import annotations

from typing import Any

_MAX_CANDIDATES = 10


def summarize_tool_result(tool_name: str, content: Any) -> dict[str, Any] | None:
    """Summarize a serialized tool result without persisting large result bodies."""

    if not isinstance(content, dict):
        return {"value_kind": _value_kind(content)}
    if tool_name == "competitions.search":
        return _search_summary(content, "candidates", _competition_summary)
    if tool_name == "competitions.list_matches":
        summary = _search_summary(content, "matches", _match_summary)
        competition = content.get("competition")
        if isinstance(competition, dict):
            summary["competition"] = _competition_summary(competition)
        return summary
    if tool_name == "matches.search":
        return _search_summary(content, "candidates", _match_summary)
    if tool_name == "matches.get_detail":
        return _match_detail_summary(content)
    if tool_name == "artifact.search":
        return _artifact_search_summary(content)
    if tool_name == "artifact.read":
        return _artifact_read_summary(content)
    return _generic_summary(content)


def _search_summary(
    content: dict[str, Any],
    entries_key: str,
    summarize_entry,
) -> dict[str, Any]:
    entries = content.get(entries_key)
    normalized_entries = entries if isinstance(entries, list) else []
    return {
        **_present_fields(content, "status", "query", "year", "time_scope", "teams"),
        "candidate_count": content.get("candidate_count", len(normalized_entries)),
        entries_key: [
            summarize_entry(entry)
            for entry in normalized_entries[:_MAX_CANDIDATES]
            if isinstance(entry, dict)
        ],
        "candidates_truncated": len(normalized_entries) > _MAX_CANDIDATES,
    }


def _competition_summary(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **_reference_field(value, "ref"),
        **_present_fields(
            value,
            "name",
            "year",
            "status",
            "starts_at",
            "ends_at",
            "tier",
            "region",
        ),
    }


def _match_summary(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result")
    winner = result.get("winner") if isinstance(result, dict) else None
    return {
        **_reference_field(value, "ref"),
        **_present_fields(
            value,
            "name",
            "status",
            "scheduled_at",
            "started_at",
            "ended_at",
            "games_count",
        ),
        **_reference_field({"winner": winner}, "winner"),
    }


def _match_detail_summary(content: dict[str, Any]) -> dict[str, Any]:
    games = content.get("games")
    normalized_games = games if isinstance(games, list) else []
    summary: dict[str, Any] = {
        **_present_fields(content, "status"),
        "game_count": len(normalized_games),
        "games": [
            {
                **_reference_field(game, "ref"),
                **_present_fields(
                    game,
                    "position",
                    "status",
                    "valve_match_id",
                    "detail_status",
                    "radiant_score",
                    "dire_score",
                ),
                **_reference_field(game, "winner"),
            }
            for game in normalized_games[:_MAX_CANDIDATES]
            if isinstance(game, dict)
        ],
        "games_truncated": len(normalized_games) > _MAX_CANDIDATES,
    }
    match = content.get("match")
    if isinstance(match, dict):
        summary["match"] = _match_summary(match)
    resolution = content.get("resolution")
    if isinstance(resolution, dict):
        summary["resolution"] = _present_fields(
            resolution,
            "status",
            "candidate_count",
            "warnings",
        )
    return summary


def _artifact_search_summary(content: dict[str, Any]) -> dict[str, Any]:
    refs = content.get("refs")
    normalized_refs = refs if isinstance(refs, list) else []
    missing_ids = content.get("missing_valve_match_ids")
    normalized_missing_ids = missing_ids if isinstance(missing_ids, list) else []
    return {
        "ref_count": len(normalized_refs),
        "refs": [
            _artifact_ref_summary(ref)
            for ref in normalized_refs[:_MAX_CANDIDATES]
            if isinstance(ref, dict)
        ],
        "refs_truncated": len(normalized_refs) > _MAX_CANDIDATES,
        "missing_valve_match_ids": normalized_missing_ids[:_MAX_CANDIDATES],
        "missing_ids_truncated": len(normalized_missing_ids) > _MAX_CANDIDATES,
    }


def _artifact_read_summary(content: dict[str, Any]) -> dict[str, Any]:
    value = content.get("value")
    summary: dict[str, Any] = {
        "ref": _artifact_ref_summary(content.get("ref")),
        **_present_fields(content, "path", "offset", "limit", "total", "truncated"),
        "value_kind": _value_kind(value),
    }
    if isinstance(value, list):
        summary["count"] = len(value)
    elif isinstance(value, dict):
        summary["field_count"] = len(value)
        summary["field_names"] = sorted(value)[:_MAX_CANDIDATES]
        summary["field_names_truncated"] = len(value) > _MAX_CANDIDATES
    return summary


def _generic_summary(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "value_kind": "object",
        "field_count": len(content),
        "field_names": sorted(content)[:_MAX_CANDIDATES],
        "field_names_truncated": len(content) > _MAX_CANDIDATES,
    }


def _artifact_ref_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _present_fields(value, "id", "artifact_type", "schema_version")


def _reference_field(value: dict[str, Any], name: str) -> dict[str, Any]:
    reference = value.get(name)
    if not isinstance(reference, dict):
        return {}
    reference_value = reference.get("value")
    return {name: reference_value} if isinstance(reference_value, str) else {}


def _present_fields(value: dict[str, Any], *names: str) -> dict[str, Any]:
    return {name: value[name] for name in names if name in value}


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
