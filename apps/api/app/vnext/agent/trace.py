"""Canonical application-visible trace capture for one agent execution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import monotonic
from typing import Any

from app.vnext.agent.answer_stage import (
    AnswerContext,
    AnswerResolution,
    ExecutionOutcome,
    ExecutionStopReason,
)
from app.vnext.agent.context_accounting import build_context_accounting
from app.vnext.agent.materialization_budget import MaterializationDecision
from app.vnext.agent.runtime_context import RuntimeContext
from app.vnext.agent.transcript_rewrite import TranscriptRewriteEvent
from app.vnext.llm.protocol import (
    Message,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
)


class AgentTraceCollector:
    """Collect one run's model and tool evidence without provider transport data."""

    def __init__(self) -> None:
        self._started = monotonic()
        self._trace: dict[str, Any] = {"initial_messages": [], "tool_schemas": [], "steps": []}

    def begin(self, messages: Sequence[Message], tool_schemas: list[dict[str, Any]]) -> None:
        self._trace["initial_messages"] = [message.model_dump(mode="json") for message in messages]
        self._trace["tool_schemas"] = tool_schemas

    def model_request(
        self,
        request: ModelRequest,
        runtime_context: RuntimeContext | None = None,
        *,
        conversation_messages: Sequence[Message] | None = None,
        task_context_messages: Sequence[Message] | None = None,
        task_context_payload: dict[str, Any] | None = None,
    ) -> None:
        """Record one model invocation without persisting its runtime prompt."""

        traced_request = (
            request.model_copy(update={"messages": list(conversation_messages)})
            if conversation_messages is not None
            else request
        )
        item = self._step(request.step)
        item["model_request"] = traced_request.model_dump(mode="json")
        item["runtime_context"] = (
            runtime_context_to_dict(runtime_context) if runtime_context is not None else None
        )
        item["context_accounting"] = build_context_accounting(
            request,
            stable_messages=conversation_messages,
            task_context_messages=task_context_messages,
            task_context_payload=task_context_payload,
        ).to_dict()

    def text_delta(self, step: int, text: str) -> None:
        self._step(step).setdefault("streamed_text", []).append(text)

    def model_response(self, step: int, response: ModelResponse, duration: float) -> None:
        item = self._step(step)
        item["model_response"] = response.model_dump(mode="json")
        item["model_duration_seconds"] = duration

    def tool_result(
        self,
        step: int,
        result: ToolResultMessage,
        duration: float,
        *,
        call: ToolCall | None = None,
    ) -> None:
        item = self._step(step)
        item.setdefault("tool_results", []).append(
            {"result": result.model_dump(mode="json"), "duration_seconds": duration}
        )
        if call is not None and call.name == "task.checkpoint":
            item.setdefault("checkpoint_metrics", []).append(
                _checkpoint_metric(call, result)
            )
        if call is not None and call.name == "task.plan":
            item.setdefault("task_plan_metrics", []).append(
                _task_plan_metric(call, result)
            )

    def transcript_rewrite(self, step: int, event: TranscriptRewriteEvent) -> None:
        """Record a transcript replacement without duplicating raw evidence."""

        self._step(step).setdefault("transcript_rewrites", []).append(
            {
                "kind": event.kind,
                "tool_call_id": event.tool_call_id,
                "reason": event.reason,
                **event.metadata,
            }
        )

    def active_evidence_lease(
        self,
        step: int,
        payload: dict[str, Any] | None,
    ) -> None:
        """Record locator-free active evidence lease accounting."""

        if payload is not None:
            self._step(step)["active_evidence_lease"] = payload

    def partition_evidence_release(self, step: int, release: Any) -> None:
        """Record evidence released after a successful partition checkpoint."""

        self._step(step)["partition_evidence_release"] = {
            "task_key": release.task_key,
            "checkpointed_count": release.checkpointed_count,
            "partition_closed_count": release.partition_closed_count,
            "released_bytes": release.released_bytes,
        }

    def materialization_admission(
        self,
        step: int,
        *,
        decision: MaterializationDecision,
        task_key: str | None,
        limit_bytes: int,
    ) -> None:
        """Record whether one materialized result entered model context."""

        budget = self._materialization_budget(step, limit_bytes)
        budget["admissions"].append(
            {
                "tool_call_id": decision.tool_call_id,
                "task_key": task_key,
                "raw_bytes": decision.raw_bytes,
                "admitted": decision.admitted,
                "active_before_bytes": decision.active_before_bytes,
                "active_after_bytes": decision.active_after_bytes,
            }
        )

    def materialization_release(
        self,
        step: int,
        *,
        tool_call_id: str,
        reason: str,
        released_bytes: int,
        active_after_bytes: int,
        limit_bytes: int,
    ) -> None:
        """Record bytes released from the active materialization budget."""

        if released_bytes <= 0:
            return
        budget = self._materialization_budget(step, limit_bytes)
        budget["releases"].append(
            {
                "tool_call_id": tool_call_id,
                "reason": reason,
                "released_bytes": released_bytes,
                "active_after_bytes": active_after_bytes,
            }
        )

    def terminal(self, *, status: str, error_code: str | None, error_message: str | None) -> None:
        self._trace["terminal"] = {
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
            "duration_seconds": max(0.0, monotonic() - self._started),
        }

    def execution_outcome(self, outcome: ExecutionOutcome, *, plan_complete: bool) -> None:
        self._trace["execution_outcome"] = {
            "reason": outcome.reason.value,
            "steps": outcome.steps,
            "plan_complete": plan_complete,
        }

    def answer_resolution(
        self,
        resolution: AnswerResolution,
        *,
        execution_reason: ExecutionStopReason,
    ) -> None:
        self._trace["answer_resolution"] = {
            "mode": resolution.mode.value,
            "execution_reason": execution_reason.value,
            "total_items": resolution.total_items,
            "completed_count": len(resolution.completed_keys),
            "remaining_count": len(resolution.remaining_keys),
            "completed_keys": list(resolution.completed_keys),
            "remaining_keys": list(resolution.remaining_keys),
        }

    def answer_stage(self, request: ModelRequest, context: AnswerContext) -> None:
        accounting = build_context_accounting(request).to_dict()
        self._trace["answer_stage"] = {
            "tool_count": len(request.tools),
            "task_state_count": len(context.task_state),
            "active_raw_count": len(context.active_artifact_evidence),
            "tool_evidence_count": len(context.tool_evidence),
            "context_bytes": accounting["effective_request"]["serialized_bytes"],
        }

    def answer_projection(
        self,
        request: ModelRequest,
        context: AnswerContext,
        *,
        kind: str,
        resolution: AnswerResolution,
    ) -> None:
        accounting = build_context_accounting(request).to_dict()
        self._trace.setdefault("answer_projections", []).append(
            {
                "kind": kind,
                "resolution": resolution.mode.value,
                "task_state_count": len(context.task_state),
                "active_raw_count": len(context.active_artifact_evidence),
                "tool_evidence_count": len(context.tool_evidence),
                "context_bytes": accounting["effective_request"]["serialized_bytes"],
            }
        )

    def answer_attempt(
        self,
        *,
        kind: str,
        step: int,
        status: str,
        duration_seconds: float,
        error_code: str | None,
    ) -> None:
        self._trace.setdefault("answer_attempts", []).append(
            {
                "kind": kind,
                "step": step,
                "status": status,
                "duration_seconds": duration_seconds,
                "error_code": error_code,
            }
        )

    def answer_fallback(self, kind: str) -> None:
        self._trace["answer_fallback"] = kind

    def snapshot(self) -> dict[str, Any]:
        return self._trace.copy()

    def _step(self, step: int | None) -> dict[str, Any]:
        normalized_step = step or 0
        for item in self._trace["steps"]:
            if item["step"] == normalized_step:
                return item
        item = {"step": normalized_step}
        self._trace["steps"].append(item)
        return item

    def _materialization_budget(self, step: int, limit_bytes: int) -> dict[str, Any]:
        item = self._step(step)
        budget = item.setdefault(
            "materialization_budget",
            {"limit_bytes": limit_bytes, "admissions": [], "releases": []},
        )
        return budget


def runtime_context_to_dict(context: RuntimeContext) -> dict[str, object]:
    """Convert a RuntimeContext snapshot into JSON-safe trace fields."""

    return {
        "phase": context.phase.value,
        "remaining_turns": context.remaining_turns,
        "time_pressure": context.time_pressure.value,
        "context_pressure": context.context_pressure.value,
        "tools_available": context.tools_available,
    }


def _checkpoint_metric(call: ToolCall, result: ToolResultMessage) -> dict[str, Any]:
    arguments = call.arguments
    value = arguments.get("value")
    source_ids = arguments.get("source_tool_call_ids")
    key = arguments.get("key")
    checkpoint_id: str | None = None
    if result.status == "ok" and isinstance(result.content, dict):
        content = result.content
        if isinstance(content.get("checkpoint_id"), str):
            checkpoint_id = content["checkpoint_id"]
        if isinstance(content.get("key"), str):
            key = content["key"]
        accepted = content.get("accepted_source_tool_call_ids")
        if isinstance(accepted, list):
            source_ids = accepted
    metric: dict[str, Any] = {
        "tool_call_id": call.id,
        "status": result.status,
    }
    if isinstance(checkpoint_id, str):
        metric["checkpoint_id"] = checkpoint_id
    if isinstance(key, str):
        metric["key"] = key
    if isinstance(source_ids, list):
        metric["source_count"] = len(source_ids)
    if value is not None:
        metric["value_bytes"] = _serialized_size(value)
    return metric


def _task_plan_metric(call: ToolCall, result: ToolResultMessage) -> dict[str, Any]:
    metric: dict[str, Any] = {
        "tool_call_id": call.id,
        "status": result.status,
    }
    if result.status == "ok" and isinstance(result.content, dict):
        item_count = result.content.get("item_count")
        current_key = result.content.get("current_key")
        if isinstance(item_count, int):
            metric["item_count"] = item_count
        if isinstance(current_key, str) or current_key is None:
            metric["current_key"] = current_key
    return metric


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


__all__ = ["AgentTraceCollector", "runtime_context_to_dict"]
