import argparse
import json

import pytest

from app.agentic.models import ExecutionPlan
from scripts.agent_plan_debug import load_plan, plan_from_raw


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
