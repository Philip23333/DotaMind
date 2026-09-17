from __future__ import annotations

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    ExecutionOutcome,
    ExecutionStopReason,
)
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import AssistantMessage, ToolCall, ToolResultMessage


def _call(call_id: str, name: str, arguments: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments or {})


def _result(call_id: str, content: object, *, status: str = "ok") -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        content=content,
        status=status,  # type: ignore[arg-type]
        error=(
            {"code": "tool_execution_error", "message": "failed", "details": {}}
            if status == "error"
            else None
        ),
    )


def _outcome(reason: ExecutionStopReason = ExecutionStopReason.DEADLINE) -> ExecutionOutcome:
    return ExecutionOutcome(reason=reason, steps=7)


def test_projection_includes_task_state_plan_and_active_artifact_range() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2021", "objective": "Collect 2021"},
            {"key": "2022", "objective": "Collect 2022"},
            {"key": "2023", "objective": "Collect 2023"},
        ]
    )
    messages = [
        AssistantMessage(tool_calls=[_call("read-2022", "artifact.read")]),
        _result(
            "read-2022",
            ArtifactReadResult(
                ref="artifact:ti",
                path="matches",
                value=[{"year": 2022}],
                offset=4,
                limit=4,
            ).model_dump(mode="json"),
        ),
    ]
    coordinator.refresh(messages)

    context = AnswerContextBuilder().build(
        execution_messages=messages,
        outcome=_outcome(),
        task_state_coordinator=coordinator,
    )

    assert context.task_plan["current_key"] == "2021"  # type: ignore[index]
    assert context.task_state == {}
    assert context.active_artifact_evidence == [
        {
            "ref": "artifact:ti",
            "path": "matches",
            "range": [4, 5],
            "value": [{"year": 2022}],
        }
    ]


def test_projection_contains_checkpointed_state_active_raw_and_pending_coverage() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2021", "objective": "Collect 2021"},
            {"key": "2022", "objective": "Collect 2022"},
            {"key": "2023", "objective": "Collect 2023"},
        ]
    )
    messages = [
        AssistantMessage(tool_calls=[_call("read-2021", "artifact.read")]),
        _result(
            "read-2021",
            ArtifactReadResult(
                ref="artifact:ti", path="matches", value=[{"year": 2021}]
            ).model_dump(mode="json"),
        ),
        AssistantMessage(tool_calls=[_call("read-2022", "artifact.read")]),
        _result(
            "read-2022",
            ArtifactReadResult(
                ref="artifact:ti", path="matches", value=[{"year": 2022}]
            ).model_dump(mode="json"),
        ),
    ]
    coordinator.refresh(messages)
    coordinator.create_checkpoint("2021", {"series_count": 22}, ["read-2021"])
    rewritten = [
        messages[0],
        messages[1].model_copy(
            update={
                "content": {
                    "_artifact_observation": {
                        "state": "receipt_only",
                        "reason": "checkpointed",
                    }
                }
            }
        ),
        *messages[2:],
    ]

    context = AnswerContextBuilder().build(
        execution_messages=rewritten,
        outcome=_outcome(),
        task_state_coordinator=coordinator,
    )

    assert context.task_state == {"2021": {"series_count": 22}}
    assert [item["value"] for item in context.active_artifact_evidence] == [[{"year": 2022}]]
    assert [item["status"] for item in context.task_plan["items"]] == [  # type: ignore[index]
        "completed",
        "in_progress",
        "pending",
    ]


def test_projection_includes_successful_normal_tools_and_excludes_control_or_failed_results(
) -> None:
    messages = [
        AssistantMessage(
            tool_calls=[
                _call("team", "esports.team.search"),
                _call("plan", "task.plan"),
                _call("checkpoint", "task.checkpoint"),
                _call("read", "artifact.read"),
                _call("grep", "artifact.grep"),
                _call("failed", "esports.match.search"),
            ]
        ),
        _result("team", {"teams": [{"id": 1}]}),
        _result("plan", {"item_count": 2, "current_key": "a"}),
        _result("checkpoint", {"checkpoint_id": "checkpoint:1"}),
        _result("read", {"ref": "artifact:x", "path": "rows", "value": []}),
        _result("grep", {"matches": []}),
        _result("failed", {"message": "no"}, status="error"),
        _result(
            "read-receipt",
            {"_artifact_observation": {"state": "receipt_only"}},
        ),
    ]

    context = AnswerContextBuilder().build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.MODEL_DONE),
        task_state_coordinator=None,
    )

    assert context.tool_evidence == [
        {"tool": "esports.team.search", "content": {"teams": [{"id": 1}]}},
        {"tool": "artifact.grep", "content": {"matches": []}},
    ]
    assert context.active_artifact_evidence == [
        {"ref": "artifact:x", "path": "rows", "range": [0, 0], "value": []}
    ]


def test_projection_without_coordinator_and_render_are_deterministic() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("team", "esports.team.search")]),
        _result("team", {"name": "Team Spirit"}),
    ]
    builder = AnswerContextBuilder()
    first = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.MAX_STEPS),
        task_state_coordinator=None,
    )
    second = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.MAX_STEPS),
        task_state_coordinator=None,
    )

    assert first.task_plan is None
    assert first.task_state == {}
    assert first.to_dict() == second.to_dict()
    assert first.render() == second.render()
    assert "reason: max_steps" in first.render()
    assert "CURRENT" not in first.render()
