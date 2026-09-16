from __future__ import annotations

import pytest

from app.vnext.agent.task_state import (
    TaskItemStatus,
    TaskStateCoordinator,
)
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import AssistantMessage, ToolCall, ToolResultMessage


def _messages(*call_ids: str) -> list[object]:
    messages: list[object] = []
    for call_id in call_ids:
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
                        ref="artifact:test", path="rows", value=[{"fact": call_id}]
                    ).model_dump(mode="json"),
                ),
            ]
        )
    return messages


def test_create_plan_initializes_first_item_and_snapshot() -> None:
    coordinator = TaskStateCoordinator()

    plan = coordinator.create_plan(
        [
            {"key": "2025", "objective": "Collect 2025 evidence"},
            {"key": "2026", "objective": "Collect 2026 evidence"},
        ]
    )

    assert plan == coordinator.plan_snapshot()
    assert coordinator.current_item() is not None
    assert coordinator.current_item().key == "2025"  # type: ignore[union-attr]
    assert [item.status for item in plan.items] == [
        TaskItemStatus.IN_PROGRESS,
        TaskItemStatus.PENDING,
    ]
    payload = coordinator.context_payload()
    assert payload["task_plan"]["current_key"] == "2025"  # type: ignore[index]


@pytest.mark.parametrize(
    "items,match",
    [
        ([], "between 2 and 16"),
        ([{"key": "only", "objective": "one"}], "between 2 and 16"),
        (
            [{"key": "same", "objective": "a"}, {"key": "same", "objective": "b"}],
            "unique",
        ),
        (
            [{"key": "", "objective": "a"}, {"key": "b", "objective": "b"}],
            "key",
        ),
        (
            [{"key": "a", "objective": ""}, {"key": "b", "objective": "b"}],
            "objective",
        ),
    ],
)
def test_create_plan_validates_before_mutating(
    items: list[dict[str, str]], match: str
) -> None:
    coordinator = TaskStateCoordinator()

    with pytest.raises(ValueError, match=match):
        coordinator.create_plan(items)

    assert coordinator.plan_snapshot() is None


def test_create_plan_is_one_shot() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [{"key": "a", "objective": "A"}, {"key": "b", "objective": "B"}]
    )

    with pytest.raises(ValueError, match="already exists"):
        coordinator.create_plan(
            [{"key": "c", "objective": "C"}, {"key": "d", "objective": "D"}]
        )


def test_checkpoint_completes_current_and_advances_plan_atomically() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [{"key": "a", "objective": "A"}, {"key": "b", "objective": "B"}]
    )
    coordinator.refresh(_messages("call-a", "call-b"))  # type: ignore[arg-type]

    coordinator.create_checkpoint("a", {"fact": "A"}, ["call-a"])
    plan = coordinator.plan_snapshot()
    assert plan is not None
    assert [(item.key, item.status.value) for item in plan.items] == [
        ("a", "completed"),
        ("b", "in_progress"),
    ]
    assert plan.current_key == "b"
    assert coordinator.current_item().key == "b"  # type: ignore[union-attr]

    coordinator.create_checkpoint("b", {"fact": "B"}, ["call-b"])
    plan = coordinator.plan_snapshot()
    assert plan is not None
    assert plan.current_key is None
    assert all(item.status is TaskItemStatus.COMPLETED for item in plan.items)


def test_checkpoint_requires_current_plan_key_and_complete_plan_rejects() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [{"key": "a", "objective": "A"}, {"key": "b", "objective": "B"}]
    )
    coordinator.refresh(_messages("call-a", "call-b"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="current task plan item"):
        coordinator.create_checkpoint("b", {"fact": "B"}, ["call-b"])

    coordinator.create_checkpoint("a", {"fact": "A"}, ["call-a"])
    coordinator.create_checkpoint("b", {"fact": "B"}, ["call-b"])

    with pytest.raises(ValueError, match="already complete"):
        coordinator.create_checkpoint("b", {"fact": "again"}, ["call-b"])


def test_plan_context_is_lightweight_and_deterministic() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [{"key": "a", "objective": "A"}, {"key": "b", "objective": "B"}]
    )

    rendered = coordinator.render_context()
    assert rendered is not None
    assert "Task plan:\nCURRENT: a" in rendered
    assert "- a [in_progress] A" in rendered
    assert "- b [pending] B" in rendered
    assert "Task state:\n{}" in rendered
    assert rendered == coordinator.render_context()
