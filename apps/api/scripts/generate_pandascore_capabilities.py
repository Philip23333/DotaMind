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
_MANUAL_OUTPUT_DIRECTORY = (
    _REPOSITORY_ROOT / "docs" / "reference" / "pandascore-generated" / "agent-manual"
)
_GENERATED_FROM = "docs/reference/pandascore-snapshots/PandaScore_endpoint_detection"
_MANUAL_RESOURCES = ("league", "serie", "tournament", "match", "team", "player")
_LIFECYCLE_SCOPES = {"all", "past", "running", "upcoming"}
_MANUAL_HEADER = "<!--\nDO NOT EDIT.\nGenerated from PandaScore endpoint snapshots.\n-->\n"
_FIELD_OPERATORS = (
    ("filter", "Filter fields"),
    ("search", "Search fields"),
    ("range", "Range fields"),
)

_QUERY_EXAMPLES = {
    "league": {"resource": "league", "search": {"name": "The International"}},
    "serie": {"resource": "serie", "filter": {"league_id": 4106, "year": 2026}},
    "tournament": {
        "resource": "tournament",
        "filter": {"serie_id": 10828, "name": "Group Stage"},
    },
    "match": {
        "resource": "match",
        "scope": "past",
        "filter": {"tournament_id": 21698},
        "search": {"name": "Grand Final"},
    },
    "team": {"resource": "team", "search": {"name": "Team Spirit"}},
    "player": {"resource": "player", "search": {"name": "..."}},
}

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


def _normal_scopes(resource: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        scope: capability
        for scope, capability in resource["scopes"].items()
        if scope in _LIFECYCLE_SCOPES
    }


def _render_field_table(fields: dict[str, dict[str, Any]]) -> list[str]:
    if not fields:
        return ["None."]

    lines = [
        "| Field | Type | Multiple | Enum | Format |",
        "| --- | --- | --- | --- | --- |",
    ]
    for field, specification in fields.items():
        field_type = specification.get("raw_type", specification["type"])
        enum = ", ".join(str(value) for value in specification["enum"] or [])
        multiple = "yes" if specification["multiple"] else "no"
        lines.append(
            f"| {field} | `{field_type}` | {multiple} | {enum} | {specification['format'] or ''} |"
        )
    return lines


def _render_scope_fields(
    scopes: dict[str, dict[str, Any]], operator: str
) -> list[str]:
    scope_capabilities = list(scopes.values())
    first_fields = scope_capabilities[0][operator]
    if all(capability[operator] == first_fields for capability in scope_capabilities[1:]):
        return [
            "The following fields are supported by all scopes:",
            "",
            *_render_field_table(first_fields),
            "",
        ]

    lines: list[str] = []
    for scope, capability in scopes.items():
        lines.extend([f"### {scope}", ""])
        lines.extend(_render_field_table(capability[operator]))
        lines.append("")
    return lines


def _render_sort_fields(scopes: dict[str, dict[str, Any]]) -> list[str]:
    scope_capabilities = list(scopes.values())
    first_sort = scope_capabilities[0]["sort"]
    if all(capability["sort"] == first_sort for capability in scope_capabilities[1:]):
        return _render_sort_values(first_sort, "all scopes")

    lines: list[str] = []
    for scope, capability in scopes.items():
        lines.extend(_render_sort_values(capability["sort"], scope))
    return lines


def _render_sort_values(sort: list[str | dict[str, str]], scope: str) -> list[str]:
    lines = [f"### {scope}", ""]
    if not sort:
        return [*lines, "None.", ""]
    for field in sort:
        if isinstance(field, str):
            lines.append(f"- `{field}`")
        else:
            lines.append(
                "- "
                f"`{field['field']}` (ascending: `{field['ascending']}`, "
                f"descending: `{field['descending']}`)"
            )
    return [*lines, "", "Prefix a field with `-` for descending order.", ""]


def _render_special_route(capability: dict[str, Any]) -> list[str]:
    lines = [
        "### Teams by serie",
        "",
        f"Path: `{capability['path']}`",
        "",
        "Path parameters:",
        "",
    ]
    for name, specification in capability["path_params"].items():
        requirement = "required" if specification["required"] else "optional"
        lines.append(f"- `{name}`: {specification['type']}, {requirement}")
    lines.extend(["", "This route lists teams for a specific serie.", ""])
    for operator, title in _FIELD_OPERATORS:
        lines.extend([f"#### {title}", ""])
        lines.extend(_render_field_table(capability[operator]))
        lines.append("")
    lines.extend(["#### Sort fields", ""])
    if not capability["sort"]:
        lines.append("None.")
    else:
        for field in capability["sort"]:
            lines.append(f"- `{field}`" if isinstance(field, str) else f"- `{field['field']}`")
        lines.append("")
        lines.append("Prefix a field with `-` for descending order.")
    return lines


def _require_filter_fields(capabilities: dict[str, Any], resource: str, *fields: str) -> None:
    available = capabilities["resources"][resource]["scopes"]["all"]["filter"]
    missing = set(fields) - set(available)
    if missing:
        raise ValueError(
            f"{resource} manual guidance requires unavailable fields: {sorted(missing)}"
        )


def _render_limitations(capabilities: dict[str, Any], resource: str) -> list[str]:
    if resource == "tournament":
        _require_filter_fields(capabilities, resource, "serie_id")
        fields = capabilities["resources"][resource]["scopes"]["all"]["filter"]
        if "league_id" in fields or "year" in fields:
            raise ValueError("Tournament manual limitation no longer matches capabilities")
        return [
            "Tournament supports `serie_id` as a filter field.",
            "",
            "Tournament does not support `league_id` as a filter field.",
            "",
            "Tournament does not support `year` as a filter field.",
            "",
            "If those constraints are known at league or edition level, obtain the corresponding "
            "serie ID before querying tournaments by `serie_id`.",
        ]
    if resource == "serie":
        _require_filter_fields(capabilities, resource, "league_id", "year")
        return [
            "Serie supports both `league_id` and `year` filter fields, which can be used "
            "together to identify a league edition."
        ]
    if resource == "match":
        _require_filter_fields(capabilities, resource, "league_id", "serie_id", "tournament_id")
        return [
            "Matches can be narrowed using `league_id`, `serie_id`, or `tournament_id`. "
            "Use the narrowest identifier already known."
        ]
    if resource == "league":
        fields = capabilities["resources"][resource]["scopes"]["all"]["filter"]
        if "year" in fields:
            raise ValueError("League manual limitation no longer matches capabilities")
        return ["League does not support a `year` filter."]
    return ["Use only the fields listed above for the selected scope."]


def _validate_example(capabilities: dict[str, Any], resource: str, example: dict[str, Any]) -> None:
    if example["resource"] != resource:
        raise ValueError(f"Example resource mismatch for {resource}")
    resource_capabilities = capabilities["resources"][resource]
    scope = example.get("scope", "all")
    if scope not in _normal_scopes(resource_capabilities):
        raise ValueError(f"Example uses unsupported {resource} scope {scope!r}")
    scope_capability = resource_capabilities["scopes"][scope]
    for operator in ("filter", "search", "range"):
        fields = set(example.get(operator, {}))
        if not fields <= set(scope_capability[operator]):
            raise ValueError(
                f"Example uses unsupported {resource} {operator} fields: {sorted(fields)}"
            )


def _render_resource_manual(capabilities: dict[str, Any], resource: str) -> str:
    resource_capabilities = capabilities["resources"][resource]
    normal_scopes = _normal_scopes(resource_capabilities)
    if not normal_scopes:
        raise ValueError(f"{resource} has no normal query scopes")
    example = _QUERY_EXAMPLES[resource]
    _validate_example(capabilities, resource, example)

    lines = [
        _MANUAL_HEADER.rstrip(),
        "",
        f"# {resource.capitalize()}",
        "",
        "## Supported scopes",
        "",
    ]
    lines.extend(f"- `{scope}`" for scope in normal_scopes)
    for operator, title in _FIELD_OPERATORS:
        lines.extend(["", f"## {title}", ""])
        lines.extend(_render_scope_fields(normal_scopes, operator))
    lines.extend(["## Sort fields", ""])
    lines.extend(_render_sort_fields(normal_scopes))
    lines.extend(["## Special routes", ""])
    special_route = resource_capabilities["scopes"].get("by_serie")
    if special_route is None:
        lines.append("None.")
    else:
        lines.extend(_render_special_route(special_route))
    lines.extend(["", "## Query examples", "", "```json", json.dumps(example, indent=2), "```"])
    lines.extend(["", "## Important limitations", ""])
    lines.extend(_render_limitations(capabilities, resource))
    return "\n".join(lines).rstrip() + "\n"


def _render_index(capabilities: dict[str, Any]) -> str:
    lines = [
        _MANUAL_HEADER.rstrip(),
        "",
        "# PandaScore Dota 2 Query Manual",
        "",
        "Use this manual when constructing esports search queries.",
        "",
        "## Query model",
        "",
        "Supported query operators:",
        "",
        "- resource",
        "- scope",
        "- filter",
        "- search",
        "- range",
        "- sort",
        "- pagination",
        "",
        "Different resources support different fields.",
        "",
        "## Resources",
        "",
        "| Resource | Supported scopes |",
        "| --- | --- |",
    ]
    for resource in _MANUAL_RESOURCES:
        scopes = ", ".join(_normal_scopes(capabilities["resources"][resource]))
        lines.append(f"| [{resource}]({resource}.md) | {scopes} |")
    lines.extend(
        [
            "",
            "## General rules",
            "",
            "- `filter` uses exact/value filtering.",
            "- `search` uses PandaScore search semantics.",
            "- `range[field]` takes two values.",
            "- Use `-field` for descending sort.",
            "- IDs returned by previous results can be reused in later queries.",
            "- Do not assume a field supported by one resource exists on another.",
            "- When unsure, read the resource manual before querying.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_agent_manual(capabilities: dict[str, Any]) -> dict[str, str]:
    missing_resources = set(_MANUAL_RESOURCES) - set(capabilities["resources"])
    if missing_resources:
        raise ValueError(f"Manual resources are missing: {sorted(missing_resources)}")
    manual = {"INDEX.md": _render_index(capabilities)}
    manual.update(
        {
            f"{resource}.md": _render_resource_manual(capabilities, resource)
            for resource in _MANUAL_RESOURCES
        }
    )
    return manual


def write_agent_manual(
    capabilities: dict[str, Any], output_directory: Path = _MANUAL_OUTPUT_DIRECTORY
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for filename, content in render_agent_manual(capabilities).items():
        (output_directory / filename).write_text(content, encoding="utf-8")


def main() -> int:
    capabilities = build_capabilities()
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(serialize_capabilities(capabilities), encoding="utf-8")
    write_agent_manual(capabilities)
    print(f"Generated {_OUTPUT_PATH} and {_MANUAL_OUTPUT_DIRECTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
