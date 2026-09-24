"""Projection of completed execution evidence for the Answer Stage."""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts.lifecycle import (
    ArtifactObservation,
    collect_active_artifact_observations,
)
from app.vnext.llm.protocol import AssistantMessage, FinalMessage, Message, ToolResultMessage


class ExecutionStopReason(str, Enum):
    """Why the normal execution stage stopped."""

    MODEL_DONE = "model_done"
    PLAN_COMPLETE = "plan_complete"
    DEADLINE = "deadline"
    CONTEXT_CAPACITY = "context_capacity"


class AnswerResolutionMode(str, Enum):
    """Whether execution produced enough durable state for Answer Stage."""

    FULL = "full"
    PARTIAL = "partial"
    FAILURE = "failure"


class AnswerProjectionMode(str, Enum):
    """Which evidence projection is being built for an Answer attempt."""

    PRIMARY = "primary"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Small termination record passed from execution to answering."""

    reason: ExecutionStopReason
    steps: int


@dataclass(frozen=True, slots=True)
class AnswerResolution:
    """Deterministic execution coverage classification for answering."""

    mode: AnswerResolutionMode
    total_items: int | None
    completed_keys: tuple[str, ...]
    remaining_keys: tuple[str, ...]


def resolve_answer(
    *,
    outcome: ExecutionOutcome,
    task_state_coordinator: TaskStateCoordinator | None,
) -> AnswerResolution:
    """Classify durable execution coverage without inspecting raw evidence."""

    payload = (
        task_state_coordinator.context_payload()
        if task_state_coordinator is not None
        else {"task_plan": None, "task_state": {}}
    )
    task_plan = payload.get("task_plan")
    if not isinstance(task_plan, dict):
        mode = (
            AnswerResolutionMode.FULL
            if outcome.reason in {ExecutionStopReason.MODEL_DONE, ExecutionStopReason.PLAN_COMPLETE}
            else AnswerResolutionMode.PARTIAL
            if outcome.reason is ExecutionStopReason.CONTEXT_CAPACITY
            else AnswerResolutionMode.FAILURE
        )
        return AnswerResolution(
            mode=mode,
            total_items=None,
            completed_keys=(),
            remaining_keys=(),
        )

    items = task_plan.get("items")
    task_state = payload.get("task_state")
    if not isinstance(items, list) or not isinstance(task_state, dict):
        return AnswerResolution(
            mode=AnswerResolutionMode.FAILURE,
            total_items=0,
            completed_keys=(),
            remaining_keys=(),
        )

    completed_keys = tuple(
        item["key"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("key"), str)
        and item.get("status") == "completed"
        and item["key"] in task_state
    )
    completed_set = set(completed_keys)
    remaining_keys = tuple(
        item["key"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("key"), str)
        and item["key"] not in completed_set
    )
    total_items = len(items)
    if total_items > 0 and len(completed_keys) == total_items:
        mode = AnswerResolutionMode.FULL
    elif completed_keys:
        mode = AnswerResolutionMode.PARTIAL
    else:
        mode = AnswerResolutionMode.FAILURE
    return AnswerResolution(
        mode=mode,
        total_items=total_items,
        completed_keys=completed_keys,
        remaining_keys=remaining_keys,
    )


def build_failure_answer(
    resolution: AnswerResolution,
    outcome: ExecutionOutcome,
) -> FinalMessage:
    """Close an execution with no durable result without invoking another model."""

    lines = [
        "I wasn't able to complete enough verified parts of this request "
        "to produce a reliable answer.",
    ]
    if outcome.reason is ExecutionStopReason.CONTEXT_CAPACITY:
        lines.append("The execution stopped because the available context budget was exhausted.")
    if resolution.total_items is not None:
        lines.append(
            f"{len(resolution.completed_keys)} of {resolution.total_items} planned "
            "parts were completed."
        )
    elif outcome.reason is ExecutionStopReason.DEADLINE:
        lines.append("The execution stopped before a verified result was completed.")
    return FinalMessage(content="\n\n".join(lines))


def build_answer_fallback(
    resolution: AnswerResolution,
    outcome: ExecutionOutcome,
    *,
    context_capacity_exhausted: bool = False,
) -> FinalMessage:
    """Build a deterministic fallback for execution or answer-stage limits."""

    if outcome.reason is ExecutionStopReason.CONTEXT_CAPACITY:
        execution_note = (
            "The execution stopped early because the available context budget was exhausted."
        )
        if resolution.total_items is None:
            return FinalMessage(
                content=(execution_note + " I wasn't able to generate a reliable final response.")
            )
        completed = len(resolution.completed_keys)
        coverage = f"{completed} of {resolution.total_items} planned parts were completed."
        remaining = (
            " The remaining parts were not completed, so I won't infer or fill them in."
            if resolution.remaining_keys
            else ""
        )
        return FinalMessage(content=f"{execution_note}\n\n{coverage}{remaining}")

    answer_capacity_message = (
        "I wasn't able to generate the detailed final response within the available context budget."
        if context_capacity_exhausted
        else None
    )
    if resolution.total_items is None:
        return FinalMessage(
            content=answer_capacity_message
            or (
                "The task execution completed, but I wasn't able to generate the "
                "detailed final response within the response limit."
            )
        )

    completed = len(resolution.completed_keys)
    coverage = f"{completed} of {resolution.total_items} planned parts were completed."
    if resolution.mode is AnswerResolutionMode.FULL:
        return FinalMessage(
            content=(
                (
                    answer_capacity_message
                    or (
                        "The requested data processing was completed, but I wasn't able "
                        "to generate the detailed final response within the response "
                        "limit."
                    )
                )
                + "\n\n"
                f"{coverage}"
            )
        )
    return FinalMessage(
        content=(
            (
                answer_capacity_message
                or (
                    "I wasn't able to generate the detailed final response within "
                    "the response limit."
                )
            )
            + "\n\n"
            f"{coverage} The remaining parts were not completed, so I won't "
            "infer or fill them in."
        )
    )


@dataclass(frozen=True, slots=True)
class AnswerContext:
    """Evidence-only projection consumed by one Answer Stage invocation."""

    execution_reason: ExecutionStopReason
    execution_steps: int
    task_plan: dict[str, Any] | None
    task_state: dict[str, Any]
    active_artifact_evidence: list[dict[str, Any]]
    tool_evidence: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_reason": self.execution_reason.value,
            "execution_steps": self.execution_steps,
            "task_plan": deepcopy(self.task_plan),
            "task_state": deepcopy(self.task_state),
            "active_artifact_evidence": deepcopy(self.active_artifact_evidence),
            "tool_evidence": deepcopy(self.tool_evidence),
        }

    def render(self) -> str:
        return render_answer_context(self)


class AnswerContextBuilder:
    """Build a compact projection without replaying or fetching evidence."""

    def build(
        self,
        *,
        execution_messages: Sequence[Message],
        outcome: ExecutionOutcome,
        task_state_coordinator: TaskStateCoordinator | None,
        resolution: AnswerResolution,
        projection_mode: AnswerProjectionMode = AnswerProjectionMode.PRIMARY,
        effective_history_embedded: bool = False,
    ) -> AnswerContext:
        payload = (
            task_state_coordinator.context_payload()
            if task_state_coordinator is not None
            else {"task_plan": None, "task_state": {}, "active_manifest": []}
        )
        task_plan = payload.get("task_plan")
        has_plan = isinstance(task_plan, dict)
        task_state_payload = payload.get("task_state", {})
        if not isinstance(task_state_payload, dict):
            task_state_payload = {}
        task_state = (
            {
                key: deepcopy(task_state_payload[key])
                for key in resolution.completed_keys
                if key in task_state_payload
            }
            if has_plan
            else deepcopy(task_state_payload)
        )
        restricted = has_plan and (
            resolution.mode is AnswerResolutionMode.PARTIAL
            or projection_mode is AnswerProjectionMode.DEGRADED
        )
        omit_history_evidence = restricted or effective_history_embedded
        return AnswerContext(
            execution_reason=outcome.reason,
            execution_steps=outcome.steps,
            task_plan=deepcopy(task_plan),
            task_state=task_state,
            active_artifact_evidence=(
                []
                if omit_history_evidence
                else [
                    _artifact_evidence(observation)
                    for observation in collect_active_artifact_observations(execution_messages)
                ]
            ),
            tool_evidence=[] if omit_history_evidence else _tool_evidence(execution_messages),
        )


def render_answer_context(context: AnswerContext) -> str:
    """Render a deterministic, machine-friendly Answer Stage context."""

    return "\n\n".join(
        (
            "Execution result:\n"
            f"reason: {context.execution_reason.value}\n"
            f"steps: {context.execution_steps}",
            "Task coverage:\n" + _json(context.task_plan),
            "Completed task state:\n" + _json(context.task_state),
            "Artifact observations:\n" + _json(context.active_artifact_evidence),
            "Other successful tool observations:\n" + _json(context.tool_evidence),
        )
    )


def _artifact_evidence(observation: ArtifactObservation) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "ref": observation.ref,
        "path": observation.path,
        "value": deepcopy(observation.value),
    }
    if observation.actual_start is not None and observation.actual_end is not None:
        evidence["range"] = [observation.actual_start, observation.actual_end]
    return evidence


def _tool_evidence(messages: Sequence[Message]) -> list[dict[str, Any]]:
    tool_names: dict[str, list[str]] = {}
    for message in messages:
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                tool_names.setdefault(call.id, []).append(call.name)
    excluded = {"task.plan", "task.checkpoint", "artifact.read"}
    evidence: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolResultMessage):
            continue
        names = tool_names.get(message.tool_call_id)
        tool_name = names.pop(0) if names else None
        if (
            message.status != "ok"
            or _is_receipt(message.content)
            or tool_name is None
            or tool_name in excluded
        ):
            continue
        evidence.append(
            {
                "tool": tool_name,
                "content": deepcopy(message.content),
            }
        )
    return evidence


def _is_receipt(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_artifact_observation")
    return isinstance(marker, dict) and marker.get("state") == "receipt_only"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = [
    "AnswerContext",
    "AnswerContextBuilder",
    "AnswerProjectionMode",
    "AnswerResolution",
    "AnswerResolutionMode",
    "ExecutionOutcome",
    "ExecutionStopReason",
    "build_answer_fallback",
    "build_failure_answer",
    "render_answer_context",
    "resolve_answer",
]
