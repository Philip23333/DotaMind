"""Generate PandaScore Dota 2 query capabilities from endpoint fact files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_DIRECTORY = (
    _REPOSITORY_ROOT
    / "docs"
    / "reference"
    / "pandascore-snapshots"
    / "PandaScore_endpoint_detection"
)
_OUTPUT_PATH = (
    _REPOSITORY_ROOT / "docs" / "reference" / "pandascore-generated" / "capabilities.json"
)
_GENERATED_FROM = "docs/reference/pandascore-snapshots/PandaScore_endpoint_detection"

ENDPOINT_MAP = {
    "get_dota2_leagues": {"resource": "league", "scope": "all"},
    "get_dota2_matches": {"resource": "match", "scope": "all"},
    "get_dota2_matches_past": {"resource": "match", "scope": "past"},
    "get_dota2_matches_running": {"resource": "match", "scope": "running"},
    "get_dota2_matches_upcoming": {"resource": "match", "scope": "upcoming"},
    "get_dota2_players": {"resource": "player", "scope": "all"},
    "get_dota2_series": {"resource": "serie", "scope": "all"},
    "get_dota2_series_past": {"resource": "serie", "scope": "past"},
    "get_dota2_series_running": {"resource": "serie", "scope": "running"},
    "get_dota2_series_upcoming": {"resource": "serie", "scope": "upcoming"},
    "get_dota2_series_serieidorslug_teams": {"resource": "team", "scope": "by_serie"},
    "get_dota2_teams": {"resource": "team", "scope": "all"},
    "get_dota2_tournaments": {"resource": "tournament", "scope": "all"},
    "get_dota2_tournaments_past": {"resource": "tournament", "scope": "past"},
    "get_dota2_tournaments_running": {"resource": "tournament", "scope": "running"},
    "get_dota2_tournaments_upcoming": {"resource": "tournament", "scope": "upcoming"},
}

_SIMPLE_TYPES = {"boolean", "integer", "number", "object", "string"}


def _section(text: str, heading: str, level: int) -> str:
    marker = "#" * level
    match = re.search(rf"(?m)^{re.escape(marker)} {re.escape(heading)}\s*$", text)
    if match is None:
        return ""
    next_heading = re.search(rf"(?m)^{re.escape(marker)} ", text[match.end() :])
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end]


def _table(section: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    headers = cells(lines[0])
    if not all(set(cell) <= {"-", ":"} for cell in cells(lines[1])):
        raise ValueError("Markdown table is missing its separator row")
    return [dict(zip(headers, cells(line), strict=True)) for line in lines[2:]]


def _query_section(query_parameters: str, heading: str) -> str:
    match = re.search(rf"(?m)^### {re.escape(heading)}\s*$", query_parameters)
    if match is None:
        return ""
    next_heading = re.search(r"(?m)^### ", query_parameters[match.end() :])
    end = match.end() + next_heading.start() if next_heading else len(query_parameters)
    return query_parameters[match.end() : end]


def _enum_values(raw: str) -> list[int | str] | None:
    match = re.search(r"(?:^|;)\s*enum:\s*(.+)$", raw)
    if match is None:
        return None
    values: list[int | str] = []
    for value in match.group(1).split(","):
        value = value.strip()
        values.append(int(value) if re.fullmatch(r"-?\d+", value) else value)
    return values


def _normalized_query_type(raw_type: str) -> dict[str, Any]:
    multiple = raw_type.startswith("array<") and raw_type.endswith(">")
    value_type = raw_type[6:-1].strip() if multiple else raw_type.strip()
    type_name = value_type.split(";", maxsplit=1)[0].strip()
    if value_type.startswith("one of:") or type_name not in _SIMPLE_TYPES | {"unknown"}:
        return {
            "type": "unknown",
            "multiple": multiple,
            "enum": None,
            "format": None,
            "raw_type": raw_type,
        }

    format_match = re.search(r"(?:^|;)\s*format:\s*([^;]+)$", value_type)
    result: dict[str, Any] = {
        "type": type_name,
        "multiple": multiple,
        "enum": _enum_values(value_type),
        "format": format_match.group(1).strip() if format_match else None,
    }
    if type_name == "unknown":
        result["raw_type"] = raw_type
    return result


def _path_param_type(raw_type: str) -> str:
    match = re.fullmatch(r"one of:\s*([a-z]+),\s*([a-z]+)", raw_type)
    if match is not None:
        return "|".join(match.groups())
    return raw_type


def _parse_path_params(section: str) -> dict[str, dict[str, Any]]:
    if "None documented." in section:
        return {}
    params: dict[str, dict[str, Any]] = {}
    for row in _table(section):
        name = row["name"]
        params[name] = {
            "type": _path_param_type(row["type"]),
            "required": row["required"].strip().lower() == "yes",
        }
    return params


def _parse_fields(section: str) -> dict[str, dict[str, Any]]:
    return {
        row["field"]: _normalized_query_type(row["type"])
        for row in _table(section)
    }


def _parse_sort(section: str) -> list[str | dict[str, str]]:
    sort: list[str | dict[str, str]] = []
    for row in _table(section):
        field = row["field"]
        ascending = row["ascending syntax"]
        descending = row["descending syntax"]
        if ascending == field and descending == f"-{field}":
            sort.append(field)
        else:
            sort.append({"field": field, "ascending": ascending, "descending": descending})
    return sort


def _integer(value: str) -> int | None:
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _parse_pagination(section: str) -> dict[str, Any]:
    rows = {row["parameter"]: row for row in _table(section)}
    result: dict[str, Any] = {"page": "page" in rows}
    per_page = rows.get("per_page")
    if per_page is None:
        return result

    constraints = per_page["constraints"]
    parsed_per_page = {
        "default": _integer(per_page["default"]),
        "min": _integer(re.search(r"minimum=([^;]+)", constraints).group(1))
        if re.search(r"minimum=([^;]+)", constraints)
        else None,
        "max": _integer(re.search(r"maximum=([^;]+)", constraints).group(1))
        if re.search(r"maximum=([^;]+)", constraints)
        else None,
    }
    result["per_page"] = {key: value for key, value in parsed_per_page.items() if value is not None}
    return result


def _parse_endpoint(path: Path) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    identity = re.search(r"(?m)^# ([^\s]+)\s*$", text)
    if identity is None:
        raise ValueError(f"{path}: missing endpoint identity")
    endpoint = identity.group(1)
    if endpoint not in ENDPOINT_MAP:
        raise ValueError(f"{path}: unsupported endpoint identity {endpoint!r}")

    identity_section = _section(text, "Identity", 2)
    path_match = re.search(r"(?m)^- \*\*API path:\*\* `([^`]+)`\s*$", identity_section)
    if path_match is None:
        raise ValueError(f"{path}: missing API path")

    query_parameters = _section(text, "Query Parameters", 2)
    return endpoint, {
        "path": path_match.group(1),
        "path_params": _parse_path_params(_section(text, "Path Parameters", 2)),
        "filter": _parse_fields(_query_section(query_parameters, "filter")),
        "search": _parse_fields(_query_section(query_parameters, "search")),
        "range": _parse_fields(_query_section(query_parameters, "range")),
        "sort": _parse_sort(_query_section(query_parameters, "sort")),
        "pagination": _parse_pagination(_query_section(query_parameters, "pagination")),
    }


def build_capabilities(source_directory: Path = _SOURCE_DIRECTORY) -> dict[str, Any]:
    files = sorted(path for path in source_directory.glob("*.md") if path.name != "INDEX.md")
    if len(files) != len(ENDPOINT_MAP):
        raise ValueError(f"Expected {len(ENDPOINT_MAP)} endpoint fact files, found {len(files)}")

    resources: dict[str, dict[str, dict[str, Any]]] = {}
    found_endpoints: set[str] = set()
    for path in files:
        endpoint, capability = _parse_endpoint(path)
        if endpoint in found_endpoints:
            raise ValueError(f"Duplicate endpoint identity {endpoint!r}")
        found_endpoints.add(endpoint)
        mapping = ENDPOINT_MAP[endpoint]
        scopes = resources.setdefault(mapping["resource"], {"scopes": {}})["scopes"]
        if mapping["scope"] in scopes:
            raise ValueError(
                f"Duplicate capability for ({mapping['resource']!r}, {mapping['scope']!r})"
            )
        scopes[mapping["scope"]] = capability

    missing_endpoints = set(ENDPOINT_MAP) - found_endpoints
    if missing_endpoints:
        raise ValueError(f"Missing endpoint facts: {', '.join(sorted(missing_endpoints))}")

    return {
        "schema_version": 1,
        "source": "pandascore",
        "game": "dota2",
        "generated_from": _GENERATED_FROM,
        "resources": resources,
    }


def serialize_capabilities(capabilities: dict[str, Any]) -> str:
    return json.dumps(capabilities, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    capabilities = build_capabilities()
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(serialize_capabilities(capabilities), encoding="utf-8")
    print(f"Generated {_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
