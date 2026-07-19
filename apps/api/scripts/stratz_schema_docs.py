"""Download STRATZ GraphQL schema docs and render a focused technical excerpt.

The STRATZ GraphiQL "Docs" panel is generated from the GraphQL introspection
schema. This script downloads that official schema with the configured API
token, writes the raw JSON for later lookup, and renders a compact Markdown
reference for the hero-stat fields DotaMind currently cares about.

Run from the repository root or apps/api:

    python apps/api/scripts/stratz_schema_docs.py

Configuration is read from environment variables first, then apps/api/.env:

    DOTAMIND_STRATZ_TOKEN
    DOTAMIND_STRATZ_GRAPHQL_URL
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

DEFAULT_STRATZ_GRAPHQL_URL = "https://api.stratz.com/graphql"

INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      kind
      name
      description
      fields(includeDeprecated: true) {
        name
        description
        args {
          name
          description
          defaultValue
          type {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
                ofType {
                  kind
                  name
                  ofType { kind name }
                }
              }
            }
          }
        }
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
                ofType { kind name }
              }
            }
          }
        }
        isDeprecated
        deprecationReason
      }
      inputFields {
        name
        description
        defaultValue
        type {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
                ofType { kind name }
              }
            }
          }
        }
      }
      interfaces { kind name }
      enumValues(includeDeprecated: true) {
        name
        description
        isDeprecated
        deprecationReason
      }
      possibleTypes { kind name }
    }
    directives {
      name
      description
      locations
      args {
        name
        description
        defaultValue
        type {
          kind
          name
          ofType {
            kind
            name
            ofType { kind name }
          }
        }
      }
    }
  }
}
"""

FOCUS_FIELDS = {
    "HeroStatsQuery": ("winDay", "laneOutcome", "heroVsHeroMatchup", "stats"),
}
FOCUS_ENUMS = (
    "RankBracket",
    "RankBracketBasicEnum",
    "MatchPlayerPositionType",
    "GameModeEnumType",
    "BasicRegionType",
    "FilterHeroWinRequestGroupBy",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download STRATZ GraphQL introspection docs."
    )
    parser.add_argument(
        "--json-out",
        default="docs/technical/stratz_schema_introspection.json",
        help="Raw introspection JSON output path.",
    )
    parser.add_argument(
        "--md-out",
        default="docs/technical/stratz_schema_reference.md",
        help="Focused Markdown reference output path.",
    )
    parser.add_argument(
        "--skip-json",
        action="store_true",
        help="Render Markdown without rewriting the JSON file when it already exists.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    json_path = (repo_root / args.json_out).resolve()
    md_path = (repo_root / args.md_out).resolve()

    json_action = "read"
    if args.skip_json:
        if not json_path.exists():
            raise SystemExit(f"--skip-json requested but file is missing: {json_path}")
        schema = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        url, token = _load_stratz_config(repo_root)
        schema = _download_schema(url, token)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        json_action = "wrote"

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(schema, json_path, md_path), encoding="utf-8")

    print(f"{json_action} {json_path}")
    print(f"wrote {md_path}")
    return 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_stratz_config(repo_root: Path) -> tuple[str, str]:
    env_values = _read_env_file(repo_root / "apps" / "api" / ".env")
    url = (
        os.environ.get("DOTAMIND_STRATZ_GRAPHQL_URL")
        or env_values.get("DOTAMIND_STRATZ_GRAPHQL_URL")
        or DEFAULT_STRATZ_GRAPHQL_URL
    )
    token = os.environ.get("DOTAMIND_STRATZ_TOKEN") or env_values.get(
        "DOTAMIND_STRATZ_TOKEN",
        "",
    )
    if not token:
        raise SystemExit(
            "DOTAMIND_STRATZ_TOKEN is required in the environment or apps/api/.env"
        )
    return url, token


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _download_schema(url: str, token: str) -> dict[str, Any]:
    payload = {
        "operationName": "IntrospectionQuery",
        "query": INTROSPECTION_QUERY,
        "variables": {},
    }
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # STRATZ official API docs ask clients to include this user agent.
            "User-Agent": "STRATZ_API",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"STRATZ introspection failed with HTTP {exc.code}: {body[:500]}"
        ) from exc
    data = json.loads(body.decode("utf-8"))
    errors = data.get("errors")
    if errors:
        raise SystemExit("STRATZ introspection returned errors: " + json.dumps(errors))
    if not isinstance(data.get("data", {}).get("__schema"), dict):
        raise SystemExit("STRATZ introspection response did not include data.__schema")
    return data


def _render_markdown(schema: dict[str, Any], json_path: Path, md_path: Path) -> str:
    type_map = _type_map(schema)
    rel_json = _relative_path(json_path, md_path.parent)
    lines = [
        "# STRATZ GraphQL Schema Reference",
        "",
        "> Generated from STRATZ official GraphQL introspection. Re-run",
        "> `python apps/api/scripts/stratz_schema_docs.py` to refresh.",
        "",
        f"Raw schema JSON: `{rel_json}`",
        "",
        "## Root Types",
        "",
    ]
    root = schema["data"]["__schema"]
    for key, label in (
        ("queryType", "query"),
        ("mutationType", "mutation"),
        ("subscriptionType", "subscription"),
    ):
        node = root.get(key)
        if node:
            lines.append(f"- {label}: `{node.get('name')}`")
    lines.extend(
        [
            "",
            "## Focus: HeroStatsQuery",
            "",
            "These fields are the authoritative schema source for current STRATZ",
            "tooling decisions around weekly lane data and daily hero trends.",
            "",
            "Implementation notes:",
            "",
            "- `HeroStatsQuery.winDay` is the official day-grain source for",
            "  hero trend charts. Compute win rate as `winCount / matchCount`.",
            "- `HeroStatsQuery.laneOutcome`, `heroVsHeroMatchup`, and `stats`",
            "  use provider week epochs (`week: Long`) and should remain modeled",
            "  as weekly buckets in DotaMind.",
            "- The schema description for `week` says null gives the current week;",
            "  DotaMind's live probe on 2026-07-03 found null matched the latest",
            "  completed week. Treat the schema as the field contract, and",
            "  `docs/design/tools/time_patch_filtering.md` as the empirical behavior",
            "  record for null-week semantics.",
            "",
        ]
    )

    for type_name, fields in FOCUS_FIELDS.items():
        type_def = type_map.get(type_name)
        if not type_def:
            lines.append(f"### `{type_name}`")
            lines.append("")
            lines.append("_Type not found in the downloaded schema._")
            lines.append("")
            continue
        field_map = {field["name"]: field for field in type_def.get("fields") or []}
        for field_name in fields:
            field = field_map.get(field_name)
            if not field:
                lines.append(f"### `{type_name}.{field_name}`")
                lines.append("")
                lines.append("_Field not found in the downloaded schema._")
                lines.append("")
                continue
            lines.extend(_render_field(type_name, field, type_map))

    lines.extend(["## Relevant Enums", ""])
    for enum_name in FOCUS_ENUMS:
        enum_def = type_map.get(enum_name)
        if not enum_def:
            continue
        values = enum_def.get("enumValues") or []
        lines.append(f"### `{enum_name}`")
        lines.append("")
        if enum_def.get("description"):
            lines.append(_one_line(enum_def["description"]))
            lines.append("")
        if values:
            lines.extend(f"- `{value['name']}`" for value in values)
        else:
            lines.append("_No enum values in introspection response._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_field(
    parent_type: str,
    field: dict[str, Any],
    type_map: dict[str, dict[str, Any]],
) -> list[str]:
    type_text = _format_type(field["type"])
    return_type_name = _named_type(field["type"])
    lines = [
        f"### `{parent_type}.{field['name']}`",
        "",
        f"Type: `{type_text}`",
        "",
    ]
    if field.get("description"):
        lines.append(_one_line(field["description"]))
        lines.append("")
    args = field.get("args") or []
    if args:
        lines.append("Arguments:")
        lines.append("")
        for arg in args:
            description = _one_line(arg.get("description") or "")
            default = (
                f" Default: `{arg['defaultValue']}`."
                if arg.get("defaultValue") is not None
                else ""
            )
            suffix = f" - {description}{default}" if description or default else ""
            lines.append(f"- `{arg['name']}`: `{_format_type(arg['type'])}`{suffix}")
        lines.append("")
    else:
        lines.append("Arguments: none")
        lines.append("")

    return_type = type_map.get(return_type_name or "")
    return_fields = return_type.get("fields") if return_type else None
    if return_fields:
        lines.append(f"Return fields on `{return_type_name}`:")
        lines.append("")
        for item in return_fields:
            lines.append(f"- `{item['name']}`: `{_format_type(item['type'])}`")
        lines.append("")
    return lines


def _type_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["name"]: item
        for item in schema["data"]["__schema"]["types"]
        if item.get("name")
    }


def _format_type(node: dict[str, Any]) -> str:
    kind = node.get("kind")
    name = node.get("name")
    of_type = node.get("ofType")
    if kind == "NON_NULL" and of_type:
        return _format_type(of_type) + "!"
    if kind == "LIST" and of_type:
        return "[" + _format_type(of_type) + "]"
    return str(name or kind or "unknown")


def _named_type(node: dict[str, Any]) -> str | None:
    name = node.get("name")
    if name:
        return str(name)
    of_type = node.get("ofType")
    if isinstance(of_type, dict):
        return _named_type(of_type)
    return None


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _relative_path(path: Path, start: Path) -> str:
    try:
        return path.relative_to(start).as_posix()
    except ValueError:
        return os.path.relpath(path, start).replace(os.sep, "/")


if __name__ == "__main__":
    raise SystemExit(main())
