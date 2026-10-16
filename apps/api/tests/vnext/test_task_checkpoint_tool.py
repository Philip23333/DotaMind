from __future__ import annotations

import asyncio

import pytest

from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.llm.protocol import AssistantMessage, ToolCall, ToolResultMessage
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import TaskCheckpointInput, register_task_checkpoint_tool


def _registry(coordinator):
    registry = ToolRegistry()
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def _observe(coordinator, call_id, task_key, content=None):
    call = ToolCall(id=call_id, name="esports.game.resolve", arguments={})
    result = ToolResultMessage(
        tool_call_id=call_id,
        content=content if content is not None else {"status": "unresolved"},
    )
    coordinator.record_tool_result(call, result, task_key=task_key)
    return [AssistantMessage(tool_calls=[call]), result]


def _checkpoint(registry, key, **extra):
    return asyncio.run(
        registry.execute(
            ToolCall(
                id="save-" + key,
                name="task.checkpoint",
                arguments={"key": key, "value": {"result": "unresolved"}, **extra},
            )
        )
    )


def test_schema_has_only_key_and_value_and_rejects_old_source_input():
    assert set(TaskCheckpointInput.model_json_schema()["properties"]) == {"key", "value"}
    coordinator = TaskStateCoordinator()
    result = _checkpoint(_registry(coordinator), "A", source_tool_call_ids=["invented"])
    assert result.error.code == "invalid_arguments"


def test_externalized_unresolved_results_are_automatically_collected():
    coordinator = TaskStateCoordinator()
    coordinator.create_plan([{"key": "A", "objective": "A"}, {"key": "B", "objective": "B"}])
    messages = (
        _observe(
            coordinator,
            "one",
            "A",
            {
                "externalized": True,
                "artifact_ref": "artifact:one",
                "value": {"status": "unresolved", "details": {"_artifact_path": "details"}},
            },
        )
        + _observe(coordinator, "two", "A")
        + _observe(coordinator, "future", "B")
    )
    coordinator.refresh(messages)
    registry = _registry(coordinator)
    result = _checkpoint(registry, "A")
    assert result.status == "ok"
    assert result.content["source_count"] == 2
    assert "accepted_source_tool_call_ids" not in result.content
    assert coordinator.store.get("A").source_tool_call_ids == ("one", "two")
    coordinator.refresh(messages)
    assert _checkpoint(registry, "B").status == "ok"
    assert coordinator.store.get("B").source_tool_call_ids == ("future",)
    assert coordinator.plan.current_key is None
    assert len(messages) == 6


def test_no_eligible_observations_fails_without_consuming_other_task():
    coordinator = TaskStateCoordinator()
    coordinator.create_plan([{"key": "A", "objective": "A"}, {"key": "B", "objective": "B"}])
    coordinator.refresh(_observe(coordinator, "future", "B"))
    before = coordinator.source_owners_snapshot()
    result = _checkpoint(_registry(coordinator), "A")
    assert result.error.code == "invalid_checkpoint_source"
    assert coordinator.store.snapshot() == {}
    assert coordinator.plan.current_key == "A"
    assert coordinator.source_owners_snapshot() == before


@pytest.mark.parametrize("extra", [{"key": ""}, {"value": {}}, {"value": []}])
def test_invalid_arguments_are_rejected(extra):
    coordinator = TaskStateCoordinator()
    args = {"key": "A", "value": {"fact": 1}, **extra}
    result = asyncio.run(
        _registry(coordinator).execute(ToolCall(id="bad", name="task.checkpoint", arguments=args))
    )
    assert result.error.code == "invalid_arguments"
    assert coordinator.store.snapshot() == {}


def test_unplanned_replacement_requires_new_observations_and_replaces_whole_value():
    coordinator = TaskStateCoordinator()
    registry = _registry(coordinator)
    messages = _observe(coordinator, "one", None)
    coordinator.refresh(messages)
    assert _checkpoint(registry, "A").status == "ok"
    assert _checkpoint(registry, "A").status == "error"
    messages += _observe(coordinator, "two", None)
    coordinator.refresh(messages)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="replace", name="task.checkpoint", arguments={"key": "A", "value": {"new": 2}}
            )
        )
    )
    assert result.status == "ok"
    assert coordinator.store.get("A").value == {"new": 2}
    assert coordinator.store.get("A").source_tool_call_ids == ("two",)
    assert registry.get("task.checkpoint").parallel_safe is False


@pytest.mark.parametrize("key,status", [("B", "pending"), ("missing", None)])
def test_key_conflicts_are_recoverable_and_leave_all_state_unchanged(key, status):
    coordinator = TaskStateCoordinator()
    coordinator.create_plan([{"key": "A", "objective": "A"}, {"key": "B", "objective": "B"}])
    coordinator.refresh(_observe(coordinator, "one", "A"))
    before = coordinator.source_owners_snapshot()
    registry = _registry(coordinator)
    result = _checkpoint(registry, key)
    assert result.error.code == "invalid_task_state"
    assert result.error.details == {
        "reason": "current_task_mismatch",
        "requested_key": key,
        "current_key": "A",
        "requested_status": status,
        "current_status": "in_progress",
    }
    assert coordinator.source_owners_snapshot() == before
    assert coordinator.store.snapshot() == {}
    assert _checkpoint(registry, "A").status == "ok"


def test_completed_plan_returns_explicit_error_without_replacing_saved_value():
    coordinator = TaskStateCoordinator()
    coordinator.create_plan([{"key": "A", "objective": "A"}, {"key": "B", "objective": "B"}])
    messages = _observe(coordinator, "one", "A") + _observe(coordinator, "two", "B")
    coordinator.refresh(messages)
    registry = _registry(coordinator)
    _checkpoint(registry, "A")
    _checkpoint(registry, "B")
    before = coordinator.store.snapshot()
    result = _checkpoint(registry, "B")
    assert result.error.code == "invalid_task_state"
    assert result.error.details["reason"] == "plan_complete"
    assert result.error.details["current_key"] is None
    assert coordinator.store.snapshot() == before


def test_internal_errors_are_not_disguised_as_recoverable_conflicts(monkeypatch):
    coordinator = TaskStateCoordinator()

    def fail(*args):
        raise RuntimeError("internal failure")

    monkeypatch.setattr(coordinator, "create_checkpoint", fail)
    result = _checkpoint(_registry(coordinator), "A")
    assert result.error.code == "tool_execution_error"
