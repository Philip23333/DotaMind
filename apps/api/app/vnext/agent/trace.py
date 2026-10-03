"""Canonical application-visible trace capture for one agent execution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from app.vnext.agent.answer_stage import (
    AnswerContext,
    AnswerResolution,
    ExecutionOutcome,
    ExecutionStopReason,
)
from app.vnext.agent.context_accounting import build_context_accounting
from app.vnext.agent.context_capacity import RequestCapacity
from app.vnext.agent.runtime_context import RuntimeContext
from app.vnext.agent.transcript_rewrite import TranscriptRewriteEvent
from app.vnext.llm.diagnostics import ModelFailureDiagnostics
from app.vnext.llm.protocol import (
    Message,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
)


class AgentTraceCollector:
    """Collect one run's model and tool evidence without provider transport data."""

    def __init__(self, *, capture_full_calls: bool = False) -> None:
        self._started = monotonic()
        self._capture_full_calls = capture_full_calls
        self._trace: dict[str, Any] = {"initial_messages": [], "tool_schemas": [], "steps": []}
        if capture_full_calls:
            self._trace["model_calls"] = []

    def model_call_started(
        self,
        request: ModelRequest,
        *,
        step: int,
        purpose: Literal["execution", "primary_answer", "degraded_answer", "compaction"],
    ) -> str | None:
        if not self._capture_full_calls:
            return None
        call_id = str(uuid4())
        self._trace["model_calls"].append(
            {
                "call_id": call_id,
                "step": step,
                "purpose": purpose,
                "request": deepcopy(request.model_dump(mode="json")),
                "response": None,
                "partial_text": "",
                "status": "started",
                "duration_seconds": None,
                "error_type": None,
                "error_code": None,
                "failure_diagnostics": None,
            }
        )
        return call_id

    def model_call_response(self, call_id: str | None, response: ModelResponse) -> None:
        call = self._model_call(call_id)
        if call is not None:
            call["response"] = deepcopy(response.model_dump(mode="json"))

    def model_call_text_delta(self, call_id: str | None, text: str) -> None:
        call = self._model_call(call_id)
        if call is not None:
            call["partial_text"] += text

    def model_call_failure_diagnostics(
        self,
        call_id: str | None,
        *,
        step: int,
        purpose: Literal["execution", "primary_answer", "degraded_answer", "compaction"],
        diagnostics: ModelFailureDiagnostics,
    ) -> None:
        """Associate parsing evidence with a full call or a redacted diagnostic step."""

        payload = diagnostics.model_dump(mode="json")
        if self._capture_full_calls:
            call = self._model_call(call_id)
            if call is not None:
                call["failure_diagnostics"] = deepcopy(payload)
            return

        redacted = deepcopy(payload)
        for tool_call in redacted.get("tool_calls", []):
            if isinstance(tool_call, dict):
                tool_call.pop("raw_arguments", None)
                tool_call.pop("arguments_prefix", None)
                tool_call.pop("arguments_suffix", None)
        redacted["purpose"] = purpose
        self._step(step).setdefault("model_failure_diagnostics", []).append(redacted)

    def model_call_finished(
        self,
        call_id: str | None,
        *,
        status: Literal["completed", "failed", "cancelled", "deadline"],
        duration_seconds: float,
        error: BaseException | None = None,
    ) -> None:
        call = self._model_call(call_id)
        if call is None or call["status"] != "started":
            return
        call["status"] = status
        call["duration_seconds"] = duration_seconds
        if error is not None:
            call["error_type"] = type(error).__name__
            code = getattr(error, "code", None)
            call["error_code"] = code if isinstance(code, str) else None

    def _model_call(self, call_id: str | None) -> dict[str, Any] | None:
        if call_id is None:
            return None
        for call in self._trace.get("model_calls", []):
            if call["call_id"] == call_id:
                return call
        return None

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

    def archive_failed_model_attempt(self, step: int, *, error_code: str) -> None:
        """Move the failed request projection aside before recording a retry."""

        item = self._step(step)
        attempt: dict[str, Any] = {}
        for field in ("model_request", "runtime_context", "context_accounting", "streamed_text"):
            if field in item:
                attempt[field] = deepcopy(item.pop(field))
        attempt["error_code"] = error_code
        item.setdefault("failed_model_attempts", []).append(attempt)

    def overflow_recovery(
        self,
        *,
        step: int,
        stage: Literal["execution", "primary_answer"],
        status: str,
        error_code: str | None,
    ) -> None:
        self._trace.setdefault("overflow_recoveries", []).append(
            {
                "step": step,
                "stage": stage,
                "status": status,
                "error_code": error_code,
            }
        )

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
            item.setdefault("checkpoint_metrics", []).append(_checkpoint_metric(call, result))
        if call is not None and call.name == "task.plan":
            item.setdefault("task_plan_metrics", []).append(_task_plan_metric(call, result))

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

    def checkpoint_source_owners(
        self,
        step: int,
        source_owners: list[dict[str, str | None]],
    ) -> None:
        """Record task ownership for currently active checkpoint sources."""

        self._step(step)["checkpoint_source_owners"] = source_owners

    def source_owners_after_checkpoint(
        self,
        step: int,
        *,
        checkpoint_key: str | None,
        source_owners: list[dict[str, str | None]],
    ) -> None:
        """Record unconsumed task-source owners after checkpoint creation."""

        self._step(step)["source_owners_after_checkpoint"] = {
            "checkpoint_key": checkpoint_key,
            "source_owners": source_owners,
        }

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

    def compaction_call(
        self,
        *,
        kind: str,
        attempt: int,
        step: int,
        status: str,
        duration_seconds: float,
        usage: dict[str, Any],
        error_code: str | None,
    ) -> None:
        self._trace.setdefault("compaction_calls", []).append(
            {
                "kind": kind,
                "attempt": attempt,
                "step": step,
                "status": status,
                "duration_seconds": duration_seconds,
                "usage": deepcopy(usage),
                "error_code": error_code,
            }
        )

    def compaction_retry(
        self,
        *,
        step: int,
        kind: str,
        failed_attempt: int,
        next_attempt: int,
        delay_seconds: int,
        error_code: str,
    ) -> None:
        self._trace.setdefault("compaction_retries", []).append(
            {
                "step": step,
                "kind": kind,
                "failed_attempt": failed_attempt,
                "next_attempt": next_attempt,
                "delay_seconds": delay_seconds,
                "error_code": error_code,
            }
        )

    def compaction_failed(
        self,
        *,
        step: int,
        trigger: str,
        stage: str,
        summary_kind: str | None,
        reason_code: str,
        attempt_count: int,
    ) -> None:
        self._trace.setdefault("compaction_failures", []).append(
            {
                "step": step,
                "trigger": trigger,
                "stage": stage,
                "summary_kind": summary_kind,
                "reason_code": reason_code,
                "attempt_count": attempt_count,
            }
        )

    def compaction_commit(
        self,
        *,
        step: int,
        trigger: str = "explicit",
        compaction_id: str,
        base_revision: int,
        new_revision: int,
        cut_index: int,
        source_message_count: int,
        retained_message_count: int,
        request_start_before: int,
        request_start_after: int,
    ) -> None:
        self._trace.setdefault("compaction_commits", []).append(
            {
                "step": step,
                "trigger": trigger,
                "compaction_id": compaction_id,
                "base_revision": base_revision,
                "new_revision": new_revision,
                "cut_index": cut_index,
                "source_message_count": source_message_count,
                "retained_message_count": retained_message_count,
                "request_start_before": request_start_before,
                "request_start_after": request_start_after,
            }
        )

    def context_capacity_check(
        self,
        *,
        step: int,
        stage: Literal["execution", "primary_answer", "degraded_answer"],
        phase: Literal["before_compaction", "before_model"],
        capacity: RequestCapacity,
    ) -> None:
        self._trace.setdefault("context_capacity_checks", []).append(
            {
                "step": step,
                "stage": stage,
                "phase": phase,
                "capacity": {
                    "measurement": capacity.measurement,
                    "context_bytes": capacity.context_bytes,
                    "estimated_input_tokens": capacity.estimated_input_tokens,
                    "reserved_output_tokens": capacity.reserved_output_tokens,
                    "safety_margin_tokens": capacity.safety_margin_tokens,
                    "context_window_tokens": capacity.context_window_tokens,
                    "available_input_tokens": capacity.available_input_tokens,
                    "compaction_reserve_tokens": capacity.compaction_reserve_tokens,
                    "production_trigger_input_tokens": capacity.production_trigger_input_tokens,
                    "test_trigger_percent": capacity.test_trigger_percent,
                    "trigger_input_tokens": capacity.trigger_input_tokens,
                    "pressure": capacity.pressure.value,
                },
            }
        )

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
