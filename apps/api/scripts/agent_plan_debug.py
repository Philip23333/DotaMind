"""Run a v2.5 ExecutionPlan from JSON and print AgentRunState."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.models import ExecutionPlan
from app.agentic.nodes import (
    answer_node,
    critic_node,
    evidence_node,
    response_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.registry import ToolExecutor
from app.agentic.state import AgentRunState
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
    state = asyncio.run(run_plan(plan, ToolExecutor(registry)))
    print(json.dumps(state.response, ensure_ascii=False, indent=2))
    return 0 if state.status == "ok" else 1


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


async def run_plan(
    plan: ExecutionPlan,
    executor: ToolExecutor | None = None,
) -> AgentRunState:
    if executor is None:
        executor = ToolExecutor(build_default_tool_registry(get_settings()))
    state = AgentRunState(query="debug plan", game="dota2", plan=plan, reason="loaded plan")
    state = validate_plan_node(state)
    if state.status != "error":
        state = await tool_executor_node(state, executor)
    state = evidence_node(state, executor.registry)
    if state.status != "error":
        state = await answer_node(state, AnswerSynthesizer())
    if state.status != "error":
        state = critic_node(state, AgenticCritic())
    return response_node(state)


if __name__ == "__main__":
    sys.exit(main())
