"""Run a v2.5 ExecutionPlan from JSON and print PlanRunResult."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agentic.models import ExecutionPlan
from app.agentic.registry import ToolExecutor
from app.agentic.runner import PlanRunner, PlanRunResult
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import get_settings


def main() -> int:
    args = parse_args()
    try:
        plan = load_plan(args)
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}, indent=2))
        return 1

    registry = build_default_tool_registry(get_settings())
    result = asyncio.run(PlanRunner(ToolExecutor(registry)).run(plan))
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "ok" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a v2.5 ExecutionPlan.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan-json", help="ExecutionPlan JSON object.")
    source.add_argument("--plan-file", help="Path to an ExecutionPlan JSON file.")
    return parser.parse_args()


def load_plan(args: argparse.Namespace) -> ExecutionPlan:
    if args.plan_file:
        raw = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    else:
        raw = json.loads(args.plan_json)
    return plan_from_raw(raw)


def plan_from_raw(raw: Any) -> ExecutionPlan:
    if not isinstance(raw, dict):
        raise ValueError("ExecutionPlan JSON must be an object")
    return ExecutionPlan.model_validate(raw)


async def run_plan(plan: ExecutionPlan) -> PlanRunResult:
    registry = build_default_tool_registry(get_settings())
    return await PlanRunner(ToolExecutor(registry)).run(plan)


if __name__ == "__main__":
    sys.exit(main())
