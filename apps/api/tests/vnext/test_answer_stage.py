from __future__ import annotations

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    AnswerProjectionMode,
    AnswerResolution,
    AnswerResolutionMode,
    ExecutionOutcome,
    ExecutionStopReason,
    build_answer_fallback,
    resolve_answer,
)
from app.vnext.agent.task_state import (
    TaskCheckpoint,
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskStateCoordinator,
)
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


def _coordinator_for_resolution(
    statuses: list[tuple[str, TaskItemStatus]],
    state_keys: list[str],
) -> TaskStateCoordinator:
    coordinator = TaskStateCoordinator()
    coordinator.plan = TaskPlan(
        items=tuple(TaskItem(key, f"Collect {key}", status) for key, status in statuses),
        current_key=next(
            (key for key, status in statuses if status is not TaskItemStatus.COMPLETED),
            None,
        ),
    )
    for key in state_keys:
        coordinator.store.put(
            TaskCheckpoint(
                checkpoint_id=f"checkpoint:{key}",
                key=key,
                value={"key": key},
                source_tool_call_ids=(),
            )
        )
    return coordinator


def test_resolve_complete_plan_requires_durable_state() -> None:
    coordinator = _coordinator_for_resolution(
        [("A", TaskItemStatus.COMPLETED), ("B", TaskItemStatus.COMPLETED)],
        ["A", "B"],
    )

    resolution = resolve_answer(
        outcome=_outcome(ExecutionStopReason.PLAN_COMPLETE),
        task_state_coordinator=coordinator,
    )

    assert resolution.mode is AnswerResolutionMode.FULL
    assert resolution.completed_keys == ("A", "B")
    assert resolution.remaining_keys == ()


def test_resolve_partial_plan_reports_remaining_items() -> None:
    coordinator = _coordinator_for_resolution(
        [
            ("A", TaskItemStatus.COMPLETED),
            ("B", TaskItemStatus.IN_PROGRESS),
            ("C", TaskItemStatus.PENDING),
        ],
        ["A"],
    )

    resolution = resolve_answer(
        outcome=_outcome(ExecutionStopReason.DEADLINE),
        task_state_coordinator=coordinator,
    )

    assert resolution.mode is AnswerResolutionMode.PARTIAL
    assert resolution.completed_keys == ("A",)
    assert resolution.remaining_keys == ("B", "C")


def test_resolve_plan_with_raw_only_is_failure() -> None:
    coordinator = _coordinator_for_resolution(
        [("A", TaskItemStatus.IN_PROGRESS), ("B", TaskItemStatus.PENDING)],
        [],
    )

    resolution = resolve_answer(
        outcome=_outcome(ExecutionStopReason.DEADLINE),
        task_state_coordinator=coordinator,
    )

    assert resolution.mode is AnswerResolutionMode.FAILURE
    assert resolution.completed_keys == ()
    assert resolution.remaining_keys == ("A", "B")


def test_resolve_without_plan_preserves_simple_model_done_and_closes_deadline() -> None:
    assert resolve_answer(
        outcome=_outcome(ExecutionStopReason.MODEL_DONE),
        task_state_coordinator=None,
    ).mode is AnswerResolutionMode.FULL
    assert resolve_answer(
        outcome=_outcome(ExecutionStopReason.DEADLINE),
        task_state_coordinator=None,
    ).mode is AnswerResolutionMode.FAILURE


def test_resolve_completed_plan_without_state_is_not_full() -> None:
    coordinator = _coordinator_for_resolution(
        [("A", TaskItemStatus.COMPLETED)],
        [],
    )

    resolution = resolve_answer(
        outcome=_outcome(ExecutionStopReason.PLAN_COMPLETE),
        task_state_coordinator=coordinator,
    )

    assert resolution.mode is AnswerResolutionMode.FAILURE
    assert resolution.completed_keys == ()
    assert resolution.remaining_keys == ("A",)


def test_build_answer_fallback_distinguishes_full_partial_and_no_plan() -> None:
    full = AnswerResolution(
        mode=AnswerResolutionMode.FULL,
        total_items=2,
        completed_keys=("A", "B"),
        remaining_keys=(),
    )
    partial = AnswerResolution(
        mode=AnswerResolutionMode.PARTIAL,
        total_items=3,
        completed_keys=("A",),
        remaining_keys=("B", "C"),
    )
    no_plan = AnswerResolution(
        mode=AnswerResolutionMode.FULL,
        total_items=None,
        completed_keys=(),
        remaining_keys=(),
    )

    assert "2 of 2 planned parts were completed" in build_answer_fallback(
        full, _outcome(ExecutionStopReason.PLAN_COMPLETE)
    ).content
    partial_text = build_answer_fallback(
        partial, _outcome(ExecutionStopReason.DEADLINE)
    ).content
    assert "1 of 3 planned parts were completed" in partial_text
    assert "won't infer or fill them in" in partial_text
    assert "planned parts" not in build_answer_fallback(
        no_plan, _outcome(ExecutionStopReason.MODEL_DONE)
    ).content


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
        resolution=AnswerResolution(
            mode=AnswerResolutionMode.FULL,
            total_items=3,
            completed_keys=("2021", "2022", "2023"),
            remaining_keys=(),
        ),
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


def test_partial_projection_contains_checkpointed_state_and_pending_coverage() -> None:
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
        resolution=resolve_answer(
            outcome=_outcome(), task_state_coordinator=coordinator
        ),
    )

    assert context.task_state == {"2021": {"series_count": 22}}
    assert context.active_artifact_evidence == []
    assert context.tool_evidence == []
    assert [item["status"] for item in context.task_plan["items"]] == [  # type: ignore[index]
        "completed",
        "in_progress",
        "pending",
    ]


def test_resolution_aware_projection_matrix() -> None:
    coordinator = _coordinator_for_resolution(
        [
            ("A", TaskItemStatus.COMPLETED),
            ("B", TaskItemStatus.IN_PROGRESS),
        ],
        ["A"],
    )
    messages = [
        AssistantMessage(
            tool_calls=[
                _call("read-B", "artifact.read"),
                _call("team", "esports.team.search"),
            ]
        ),
        _result(
            "read-B",
            ArtifactReadResult(
                ref="artifact:ti", path="matches", value=[{"year": 2022}]
            ).model_dump(mode="json"),
        ),
        _result("team", {"teams": [{"id": 1}]}),
    ]
    partial = resolve_answer(
        outcome=_outcome(ExecutionStopReason.DEADLINE),
        task_state_coordinator=coordinator,
    )
    full = AnswerResolution(
        mode=AnswerResolutionMode.FULL,
        total_items=2,
        completed_keys=("A",),
        remaining_keys=("B",),
    )
    builder = AnswerContextBuilder()

    full_primary = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.PLAN_COMPLETE),
        task_state_coordinator=coordinator,
        resolution=full,
        projection_mode=AnswerProjectionMode.PRIMARY,
    )
    partial_primary = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.DEADLINE),
        task_state_coordinator=coordinator,
        resolution=partial,
        projection_mode=AnswerProjectionMode.PRIMARY,
    )
    full_degraded = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.PLAN_COMPLETE),
        task_state_coordinator=coordinator,
        resolution=full,
        projection_mode=AnswerProjectionMode.DEGRADED,
    )
    no_plan_degraded = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.MODEL_DONE),
        task_state_coordinator=None,
        resolution=resolve_answer(
            outcome=_outcome(ExecutionStopReason.MODEL_DONE),
            task_state_coordinator=None,
        ),
        projection_mode=AnswerProjectionMode.DEGRADED,
    )

    assert full_primary.active_artifact_evidence
    assert full_primary.tool_evidence
    assert partial_primary.task_state == {"A": {"key": "A"}}
    assert partial_primary.active_artifact_evidence == []
    assert partial_primary.tool_evidence == []
    assert full_degraded.task_state == {"A": {"key": "A"}}
    assert full_degraded.active_artifact_evidence == []
    assert full_degraded.tool_evidence == []
    assert no_plan_degraded.active_artifact_evidence
    assert no_plan_degraded.tool_evidence


def test_projection_task_state_uses_only_completed_resolution_keys() -> None:
    coordinator = _coordinator_for_resolution(
        [
            ("A", TaskItemStatus.COMPLETED),
            ("B", TaskItemStatus.COMPLETED),
        ],
        ["A", "B"],
    )
    messages: list[object] = []
    resolution = AnswerResolution(
        mode=AnswerResolutionMode.FULL,
        total_items=2,
        completed_keys=("A",),
        remaining_keys=("B",),
    )

    context = AnswerContextBuilder().build(
        execution_messages=messages,  # type: ignore[arg-type]
        outcome=_outcome(ExecutionStopReason.MODEL_DONE),
        task_state_coordinator=coordinator,
        resolution=resolution,
    )

    assert context.task_state == {"A": {"key": "A"}}


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
        resolution=resolve_answer(
            outcome=_outcome(ExecutionStopReason.MODEL_DONE),
            task_state_coordinator=None,
        ),
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
        resolution=resolve_answer(
            outcome=_outcome(ExecutionStopReason.MAX_STEPS),
            task_state_coordinator=None,
        ),
    )
    second = builder.build(
        execution_messages=messages,
        outcome=_outcome(ExecutionStopReason.MAX_STEPS),
        task_state_coordinator=None,
        resolution=resolve_answer(
            outcome=_outcome(ExecutionStopReason.MAX_STEPS),
            task_state_coordinator=None,
        ),
    )

    assert first.task_plan is None
    assert first.task_state == {}
    assert first.to_dict() == second.to_dict()
    assert first.render() == second.render()
    assert "reason: max_steps" in first.render()
    assert "CURRENT" not in first.render()
