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
from app.vnext.llm.protocol import AssistantMessage, Message, ToolResultMessage


class ExecutionStopReason(str, Enum):
    """Why the normal execution stage stopped."""

    MODEL_DONE = "model_done"
    PLAN_COMPLETE = "plan_complete"
    DEADLINE = "deadline"
    MAX_STEPS = "max_steps"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Small termination record passed from execution to answering."""

    reason: ExecutionStopReason
    steps: int


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
    ) -> AnswerContext:
        payload = (
            task_state_coordinator.context_payload()
            if task_state_coordinator is not None
            else {"task_plan": None, "task_state": {}, "active_manifest": []}
        )
        return AnswerContext(
            execution_reason=outcome.reason,
            execution_steps=outcome.steps,
            task_plan=deepcopy(payload.get("task_plan")),
            task_state=deepcopy(payload.get("task_state", {})),
            active_artifact_evidence=[
                _artifact_evidence(observation)
                for observation in collect_active_artifact_observations(execution_messages)
            ],
            tool_evidence=_tool_evidence(execution_messages),
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
            "Uncheckpointed verified artifact evidence:\n"
            + _json(context.active_artifact_evidence),
            "Other verified tool evidence:\n" + _json(context.tool_evidence),
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
    tool_names = {
        call.id: call.name
        for message in messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
    }
    excluded = {"task.plan", "task.checkpoint", "artifact.read"}
    evidence: list[dict[str, Any]] = []
    for message in messages:
        if (
            not isinstance(message, ToolResultMessage)
            or message.status != "ok"
            or _is_receipt(message.content)
        ):
            continue
        tool_name = tool_names.get(message.tool_call_id)
        if tool_name is None or tool_name in excluded:
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
    "ExecutionOutcome",
    "ExecutionStopReason",
    "render_answer_context",
]
