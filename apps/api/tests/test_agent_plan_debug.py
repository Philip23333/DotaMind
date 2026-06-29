import argparse
import asyncio
import json

import pytest
from pydantic import BaseModel

from app.agentic.models import ExecutionPlan
from app.agentic.registry import ToolDefinition, ToolExecutor, ToolRegistry
from scripts.agent_plan_debug import load_plan, plan_from_raw, run_plan


def test_plan_from_raw_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        plan_from_raw([])


def test_load_plan_from_json() -> None:
    raw = {
        "intent": "debug",
        "goal": "Run a debug plan.",
        "output_contract": "tool_results",
        "tool_calls": [],
    }
    plan = load_plan(
        argparse.Namespace(plan_json=json.dumps(raw), plan_file=None)
    )

    assert isinstance(plan, ExecutionPlan)
    assert plan.intent == "debug"


def test_load_plan_from_file(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "intent": "debug",
                "goal": "Run a debug plan.",
                "output_contract": "tool_results",
                "tool_calls": [],
            }
        ),
        encoding="utf-8",
    )

    plan = load_plan(argparse.Namespace(plan_json=None, plan_file=str(path)))

    assert plan.intent == "debug"


def test_run_plan_builds_response_with_registry_evidence() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.utility",
            description="Utility tool without evidence.",
            input_model=DebugInput,
            handler=lambda args: {"value": args.value},
        )
    )
    plan = ExecutionPlan(
        intent="debug",
        goal="Run a utility tool.",
        output_contract="tool_results",
        tool_calls=[
            {
                "id": "utility",
                "tool": "debug.utility",
                "args": {"value": 1},
            }
        ],
    )

    state = asyncio.run(run_plan(plan, ToolExecutor(registry)))

    assert state.response
    assert state.response["status"] == "ok"
    assert state.evidence_graph
    assert state.evidence_graph.tool_results[0].tool == "debug.utility"


class DebugInput(BaseModel):
    value: int
