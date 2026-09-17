"""Canonical application-visible trace capture for one agent execution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import monotonic
from typing import Any

from app.vnext.agent.answer_stage import AnswerContext, ExecutionOutcome
from app.vnext.agent.context_accounting import build_context_accounting
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

    def answer_stage(self, request: ModelRequest, context: AnswerContext) -> None:
        accounting = build_context_accounting(request).to_dict()
        self._trace["answer_stage"] = {
            "tool_count": len(request.tools),
            "task_state_count": len(context.task_state),
            "active_raw_count": len(context.active_artifact_evidence),
            "tool_evidence_count": len(context.tool_evidence),
            "context_bytes": accounting["effective_request"]["serialized_bytes"],
        }

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
