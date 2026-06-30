"""Run one registered v2.5 tool call from the command line."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.agentic.models import ToolCall
from app.agentic.registry import ToolExecutor
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import get_settings


def main() -> int:
    args = parse_args()
    call = ToolCall(id="debug-1", tool=args.tool, args=parse_tool_args(args))
    registry = build_default_tool_registry(get_settings())
    result = asyncio.run(ToolExecutor(registry).execute(call))
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "ok" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a registered v2.5 tool call.")
    parser.add_argument("--tool", required=True, help="Registered tool name.")
    parser.add_argument("--query", help="Hero name or alias for resolve_hero.")
    parser.add_argument("--hero-id", type=int, help="Dota hero id for STRATZ hero tools.")
    parser.add_argument("--take", type=int, help="Maximum rows per STRATZ matchup side.")
    parser.add_argument("--args-json", help="Raw JSON object with tool args.")
    return parser.parse_args()


def parse_tool_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.args_json:
        raw = json.loads(args.args_json)
        if not isinstance(raw, dict):
            raise ValueError("--args-json must be a JSON object")
        return raw

    tool_args: dict[str, Any] = {}
    if args.query is not None:
        tool_args["query"] = args.query
    if args.hero_id is not None:
        tool_args["hero_id"] = args.hero_id
    if args.take is not None:
        tool_args["take"] = args.take
    return tool_args


if __name__ == "__main__":
    raise SystemExit(main())
