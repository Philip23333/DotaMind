from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import AssistantMessage, ToolCall, ToolResultMessage
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import TaskCheckpointInput, register_task_checkpoint_tool


def _active_messages(*call_ids: str) -> list[object]:
    ids = call_ids or ("call-1",)
    messages: list[object] = []
    for call_id in ids:
        messages.extend(
            [
                AssistantMessage(
                    tool_calls=[
                        ToolCall(
                            id=call_id,
                            name="artifact.read",
                            arguments={
                                "ref": "artifact:test",
                                "mode": "read",
                                "path": "rows",
                            },
                        )
                    ]
                ),
                ToolResultMessage(
                    tool_call_id=call_id,
                    content=ArtifactReadResult(
                        ref="artifact:test", path="rows", value=[{"fact": "A"}]
                    ).model_dump(mode="json"),
                ),
            ]
        )
    return messages


def _registry(coordinator: TaskStateCoordinator) -> ToolRegistry:
    registry = ToolRegistry()
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def test_checkpoint_input_schema_has_no_model_supplied_checkpoint_id() -> None:
    schema = TaskCheckpointInput.model_json_schema()

    assert set(schema["properties"]) == {"key", "value", "source_tool_call_ids"}
    with pytest.raises(ValidationError):
        TaskCheckpointInput.model_validate(
            {
                "checkpoint_id": "checkpoint:bad",
                "key": "part",
                "value": {"fact": "A"},
                "source_tool_call_ids": ["call-1"],
            }
        )


def test_checkpoint_tool_accepts_active_source_and_generates_id() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_active_messages())  # type: ignore[arg-type]
    registry = _registry(coordinator)

    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="checkpoint-call",
                name="task.checkpoint",
                arguments={
                    "key": "part",
                    "value": {"fact": "A"},
                    "source_tool_call_ids": ["call-1"],
                },
            )
        )
    )

    assert result.status == "ok"
    assert result.content["checkpoint_id"].startswith("checkpoint:")  # type: ignore[index]
    assert result.content["accepted_source_tool_call_ids"] == ["call-1"]  # type: ignore[index]
    assert coordinator.store.get("part") is not None


@pytest.mark.parametrize(
    "arguments",
    [
        {"key": "", "value": {"fact": "A"}, "source_tool_call_ids": ["call-1"]},
        {"key": "part", "value": {}, "source_tool_call_ids": ["call-1"]},
        {"key": "part", "value": {"fact": "A"}, "source_tool_call_ids": []},
    ],
)
def test_checkpoint_tool_rejects_invalid_arguments(arguments: dict[str, object]) -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_active_messages())  # type: ignore[arg-type]

    result = asyncio.run(
        _registry(coordinator).execute(
            ToolCall(id="checkpoint-call", name="task.checkpoint", arguments=arguments)
        )
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert coordinator.store.snapshot() == {}


def test_checkpoint_tool_rejects_unknown_source_atomically() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_active_messages())  # type: ignore[arg-type]
    registry = _registry(coordinator)
    good = {
        "key": "part",
        "value": {"fact": "A"},
        "source_tool_call_ids": ["call-1"],
    }
    asyncio.run(registry.execute(ToolCall(id="good", name="task.checkpoint", arguments=good)))

    bad = {**good, "value": {"fact": "B"}, "source_tool_call_ids": ["missing"]}
    result = asyncio.run(
        registry.execute(ToolCall(id="bad", name="task.checkpoint", arguments=bad))
    )

    assert result.status == "error"
    assert coordinator.store.get("part").value == {"fact": "A"}  # type: ignore[union-attr]


def test_checkpoint_tool_same_key_replaces_whole_value_and_is_not_parallel_safe() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_active_messages("call-1", "call-2"))  # type: ignore[arg-type]
    registry = _registry(coordinator)
    first = {
        "key": "part",
        "value": {"old": 1},
        "source_tool_call_ids": ["call-1"],
    }
    second = {**first, "value": {"new": 2}}
    second["source_tool_call_ids"] = ["call-2"]

    asyncio.run(registry.execute(ToolCall(id="first", name="task.checkpoint", arguments=first)))
    asyncio.run(registry.execute(ToolCall(id="second", name="task.checkpoint", arguments=second)))

    assert coordinator.store.get("part").value == {"new": 2}  # type: ignore[union-attr]
    assert registry.get("task.checkpoint").parallel_safe is False
