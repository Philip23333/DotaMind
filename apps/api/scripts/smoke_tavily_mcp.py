"""Opt-in, one-request Tavily MCP smoke check; dry by default."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.vnext.composition import (
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
    initialize_vnext_services,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.json_schema import compile_object_json_schema

_QUERY = "site:dota2.com The International 2026 Dota 2 official information"


def _bounded_search_arguments(schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("discovered search schema has no properties")
    query_name = next((name for name in ("query", "search_query") if name in properties), None)
    if query_name is None:
        raise ValueError("discovered search schema has no supported query field")
    arguments: dict[str, Any] = {query_name: _QUERY}

    result_limit = properties.get("max_results")
    if not isinstance(result_limit, Mapping):
        raise ValueError("discovered search schema has no explicit max_results bound")
    maximum = result_limit.get("maximum", 5)
    minimum = result_limit.get("minimum", 1)
    if not isinstance(maximum, int) or not isinstance(minimum, int) or minimum > 5:
        raise ValueError("discovered search schema has no safe result limit")
    arguments["max_results"] = min(3, maximum)
    arguments["max_results"] = max(minimum, arguments["max_results"])

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ValueError("discovered search schema has invalid required fields")
    for name in required:
        if name in arguments:
            continue
        definition = properties.get(name)
        if isinstance(definition, Mapping) and "default" in definition:
            arguments[name] = definition["default"]
        else:
            raise ValueError("discovered search schema requires an unsupported argument")

    validator = compile_object_json_schema(schema)
    if list(validator.iter_errors(arguments)):
        raise ValueError("bounded smoke arguments do not match the discovered schema")
    return arguments


def _find_source_urls(value: Any) -> list[str]:
    found: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key in {"url", "href"} and isinstance(nested, str):
                    if nested.startswith(("https://", "http://")):
                        found.append(nested)
                else:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return list(dict.fromkeys(found))[:10]


def _redact_url(url: str, api_key: str) -> str:
    parsed = urlsplit(url)
    sensitive_names = {"key", "api_key", "apikey", "token", "authorization", "tavilyapikey"}
    query = [
        (name, "[redacted]" if name.lower() in sensitive_names or value == api_key else value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


async def _run_smoke(settings: VNextSettings) -> dict[str, Any]:
    services = build_vnext_services(settings)
    await initialize_vnext_services(settings, services)
    if services.tavily_web_search is None:
        raise RuntimeError("Tavily web search is unavailable after MCP discovery")

    registry = build_vnext_registry(services, settings=settings)
    schema = next(tool.input_schema for tool in registry.schemas() if tool.name == "web.search")
    arguments = _bounded_search_arguments(schema)
    started_at = time.monotonic()
    result = await registry.execute(
        ToolCall(id="tavily-smoke", name="web.search", arguments=arguments)
    )
    elapsed = time.monotonic() - started_at
    if result.status != "ok":
        error_code = result.error.code if result.error is not None else "provider_error"
        raise RuntimeError(f"web.search failed: {error_code}")
    urls = [_redact_url(url, settings.tavily_api_key) for url in _find_source_urls(result.content)]
    return {
        "status": "ok",
        "operation": "discover_and_one_search",
        "source_urls": urls,
        "duration_seconds": round(elapsed, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform one Tavily MCP discovery and bounded web search",
    )
    args = parser.parse_args()
    if not args.execute:
        print("Dry run only; no MCP request was made. Pass --execute to opt in.")
        return 0

    settings = VNextSettings.from_env()
    if not settings.tavily_mcp_enabled or not settings.tavily_api_key.strip():
        print(json.dumps({"status": "unavailable", "reason": "configuration"}))
        return 1

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_smoke(settings),
                timeout=settings.tavily_mcp_timeout_seconds * 2 + 1,
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
