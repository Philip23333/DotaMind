from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import (
    TaskPlanInput,
    register_task_plan_tool,
)


def _registry(coordinator: TaskStateCoordinator) -> ToolRegistry:
    registry = ToolRegistry()
    register_task_plan_tool(registry, coordinator)
    return registry


def test_plan_input_schema_has_only_items() -> None:
    schema = TaskPlanInput.model_json_schema()
    assert set(schema["properties"]) == {"items"}
    with pytest.raises(ValidationError):
        TaskPlanInput.model_validate({"items": [{"key": "a", "objective": "A"}]})


def test_plan_tool_creates_plan_and_returns_compact_result() -> None:
    coordinator = TaskStateCoordinator()
    registry = _registry(coordinator)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="plan-call",
                name="task.plan",
                arguments={
                    "items": [
                        {"key": "2025", "objective": "Collect 2025"},
                        {"key": "2026", "objective": "Collect 2026"},
                    ]
                },
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {"item_count": 2, "current_key": "2025"}
    definition = registry.get("task.plan")
    assert definition.parallel_safe is False
    assert definition.read_only is False
    assert definition.externalize_result is False


def test_plan_tool_rejects_second_plan_without_mutating_first() -> None:
    coordinator = TaskStateCoordinator()
    registry = _registry(coordinator)
    first = {
        "items": [
            {"key": "a", "objective": "A"},
            {"key": "b", "objective": "B"},
        ]
    }
    asyncio.run(
        registry.execute(ToolCall(id="first", name="task.plan", arguments=first))
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="second",
                name="task.plan",
                arguments={
                    "items": [
                        {"key": "c", "objective": "C"},
                        {"key": "d", "objective": "D"},
                    ]
                },
            )
        )
    )

    assert result.status == "error"
    assert coordinator.plan_snapshot().current_key == "a"  # type: ignore[union-attr]
