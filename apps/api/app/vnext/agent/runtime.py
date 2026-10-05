"""A thin native tool-calling loop with bounded, observable execution."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal

from pydantic import ValidationError

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    AnswerProjectionMode,
    AnswerResolutionMode,
    ExecutionOutcome,
    ExecutionStopReason,
    build_answer_fallback,
    build_failure_answer,
    resolve_answer,
)
from app.vnext.agent.compaction_budget import resolve_compaction_output_tokens
from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    AgentRuntimeError,
    AnswerOutputTruncated,
    CompactionFailedError,
    ContextCapacityExceeded,
    ModelContextWindowExceeded,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    CompactionFailed,
    ModelRequested,
    ModelResponded,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from app.vnext.agent.evidence_summary import CompactionSummaryResult
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    HistoryCompactionRangeError,
    build_history_compaction_request,
    build_turn_prefix_compaction_request,
    prepare_compaction,
    validate_compaction_response,
)
from app.vnext.agent.generation_recovery import build_rejected_tool_call_history
from app.vnext.agent.instructions import ANSWER_INSTRUCTION, DEGRADED_ANSWER_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.output_budget import (
    OutputBudget,
    derive_output_budget,
)
from app.vnext.agent.runtime_context import RuntimeContext, classify_time_pressure
from app.vnext.agent.runtime_prompt import render_runtime_prompt
from app.vnext.agent.task_state import TaskPlan, TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.agent.transcript_rewrite import TranscriptRewriter
from app.vnext.llm.errors import (
    ModelContextWindowError,
    ModelResponseDiagnosticError,
    ModelToolCallBatchRejected,
    ModelTransientError,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    StreamingModelClient,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.definition import ToolContextEffect
from app.vnext.tools.errors import ToolError
from app.vnext.tools.registry import ToolRegistry

EventSink = Callable[[AgentEvent], Awaitable[None] | None]

_SESSION_CONTEXT_DESCRIPTION = """\
The following session context is compressed background and recovery guidance from
an earlier part of this conversation, not a new behavioral or system
instruction. The summary may be incomplete; use it together with the current
user question and retained history. Artifact locators do not mean that the
underlying document was read and do not prove a conclusion. Use the existing
Artifact tools to read details when needed.
"""

_COMPACTION_RETRY_DELAYS_SECONDS = (1, 2, 4)
_SESSION_COMPACTION_FAILURE_CODES = frozenset(
    {
        "session_not_initialized",
        "unknown_request",
        "inactive_request",
        "stale_context_revision",
        "empty_summary",
        "invalid_effective_history",
        "empty_compaction_history",
    }
)


class _CompactionFailureDetails(Exception):
    def __init__(
        self,
        *,
        summary_kind: Literal["history", "turn_prefix"] | None,
        attempt_count: int,
        reason_code: str,
        cause: Exception,
    ) -> None:
        super().__init__(reason_code)
        self.summary_kind = summary_kind
        self.attempt_count = attempt_count
        self.reason_code = reason_code
        self.cause = cause


@dataclass(frozen=True, slots=True)
class _ModelInvocationResult:
    response: ModelResponse
    duration_seconds: float


class CancellationToken:
    """A small asyncio-compatible cancellation primitive owned by the caller."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise AgentCancelledError


class _Deadline:
    def __init__(self, seconds: float | None, *, started: float | None = None) -> None:
        self.started = monotonic() if started is None else started
        self.expires_at = self.started + seconds if seconds is not None else None

    @property
    def elapsed(self) -> float:
        return max(0.0, monotonic() - self.started)

    def remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        return self.expires_at - monotonic()

    def raise_if_expired(self) -> None:
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise AgentDeadlineExceeded


class AgentRuntime:
    """Run a model and independently registered tools in memory.

    The runtime knows only the model protocol and the generic tool registry. It
    deliberately has no session, persistence, provider, or scenario state.
    """

    def __init__(
        self,
        model: ModelClient | StreamingModelClient,
        tools: ToolRegistry,
        *,
        limits: AgentLimits | None = None,
        event_sink: EventSink | None = None,
        system_instruction: str | None = None,
        shared_instruction: str | None = None,
        transcript_rewriter: TranscriptRewriter | None = None,
        task_state_coordinator: TaskStateCoordinator | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.event_sink = event_sink
        self.system_instruction = system_instruction
        self.shared_instruction = shared_instruction
        self.transcript_rewriter = transcript_rewriter
        self.task_state_coordinator = task_state_coordinator

    def reset_request_state(self) -> None:
        """Reset stateful execution helpers before a new request."""

        if self.task_state_coordinator is not None:
            self.task_state_coordinator.reset()

    async def run(
        self,
        messages: Sequence[Message],
        *,
        cancellation_token: CancellationToken | None = None,
        event_sink: EventSink | None = None,
        trace_collector: AgentTraceCollector | None = None,
        execution_history: Any | None = None,
        request_id: Any | None = None,
        compact_before_steps: Sequence[int] = (),
    ) -> FinalMessage:
        """Run to a final message, while ``run_stream`` exposes every event."""

        final: FinalMessage | None = None
        async for event in self.run_stream(
            messages,
            cancellation_token=cancellation_token,
            event_sink=event_sink,
            trace_collector=trace_collector,
            execution_history=execution_history,
            request_id=request_id,
            compact_before_steps=compact_before_steps,
        ):
            if isinstance(event, AgentCompleted):
                final = event.final
        if final is None:
            raise AgentRuntimeError("agent stream ended without a final message")
        return final

    async def run_stream(
        self,
        messages: Sequence[Message],
        *,
        cancellation_token: CancellationToken | None = None,
        event_sink: EventSink | None = None,
        trace_collector: AgentTraceCollector | None = None,
        execution_history: Any | None = None,
        request_id: Any | None = None,
        compact_before_steps: Sequence[int] = (),
    ) -> AsyncIterator[AgentEvent]:
        """Yield ephemeral runtime events in execution order."""

        compaction_steps = _normalize_compaction_steps(compact_before_steps)
        auto_compaction_enabled = self.limits.context_window_tokens is not None
        if compaction_steps or auto_compaction_enabled:
            _validate_compaction_entry(execution_history, request_id)
        if execution_history is not None:
            self.reset_request_state()
        token = cancellation_token or CancellationToken()
        sink = event_sink
        execution_deadline = _Deadline(self.limits.deadline_seconds)
        started_at = execution_deadline.started
        step = 0
        outcome: ExecutionOutcome | None = None
        request_messages: list[Message] = []
        compaction_attempted_since_progress = False
        overflow_recovery_used = False
        answer_attempt_count = 0
        consecutive_generation_rejections = 0
        has_reliable_results = False

        def next_answer_attempt_id() -> str:
            nonlocal answer_attempt_count
            answer_attempt_count += 1
            return f"answer-{answer_attempt_count}"

        try:
            if (self.system_instruction is not None or self.shared_instruction is not None) and any(
                isinstance(message, SystemMessage) for message in messages
            ):
                raise ModelProtocolError("system messages are runtime-owned by the Runtime")
            request_messages = list(messages)
            if self.system_instruction is not None:
                request_messages.insert(0, SystemMessage(content=self.system_instruction))
            request_messages = ModelRequest(messages=request_messages, tools=[]).messages
            request_start = len(messages) + (1 if self.system_instruction is not None else 0)
            if self.transcript_rewriter is not None:
                set_scope = getattr(self.transcript_rewriter, "set_request_scope", None)
                if callable(set_scope):
                    set_scope(request_start)
            if self.task_state_coordinator is not None:
                self.task_state_coordinator.set_request_scope(request_start)
            if execution_history is not None:
                _history_set_effective(
                    execution_history,
                    _persistent_history_messages(request_messages, self.system_instruction),
                )
            if trace_collector is not None:
                trace_collector.begin(
                    request_messages,
                    [schema.model_dump(mode="json") for schema in self.tools.schemas()],
                )
            yield await self._publish(AgentStarted(), sink)

            while True:
                step += 1
                try:
                    self._check_controls(token, execution_deadline)
                except AgentDeadlineExceeded:
                    outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                    break
                explicit_compaction = step in compaction_steps
                execution_request_data = None
                compaction_trigger: str | None = None
                if auto_compaction_enabled:
                    execution_request_data = self._build_execution_request(
                        request_messages=request_messages,
                        execution_history=execution_history,
                        step=step,
                        deadline=execution_deadline,
                    )
                    candidate_request, candidate_budget = self._apply_output_budget(
                        execution_request_data[0]
                    )
                    execution_request_data = (
                        candidate_request,
                        *execution_request_data[1:],
                    )
                    candidate_capacity = assess_request_capacity(
                        candidate_request,
                        self.limits,
                        output_budget=candidate_budget,
                    )
                    assert candidate_capacity is not None
                    if explicit_compaction:
                        compaction_trigger = "explicit"
                    elif candidate_capacity.pressure.value in {"high", "critical"}:
                        compaction_trigger = "watermark"
                    if compaction_trigger is not None and trace_collector is not None:
                        trace_collector.context_capacity_check(
                            step=step,
                            stage="execution",
                            phase="before_compaction",
                            capacity=candidate_capacity,
                        )
                elif explicit_compaction:
                    compaction_trigger = "explicit"

                if compaction_trigger is not None:
                    compaction_attempted_since_progress = True
                    request_start_before = request_start
                    try:
                        compacted = await self._compact_session_history(
                            execution_history=execution_history,
                            request_id=request_id,
                            token=token,
                            deadline=execution_deadline,
                            step=step,
                            recent_history_tokens=self.limits.compaction_keep_recent_tokens,
                            max_input_bytes=self.limits.compaction_max_input_bytes,
                            trace_collector=trace_collector,
                            trigger=compaction_trigger,
                            stage="execution",
                        )
                    except AgentCancelledError:
                        raise
                    except AgentDeadlineExceeded:
                        outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                        break
                    except AgentRuntimeError:
                        raise
                    except Exception as exc:
                        raise AgentRuntimeError(
                            f"session compaction failed: {exc}",
                            details={"code": getattr(exc, "code", type(exc).__name__)},
                        ) from exc
                    if compacted:
                        request_start, request_messages = self._rebuild_after_compaction(
                            execution_history=execution_history,
                            request_id=request_id,
                            request_start=request_start,
                            request_start_before=request_start_before,
                            step=step,
                            trigger=compaction_trigger,
                            trace_collector=trace_collector,
                        )
                    execution_request_data = None

                if execution_request_data is None:
                    execution_request_data = self._build_execution_request(
                        request_messages=request_messages,
                        execution_history=execution_history,
                        step=step,
                        deadline=execution_deadline,
                    )
                (
                    request,
                    runtime_context,
                    conversation_messages,
                    task_context_messages,
                    task_context_payload,
                ) = execution_request_data
                request, output_budget = self._apply_output_budget(request)
                execution_request_data = (
                    request,
                    runtime_context,
                    conversation_messages,
                    task_context_messages,
                    task_context_payload,
                )
                if auto_compaction_enabled:
                    final_capacity = assess_request_capacity(
                        request,
                        self.limits,
                        output_budget=output_budget,
                    )
                    assert final_capacity is not None
                    if trace_collector is not None:
                        trace_collector.context_capacity_check(
                            step=step,
                            stage="execution",
                            phase="before_model",
                            capacity=final_capacity,
                        )
                    if final_capacity.pressure.value == "critical":
                        outcome = ExecutionOutcome(
                            ExecutionStopReason.CONTEXT_CAPACITY,
                            step,
                        )
                        break
                recovery_pending = False
                correction_requested = False
                while True:
                    if trace_collector is not None:
                        trace_collector.model_request(
                            request,
                            runtime_context=runtime_context,
                            conversation_messages=conversation_messages,
                            task_context_messages=task_context_messages,
                            task_context_payload=task_context_payload,
                            output_budget=output_budget,
                        )
                    yield await self._publish(
                        ModelRequested(
                            step=step,
                            message_count=len(request.messages),
                            tool_count=len(request.tools),
                        ),
                        sink,
                    )

                    try:
                        response, duration = await self._invoke_model(
                            request,
                            purpose="execution",
                            token=token,
                            deadline=execution_deadline,
                            step=step,
                            trace_collector=trace_collector,
                            publish_text=False,
                            output_budget=output_budget,
                        )
                        consecutive_generation_rejections = 0
                    except AgentCancelledError:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=step,
                                stage="execution",
                                status="cancelled",
                                error_code=AgentCancelledError.code,
                            )
                        raise
                    except AgentDeadlineExceeded:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=step,
                                stage="execution",
                                status="deadline_exceeded",
                                error_code=AgentDeadlineExceeded.code,
                            )
                        outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                        break
                    except ModelContextWindowExceeded as overflow_error:
                        if recovery_pending:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="retry_failed",
                                    error_code=overflow_error.code,
                                )
                            recovery_pending = False
                            raise
                        if not auto_compaction_enabled or overflow_recovery_used:
                            raise

                        overflow_recovery_used = True
                        recovery_pending = True
                        compaction_attempted_since_progress = True
                        request_start_before = request_start
                        try:
                            self._check_controls(token, execution_deadline)
                            compacted = await self._compact_session_history(
                                execution_history=execution_history,
                                request_id=request_id,
                                token=token,
                                deadline=execution_deadline,
                                step=step,
                                recent_history_tokens=self.limits.compaction_keep_recent_tokens,
                                max_input_bytes=self.limits.compaction_max_input_bytes,
                                trace_collector=trace_collector,
                                trigger="overflow",
                                stage="execution",
                            )
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                            break
                        except AgentRuntimeError as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="compaction_failed",
                                    error_code=getattr(
                                        recovery_error,
                                        "code",
                                        type(recovery_error).__name__,
                                    ),
                                )
                            recovery_pending = False
                            raise
                        except Exception as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="compaction_failed",
                                    error_code=getattr(
                                        recovery_error,
                                        "code",
                                        type(recovery_error).__name__,
                                    ),
                                )
                            recovery_pending = False
                            raise AgentRuntimeError(
                                f"session compaction failed: {recovery_error}",
                                details={
                                    "code": getattr(
                                        recovery_error,
                                        "code",
                                        type(recovery_error).__name__,
                                    )
                                },
                            ) from recovery_error

                        if not compacted:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="no_compactable_range",
                                    error_code=overflow_error.code,
                                )
                            recovery_pending = False
                            raise overflow_error

                        try:
                            request_start, request_messages = self._rebuild_after_compaction(
                                execution_history=execution_history,
                                request_id=request_id,
                                request_start=request_start,
                                request_start_before=request_start_before,
                                step=step,
                                trigger="overflow",
                                trace_collector=trace_collector,
                            )
                            self._check_controls(token, execution_deadline)
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                            break
                        except AgentRuntimeError as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="compaction_failed",
                                    error_code=recovery_error.code,
                                )
                            recovery_pending = False
                            raise
                        except Exception as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="compaction_failed",
                                    error_code=getattr(
                                        recovery_error,
                                        "code",
                                        type(recovery_error).__name__,
                                    ),
                                )
                            recovery_pending = False
                            raise
                        (
                            request,
                            runtime_context,
                            conversation_messages,
                            task_context_messages,
                            task_context_payload,
                        ) = self._build_execution_request(
                            request_messages=request_messages,
                            execution_history=execution_history,
                            step=step,
                            deadline=execution_deadline,
                        )
                        request, output_budget = self._apply_output_budget(request)
                        final_capacity = assess_request_capacity(
                            request,
                            self.limits,
                            output_budget=output_budget,
                        )
                        assert final_capacity is not None
                        if trace_collector is not None:
                            trace_collector.context_capacity_check(
                                step=step,
                                stage="execution",
                                phase="before_model",
                                capacity=final_capacity,
                            )
                        if final_capacity.pressure.value == "critical":
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="capacity_exceeded",
                                    error_code=ContextCapacityExceeded.code,
                                )
                            recovery_pending = False
                            outcome = ExecutionOutcome(
                                ExecutionStopReason.CONTEXT_CAPACITY,
                                step,
                            )
                            break
                        try:
                            self._check_controls(token, execution_deadline)
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=step,
                                    stage="execution",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                            break
                        if trace_collector is not None:
                            trace_collector.archive_failed_model_attempt(
                                step,
                                error_code=overflow_error.code,
                            )
                        continue
                    except ModelProviderError as model_error:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=step,
                                stage="execution",
                                status="retry_failed",
                                error_code=model_error.code,
                            )
                        recovery_pending = False
                        rejected = model_error.cause
                        if not isinstance(rejected, ModelToolCallBatchRejected):
                            raise
                        try:
                            self._check_controls(token, execution_deadline)
                        except AgentDeadlineExceeded:
                            outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                            break

                        batch = rejected.batch
                        rejected_assistant, rejected_results = build_rejected_tool_call_history(
                            batch
                        )
                        group: list[Message] = [rejected_assistant, *rejected_results]
                        request_messages.extend(group)
                        if execution_history is not None and request_id is not None:
                            execution_history.record(
                                request_id,
                                rejected_assistant,
                                kind="assistant_rejected",
                            )
                            for result in rejected_results:
                                execution_history.record(
                                    request_id,
                                    result,
                                    kind="tool_result",
                                )
                            _history_set_effective(
                                execution_history,
                                _persistent_history_messages(
                                    request_messages,
                                    self.system_instruction,
                                ),
                            )
                        consecutive_generation_rejections += 1
                        next_action: Literal["correct", "finalize"] = (
                            "correct"
                            if consecutive_generation_rejections <= 2
                            else "finalize"
                        )
                        if trace_collector is not None:
                            trace_collector.generation_recovery(
                                step=step,
                                reason=batch.reason,
                                call_ids=[call.id for call in batch.calls],
                                consecutive_rejections=consecutive_generation_rejections,
                                correction_attempt=consecutive_generation_rejections - 1,
                                next_action=next_action,
                            )
                        try:
                            self._check_controls(token, execution_deadline)
                        except AgentDeadlineExceeded:
                            outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                            break
                        if next_action == "correct":
                            correction_requested = True
                        else:
                            outcome = ExecutionOutcome(
                                ExecutionStopReason.GENERATION_RECOVERY_EXHAUSTED,
                                step,
                            )
                        break
                    except AgentRuntimeError as model_error:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=step,
                                stage="execution",
                                status="retry_failed",
                                error_code=model_error.code,
                            )
                        recovery_pending = False
                        raise
                    else:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=step,
                                stage="execution",
                                status="retry_succeeded",
                                error_code=None,
                            )
                        recovery_pending = False
                        break

                if outcome is not None:
                    break
                if correction_requested:
                    continue
                assistant = response.message
                if execution_history is not None and request_id is not None:
                    execution_history.record(
                        request_id,
                        assistant,
                        kind=(
                            "execution_final"
                            if isinstance(assistant, FinalMessage)
                            else "assistant_tool_call"
                        ),
                    )
                if trace_collector is not None:
                    trace_collector.model_response(step, response, duration)
                yield await self._publish(
                    ModelResponded(
                        step=step,
                        has_tool_calls=isinstance(assistant, AssistantMessage)
                        and bool(assistant.tool_calls),
                        duration=duration,
                    ),
                    sink,
                )

                if isinstance(assistant, FinalMessage):
                    outcome = ExecutionOutcome(ExecutionStopReason.MODEL_DONE, step)
                    break
                calls = assistant.tool_calls
                if not calls:
                    raise ModelProtocolError(
                        "execution model response had neither content nor tool calls"
                    )
                results: list[ToolResultMessage] = []
                try:
                    async for tool_event in self._execute_tools_stream(
                        calls,
                        step,
                        token,
                        execution_deadline,
                        sink,
                        results,
                        trace_collector,
                        execution_history=execution_history,
                        request_id=request_id,
                    ):
                        yield tool_event
                    self._check_controls(token, execution_deadline)
                except AgentDeadlineExceeded:
                    has_reliable_results = has_reliable_results or _has_reliable_tool_results(
                        calls,
                        results,
                    )
                    outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                    break
                has_reliable_results = has_reliable_results or _has_reliable_tool_results(
                    calls,
                    results,
                )
                candidate_messages = [*request_messages, assistant, *results]
                if self.transcript_rewriter is None:
                    request_messages = candidate_messages
                else:
                    rewrite = self.transcript_rewriter.rewrite(candidate_messages)
                    request_messages = rewrite.messages
                    for event in rewrite.events:
                        if trace_collector is not None:
                            trace_collector.transcript_rewrite(step, event)
                if execution_history is not None:
                    _history_set_effective(
                        execution_history,
                        _persistent_history_messages(request_messages, self.system_instruction),
                    )
                compaction_attempted_since_progress = False
                if (
                    self.task_state_coordinator is not None
                    and self.task_state_coordinator.plan_snapshot() is not None
                    and self.task_state_coordinator.plan_snapshot().current_key is None
                ):
                    outcome = ExecutionOutcome(ExecutionStopReason.PLAN_COMPLETE, step)
                    break

            if outcome is None:
                raise AgentRuntimeError("execution loop exited without a stop reason")
            plan_complete = (
                self.task_state_coordinator is not None
                and self.task_state_coordinator.plan_snapshot() is not None
                and self.task_state_coordinator.plan_snapshot().current_key is None
            )
            if trace_collector is not None:
                trace_collector.execution_outcome(outcome, plan_complete=plan_complete)

            resolution = resolve_answer(
                outcome=outcome,
                task_state_coordinator=self.task_state_coordinator,
                has_reliable_results=has_reliable_results,
            )
            if trace_collector is not None:
                trace_collector.answer_resolution(
                    resolution,
                    execution_reason=outcome.reason,
                )
            answer_step = step + 1
            yield await self._publish(AnswerStageStarted(step=answer_step), sink)
            if resolution.mode is AnswerResolutionMode.FAILURE:
                attempt_id = next_answer_attempt_id()
                yield await self._publish(
                    AnswerAttemptStarted(
                        step=answer_step,
                        attempt_id=attempt_id,
                        answer_kind="deterministic",
                    ),
                    sink,
                )
                final = build_failure_answer(resolution, outcome)
                if execution_history is not None and request_id is not None:
                    _record_delivery(
                        execution_history,
                        request_id,
                        final,
                        request_messages,
                        self.system_instruction,
                    )
                if trace_collector is not None:
                    trace_collector.terminal(
                        status="completed",
                        error_code=None,
                        error_message=None,
                    )
                yield await self._publish(
                    AgentCompleted(
                        step=answer_step,
                        duration=max(0.0, monotonic() - started_at),
                        final=final,
                        attempt_id=attempt_id,
                    ),
                    sink,
                )
                return

            answer_context_builder = AnswerContextBuilder()
            answer_deadline = _Deadline(self.limits.answer_timeout_seconds)
            primary_started = monotonic()
            primary_attempt_id = next_answer_attempt_id()
            primary_attempt_failed = False
            yield await self._publish(
                AnswerAttemptStarted(
                    step=answer_step,
                    attempt_id=primary_attempt_id,
                    answer_kind="primary",
                ),
                sink,
            )
            try:
                primary_context = answer_context_builder.build(
                    execution_messages=request_messages,
                    outcome=outcome,
                    task_state_coordinator=self.task_state_coordinator,
                    resolution=resolution,
                    projection_mode=AnswerProjectionMode.PRIMARY,
                    effective_history_embedded=True,
                )
                answer_messages = _project_answer_messages(
                    request_messages,
                    execution_history,
                    self.system_instruction,
                )
                answer_request = self._build_stage_answer_request(
                    instruction=ANSWER_INSTRUCTION,
                    messages=answer_messages,
                    context=primary_context,
                    step=answer_step,
                    deadline=answer_deadline,
                )
                answer_request, answer_output_budget = self._apply_output_budget(
                    answer_request
                )
                if auto_compaction_enabled:
                    primary_capacity = assess_request_capacity(
                        answer_request,
                        self.limits,
                        output_budget=answer_output_budget,
                    )
                    assert primary_capacity is not None
                    if (
                        primary_capacity.pressure.value in {"high", "critical"}
                        and not compaction_attempted_since_progress
                    ):
                        compaction_attempted_since_progress = True
                        if trace_collector is not None:
                            trace_collector.context_capacity_check(
                                step=answer_step,
                                stage="primary_answer",
                                phase="before_compaction",
                                capacity=primary_capacity,
                            )
                        request_start_before = request_start
                        compacted = await self._compact_session_history(
                            execution_history=execution_history,
                            request_id=request_id,
                            token=token,
                            deadline=answer_deadline,
                            step=answer_step,
                            recent_history_tokens=(self.limits.compaction_keep_recent_tokens),
                            max_input_bytes=self.limits.compaction_max_input_bytes,
                            trace_collector=trace_collector,
                            trigger="watermark",
                            stage="primary_answer",
                        )
                        if compacted:
                            request_start, request_messages = self._rebuild_after_compaction(
                                execution_history=execution_history,
                                request_id=request_id,
                                request_start=request_start,
                                request_start_before=request_start_before,
                                step=answer_step,
                                trigger="watermark",
                                trace_collector=trace_collector,
                            )
                            primary_context = answer_context_builder.build(
                                execution_messages=request_messages,
                                outcome=outcome,
                                task_state_coordinator=self.task_state_coordinator,
                                resolution=resolution,
                                projection_mode=AnswerProjectionMode.PRIMARY,
                                effective_history_embedded=True,
                            )
                            answer_messages = _project_answer_messages(
                                request_messages,
                                execution_history,
                                self.system_instruction,
                            )
                            answer_request = self._build_stage_answer_request(
                                instruction=ANSWER_INSTRUCTION,
                                messages=answer_messages,
                                context=primary_context,
                                step=answer_step,
                                deadline=answer_deadline,
                            )
                            answer_request, answer_output_budget = self._apply_output_budget(
                                answer_request
                            )
                    self._check_controls(token, answer_deadline)
                    final_capacity = assess_request_capacity(
                        answer_request,
                        self.limits,
                        output_budget=answer_output_budget,
                    )
                    assert final_capacity is not None
                    if trace_collector is not None:
                        trace_collector.context_capacity_check(
                            step=answer_step,
                            stage="primary_answer",
                            phase="before_model",
                            capacity=final_capacity,
                        )
                    if final_capacity.pressure.value == "critical":
                        raise ContextCapacityExceeded(
                            "answer request exceeds the configured context budget"
                        )
                self._check_controls(token, answer_deadline)
                recovery_pending = False
                while True:
                    if trace_collector is not None:
                        trace_collector.model_request(
                            answer_request,
                            output_budget=answer_output_budget,
                        )
                        trace_collector.answer_stage(answer_request, primary_context)
                        trace_collector.answer_projection(
                            answer_request,
                            primary_context,
                            kind="primary",
                            resolution=resolution,
                        )
                    yield await self._publish(
                        ModelRequested(
                            step=answer_step,
                            message_count=len(answer_request.messages),
                            tool_count=0,
                        ),
                        sink,
                    )
                    try:
                        invocation_result: _ModelInvocationResult | None = None
                        async with aclosing(
                            self._stream_model_invocation(
                                answer_request,
                                purpose="primary_answer",
                                token=token,
                                deadline=answer_deadline,
                                step=answer_step,
                                trace_collector=trace_collector,
                                publish_text=True,
                                answer_attempt_id=primary_attempt_id,
                                output_budget=answer_output_budget,
                            )
                        ) as invocation_stream:
                            async for invocation_item in invocation_stream:
                                if isinstance(invocation_item, TextDelta):
                                    yield await self._publish(invocation_item, sink)
                                elif invocation_result is not None:
                                    raise ModelProtocolError(
                                        "model invocation emitted more than one result"
                                    )
                                else:
                                    invocation_result = invocation_item
                        if invocation_result is None:
                            raise ModelProtocolError(
                                "model invocation ended without a result"
                            )
                        response = invocation_result.response
                        duration = invocation_result.duration_seconds
                    except AgentCancelledError:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=answer_step,
                                stage="primary_answer",
                                status="cancelled",
                                error_code=AgentCancelledError.code,
                            )
                        raise
                    except AgentDeadlineExceeded:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=answer_step,
                                stage="primary_answer",
                                status="deadline_exceeded",
                                error_code=AgentDeadlineExceeded.code,
                            )
                        raise
                    except ModelContextWindowExceeded as overflow_error:
                        if recovery_pending:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="retry_failed",
                                    error_code=overflow_error.code,
                                )
                            recovery_pending = False
                            raise
                        if not auto_compaction_enabled or overflow_recovery_used:
                            raise

                        yield await self._publish(
                            AnswerAttemptFailed(
                                step=answer_step,
                                attempt_id=primary_attempt_id,
                                error_code=overflow_error.code,
                            ),
                            sink,
                        )
                        primary_attempt_failed = True
                        overflow_recovery_used = True
                        recovery_pending = True
                        compaction_attempted_since_progress = True
                        request_start_before = request_start
                        try:
                            self._check_controls(token, answer_deadline)
                            compacted = await self._compact_session_history(
                                execution_history=execution_history,
                                request_id=request_id,
                                token=token,
                                deadline=answer_deadline,
                                step=answer_step,
                                recent_history_tokens=(self.limits.compaction_keep_recent_tokens),
                                max_input_bytes=self.limits.compaction_max_input_bytes,
                                trace_collector=trace_collector,
                                trigger="overflow",
                                stage="primary_answer",
                            )
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            raise
                        except Exception as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="compaction_failed",
                                    error_code=getattr(
                                        recovery_error,
                                        "code",
                                        type(recovery_error).__name__,
                                    ),
                                )
                            recovery_pending = False
                            raise

                        if not compacted:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="no_compactable_range",
                                    error_code=overflow_error.code,
                                )
                            recovery_pending = False
                            raise overflow_error

                        try:
                            request_start, request_messages = self._rebuild_after_compaction(
                                execution_history=execution_history,
                                request_id=request_id,
                                request_start=request_start,
                                request_start_before=request_start_before,
                                step=answer_step,
                                trigger="overflow",
                                trace_collector=trace_collector,
                            )
                            self._check_controls(token, answer_deadline)
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentRuntimeError as recovery_error:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="compaction_failed",
                                    error_code=recovery_error.code,
                                )
                            recovery_pending = False
                            raise

                        primary_context = answer_context_builder.build(
                            execution_messages=request_messages,
                            outcome=outcome,
                            task_state_coordinator=self.task_state_coordinator,
                            resolution=resolution,
                            projection_mode=AnswerProjectionMode.PRIMARY,
                            effective_history_embedded=True,
                        )
                        answer_messages = _project_answer_messages(
                            request_messages,
                            execution_history,
                            self.system_instruction,
                        )
                        answer_request = self._build_stage_answer_request(
                            instruction=ANSWER_INSTRUCTION,
                            messages=answer_messages,
                            context=primary_context,
                            step=answer_step,
                            deadline=answer_deadline,
                        )
                        answer_request, answer_output_budget = self._apply_output_budget(
                            answer_request
                        )
                        try:
                            self._check_controls(token, answer_deadline)
                        except AgentCancelledError:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="cancelled",
                                    error_code=AgentCancelledError.code,
                                )
                            recovery_pending = False
                            raise
                        except AgentDeadlineExceeded:
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="deadline_exceeded",
                                    error_code=AgentDeadlineExceeded.code,
                                )
                            recovery_pending = False
                            raise
                        final_capacity = assess_request_capacity(
                            answer_request,
                            self.limits,
                            output_budget=answer_output_budget,
                        )
                        assert final_capacity is not None
                        if trace_collector is not None:
                            trace_collector.context_capacity_check(
                                step=answer_step,
                                stage="primary_answer",
                                phase="before_model",
                                capacity=final_capacity,
                            )
                        if final_capacity.pressure.value == "critical":
                            if trace_collector is not None:
                                trace_collector.overflow_recovery(
                                    step=answer_step,
                                    stage="primary_answer",
                                    status="capacity_exceeded",
                                    error_code=ContextCapacityExceeded.code,
                                )
                            recovery_pending = False
                            raise ContextCapacityExceeded(
                                "answer request exceeds the configured context budget"
                            ) from None
                        if trace_collector is not None:
                            trace_collector.archive_failed_model_attempt(
                                answer_step,
                                error_code=overflow_error.code,
                            )
                        primary_attempt_id = next_answer_attempt_id()
                        primary_attempt_failed = False
                        yield await self._publish(
                            AnswerAttemptStarted(
                                step=answer_step,
                                attempt_id=primary_attempt_id,
                                answer_kind="primary",
                            ),
                            sink,
                        )
                        continue
                    except AgentRuntimeError as model_error:
                        if recovery_pending and trace_collector is not None:
                            trace_collector.overflow_recovery(
                                step=answer_step,
                                stage="primary_answer",
                                status="retry_failed",
                                error_code=model_error.code,
                            )
                        recovery_pending = False
                        raise
                    else:
                        break
                answer = response.message
                if not isinstance(answer, FinalMessage):
                    if recovery_pending and trace_collector is not None:
                        trace_collector.overflow_recovery(
                            step=answer_step,
                            stage="primary_answer",
                            status="retry_failed",
                            error_code=ModelProtocolError.code,
                        )
                    recovery_pending = False
                    if trace_collector is not None:
                        trace_collector.model_response(answer_step, response, duration)
                    yield await self._publish(
                        ModelResponded(
                            step=answer_step,
                            has_tool_calls=bool(answer.tool_calls),
                            duration=duration,
                        ),
                        sink,
                    )
                    raise ModelProtocolError("answer stage model requested tools")
                if recovery_pending and trace_collector is not None:
                    trace_collector.overflow_recovery(
                        step=answer_step,
                        stage="primary_answer",
                        status="retry_succeeded",
                        error_code=None,
                    )
                recovery_pending = False
                if trace_collector is not None:
                    trace_collector.model_response(answer_step, response, duration)
                yield await self._publish(
                    ModelResponded(
                        step=answer_step,
                        has_tool_calls=False,
                        duration=duration,
                    ),
                    sink,
                )
            except (
                AgentDeadlineExceeded,
                ContextCapacityExceeded,
                ModelProviderError,
                ModelProtocolError,
            ) as exc:
                answer_capacity_exhausted = isinstance(exc, ContextCapacityExceeded)
                if not primary_attempt_failed:
                    yield await self._publish(
                        AnswerAttemptFailed(
                            step=answer_step,
                            attempt_id=primary_attempt_id,
                            error_code=exc.code,
                        ),
                        sink,
                    )
                    primary_attempt_failed = True
                if trace_collector is not None:
                    trace_collector.answer_attempt(
                        kind="primary",
                        step=answer_step,
                        status=_answer_attempt_status(exc),
                        duration_seconds=max(0.0, monotonic() - primary_started),
                        error_code=exc.code,
                    )

                degraded_step = answer_step + 1
                degraded_attempt_id = next_answer_attempt_id()
                yield await self._publish(
                    AnswerAttemptStarted(
                        step=degraded_step,
                        attempt_id=degraded_attempt_id,
                        answer_kind="degraded",
                    ),
                    sink,
                )
                degraded_started = monotonic()
                degraded_context = answer_context_builder.build(
                    execution_messages=request_messages,
                    outcome=outcome,
                    task_state_coordinator=self.task_state_coordinator,
                    resolution=resolution,
                    projection_mode=AnswerProjectionMode.DEGRADED,
                    effective_history_embedded=True,
                )
                degraded_request = self._build_stage_answer_request(
                    instruction=DEGRADED_ANSWER_INSTRUCTION,
                    messages=_project_answer_messages(
                        request_messages,
                        execution_history,
                        self.system_instruction,
                    ),
                    context=degraded_context,
                    step=degraded_step,
                    deadline=answer_deadline,
                )
                degraded_request, degraded_output_budget = self._apply_output_budget(
                    degraded_request
                )
                degraded_precheck_error: AgentRuntimeError | None = None
                if auto_compaction_enabled:
                    degraded_capacity = assess_request_capacity(
                        degraded_request,
                        self.limits,
                        output_budget=degraded_output_budget,
                    )
                    assert degraded_capacity is not None
                    if trace_collector is not None:
                        trace_collector.context_capacity_check(
                            step=degraded_step,
                            stage="degraded_answer",
                            phase="before_model",
                            capacity=degraded_capacity,
                        )
                    if degraded_capacity.pressure.value == "critical":
                        degraded_precheck_error = ContextCapacityExceeded(
                            "degraded answer request exceeds the configured context budget"
                        )
                if degraded_precheck_error is None:
                    try:
                        self._check_controls(token, answer_deadline)
                    except AgentDeadlineExceeded as exc:
                        degraded_precheck_error = exc
                if degraded_precheck_error is None:
                    if trace_collector is not None:
                        trace_collector.model_request(
                            degraded_request,
                            output_budget=degraded_output_budget,
                        )
                        trace_collector.answer_projection(
                            degraded_request,
                            degraded_context,
                            kind="degraded",
                            resolution=resolution,
                        )
                    yield await self._publish(
                        ModelRequested(
                            step=degraded_step,
                            message_count=len(degraded_request.messages),
                            tool_count=0,
                        ),
                        sink,
                    )
                try:
                    if degraded_precheck_error is not None:
                        raise degraded_precheck_error
                    degraded_invocation_result: _ModelInvocationResult | None = None
                    async with aclosing(
                        self._stream_model_invocation(
                            degraded_request,
                            purpose="degraded_answer",
                            token=token,
                            deadline=answer_deadline,
                            step=degraded_step,
                            trace_collector=trace_collector,
                            publish_text=True,
                            answer_attempt_id=degraded_attempt_id,
                            output_budget=degraded_output_budget,
                        )
                    ) as invocation_stream:
                        async for invocation_item in invocation_stream:
                            if isinstance(invocation_item, TextDelta):
                                yield await self._publish(invocation_item, sink)
                            elif degraded_invocation_result is not None:
                                raise ModelProtocolError(
                                    "model invocation emitted more than one result"
                                )
                            else:
                                degraded_invocation_result = invocation_item
                    if degraded_invocation_result is None:
                        raise ModelProtocolError("model invocation ended without a result")
                    degraded_response = degraded_invocation_result.response
                    degraded_duration = degraded_invocation_result.duration_seconds
                    degraded_answer = degraded_response.message
                    if not isinstance(degraded_answer, FinalMessage):
                        if trace_collector is not None:
                            trace_collector.model_response(
                                degraded_step, degraded_response, degraded_duration
                            )
                        yield await self._publish(
                            ModelResponded(
                                step=degraded_step,
                                has_tool_calls=bool(degraded_answer.tool_calls),
                                duration=degraded_duration,
                            ),
                            sink,
                        )
                        raise ModelProtocolError("answer stage model requested tools")
                    if trace_collector is not None:
                        trace_collector.model_response(
                            degraded_step, degraded_response, degraded_duration
                        )
                    yield await self._publish(
                        ModelResponded(
                            step=degraded_step,
                            has_tool_calls=False,
                            duration=degraded_duration,
                        ),
                        sink,
                    )
                    if trace_collector is not None:
                        trace_collector.answer_attempt(
                            kind="degraded",
                            step=degraded_step,
                            status="completed",
                            duration_seconds=degraded_duration,
                            error_code=None,
                        )
                        trace_collector.answer_fallback("degraded_model")
                    if trace_collector is not None:
                        trace_collector.terminal(
                            status="completed", error_code=None, error_message=None
                        )
                    if execution_history is not None and request_id is not None:
                        _record_delivery(
                            execution_history,
                            request_id,
                            degraded_answer,
                            request_messages,
                            self.system_instruction,
                        )
                    yield await self._publish(
                        AgentCompleted(
                            step=degraded_step,
                            duration=max(0.0, monotonic() - started_at),
                            final=degraded_answer,
                            attempt_id=degraded_attempt_id,
                        ),
                        sink,
                    )
                    return
                except (
                    AgentDeadlineExceeded,
                    ContextCapacityExceeded,
                    ModelProviderError,
                    ModelProtocolError,
                ) as degraded_exc:
                    yield await self._publish(
                        AnswerAttemptFailed(
                            step=degraded_step,
                            attempt_id=degraded_attempt_id,
                            error_code=degraded_exc.code,
                        ),
                        sink,
                    )
                    if trace_collector is not None:
                        trace_collector.answer_attempt(
                            kind="degraded",
                            step=degraded_step,
                            status=_answer_attempt_status(degraded_exc),
                            duration_seconds=max(0.0, monotonic() - degraded_started),
                            error_code=degraded_exc.code,
                        )
                        trace_collector.answer_fallback("deterministic")
                    deterministic_attempt_id = next_answer_attempt_id()
                    yield await self._publish(
                        AnswerAttemptStarted(
                            step=degraded_step,
                            attempt_id=deterministic_attempt_id,
                            answer_kind="deterministic",
                        ),
                        sink,
                    )
                    final = build_answer_fallback(
                        resolution,
                        outcome,
                        context_capacity_exhausted=(
                            answer_capacity_exhausted
                            or isinstance(degraded_exc, ContextCapacityExceeded)
                        ),
                    )
                    if execution_history is not None and request_id is not None:
                        _record_delivery(
                            execution_history,
                            request_id,
                            final,
                            request_messages,
                            self.system_instruction,
                        )
                    if trace_collector is not None:
                        trace_collector.terminal(
                            status="completed", error_code=None, error_message=None
                        )
                    yield await self._publish(
                        AgentCompleted(
                            step=degraded_step,
                            duration=max(0.0, monotonic() - started_at),
                            final=final,
                            attempt_id=deterministic_attempt_id,
                        ),
                        sink,
                    )
                    return
            else:
                if trace_collector is not None:
                    trace_collector.answer_attempt(
                        kind="primary",
                        step=answer_step,
                        status="completed",
                        duration_seconds=duration,
                        error_code=None,
                    )
                    trace_collector.answer_fallback("none")
                if trace_collector is not None:
                    trace_collector.terminal(
                        status="completed", error_code=None, error_message=None
                    )
                if execution_history is not None and request_id is not None:
                    _record_delivery(
                        execution_history,
                        request_id,
                        answer,
                        request_messages,
                        self.system_instruction,
                    )
                yield await self._publish(
                    AgentCompleted(
                        step=answer_step,
                        duration=max(0.0, monotonic() - started_at),
                        final=answer,
                        attempt_id=primary_attempt_id,
                    ),
                    sink,
                )
        except AgentCancelledError as exc:
            if trace_collector is not None:
                trace_collector.terminal(
                    status="cancelled", error_code=exc.code, error_message=str(exc)
                )
            event = AgentCancelled(
                step=step or None,
                error_message=str(exc),
            )
            yield await self._publish(event, sink)
            raise
        except CompactionFailedError as exc:
            if trace_collector is not None:
                trace_collector.compaction_failed(
                    step=exc.step,
                    trigger=exc.trigger,
                    stage=exc.stage,
                    summary_kind=exc.summary_kind,
                    reason_code=exc.reason_code,
                    attempt_count=exc.attempt_count,
                )
                trace_collector.terminal(
                    status="failed", error_code=exc.code, error_message=str(exc)
                )
            yield await self._publish(
                CompactionFailed(
                    step=exc.step,
                    trigger=exc.trigger,
                    stage=exc.stage,
                    summary_kind=exc.summary_kind,
                    reason_code=exc.reason_code,
                    attempt_count=exc.attempt_count,
                ),
                sink,
            )
            yield await self._publish(
                AgentFailed(
                    step=exc.step,
                    duration=max(0.0, monotonic() - started_at),
                    error_code=exc.code,
                    error_message=str(exc),
                    details=exc.details,
                ),
                sink,
            )
            raise
        except AgentRuntimeError as exc:
            if trace_collector is not None:
                trace_collector.terminal(
                    status="failed", error_code=exc.code, error_message=str(exc)
                )
            event = AgentFailed(
                step=step or None,
                duration=max(0.0, monotonic() - started_at),
                error_code=exc.code,
                error_message=str(exc),
            )
            yield await self._publish(event, sink)
            raise
        except Exception as exc:
            # Failures outside a model call are still runtime failures and must
            # never be represented as a successful tool result.
            wrapped = AgentRuntimeError(f"agent runtime failed: {exc}")
            if trace_collector is not None:
                trace_collector.terminal(
                    status="failed", error_code=wrapped.code, error_message=str(wrapped)
                )
            event = AgentFailed(
                step=step or None,
                duration=max(0.0, monotonic() - started_at),
                error_code=wrapped.code,
                error_message=str(wrapped),
            )
            yield await self._publish(event, sink)
            raise wrapped from exc

    def _build_stage_answer_request(
        self,
        *,
        instruction: str,
        messages: Sequence[Message],
        context: Any,
        step: int,
        deadline: _Deadline,
    ) -> ModelRequest:
        """Build an answer request with a fresh, ephemeral stage snapshot."""

        runtime_context = RuntimeContext.from_state(
            current_step=step,
            tools_available=False,
            time_pressure=classify_time_pressure(
                remaining_seconds=deadline.remaining(),
                budget_seconds=self.limits.answer_timeout_seconds,
            ),
        )
        return _build_answer_request(
            instruction=instruction,
            runtime_prompt=render_runtime_prompt(runtime_context, stage="answer"),
            shared_instruction=self.shared_instruction,
            messages=messages,
            context=context,
            step=step,
            max_output_tokens=None,
        )

    def _build_execution_request(
        self,
        *,
        request_messages: Sequence[Message],
        execution_history: Any | None,
        step: int,
        deadline: _Deadline,
    ) -> tuple[
        ModelRequest,
        RuntimeContext,
        list[Message],
        list[Message],
        dict[str, Any] | None,
    ]:
        """Build one complete execution request and its trace projections."""

        time_pressure = classify_time_pressure(
            remaining_seconds=deadline.remaining(),
            budget_seconds=self.limits.deadline_seconds,
        )
        runtime_context = RuntimeContext.from_state(
            current_step=step,
            tools_available=True,
            time_pressure=time_pressure,
        )
        conversation_messages = _project_session_context(
            request_messages,
            execution_history,
        )
        if self.shared_instruction is not None:
            conversation_messages = _append_system_instruction(
                conversation_messages,
                self.shared_instruction,
            )
        turn_messages = conversation_messages
        task_context_messages: list[Message] | None = None
        task_context_payload: dict[str, Any] | None = None
        if self.task_state_coordinator is not None:
            self.task_state_coordinator.refresh(request_messages)
            task_context = self.task_state_coordinator.render_context()
            if task_context is not None:
                turn_messages = _append_system_instruction(turn_messages, task_context)
                task_context_messages = turn_messages
                task_context_payload = self.task_state_coordinator.context_payload()
        turn_messages = _append_system_instruction(
            turn_messages,
            render_runtime_prompt(runtime_context),
        )
        if task_context_messages is None:
            task_context_messages = list(conversation_messages)
        request = ModelRequest(
            messages=turn_messages,
            tools=self.tools.schemas(),
            step=step,
        )
        return (
            request,
            runtime_context,
            conversation_messages,
            task_context_messages,
            task_context_payload,
        )

    def _apply_output_budget(self, request: ModelRequest) -> tuple[ModelRequest, OutputBudget]:
        budget = derive_output_budget(request, self.limits)
        max_output_tokens = budget.actual_output_tokens or None
        return request.model_copy(update={"max_output_tokens": max_output_tokens}), budget

    def _rebuild_after_compaction(
        self,
        *,
        execution_history: Any,
        request_id: Any,
        request_start: int,
        request_start_before: int,
        step: int,
        trigger: str,
        trace_collector: AgentTraceCollector | None,
    ) -> tuple[int, list[Message]]:
        """Rebuild all request-local projections after an atomic compaction."""

        record = _latest_compaction_record(execution_history, request_id)
        system_offset = 1 if self.system_instruction is not None else 0
        old_start = request_start - system_offset
        pinned = int(record.current_user_index_before < record.cut_index)
        new_start = max(0, old_start - record.cut_index) + pinned
        request_start = new_start + system_offset
        request_messages = _runtime_history_messages(
            execution_history,
            self.system_instruction,
        )
        if self.transcript_rewriter is not None:
            set_scope = getattr(self.transcript_rewriter, "set_request_scope", None)
            if callable(set_scope):
                set_scope(request_start)
        if self.task_state_coordinator is not None:
            self.task_state_coordinator.set_request_scope(request_start)
            self.task_state_coordinator.refresh(request_messages)
        if trace_collector is not None:
            trace_collector.compaction_commit(
                step=step,
                trigger=trigger,
                compaction_id=record.compaction_id,
                base_revision=record.base_revision,
                new_revision=execution_history.revision,
                cut_index=record.cut_index,
                source_message_count=record.source_message_count,
                retained_message_count=len(execution_history.effective_messages()),
                request_start_before=request_start_before,
                request_start_after=request_start,
            )
        return request_start, request_messages

    async def _stream_model_invocation(
        self,
        request: ModelRequest,
        *,
        purpose: Literal["execution", "primary_answer", "degraded_answer", "compaction"],
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
        publish_text: bool,
        output_budget: OutputBudget | None = None,
        answer_attempt_id: str | None = None,
        record_step_text: bool = True,
        on_response: Callable[[ModelResponse], None] | None = None,
    ) -> AsyncIterator[TextDelta | _ModelInvocationResult]:
        """Run one model call, forwarding answer text before its terminal response."""

        started = monotonic()
        call_id: str | None = None
        if trace_collector is not None:
            try:
                call_id = trace_collector.model_call_started(
                    request,
                    step=step,
                    purpose=purpose,
                    output_budget=output_budget,
                )
            except Exception:
                pass
        call_status: Literal["completed", "failed", "cancelled", "deadline"] = "failed"
        call_error: BaseException | None = None
        invocation_result: _ModelInvocationResult | None = None
        try:
            response: ModelResponse | None = None
            stream = getattr(self.model, "stream", None)
            if callable(stream):
                model_stream = stream(request)
                if inspect.isawaitable(model_stream):
                    model_stream = await self._await_controlled(model_stream, token, deadline)
                if not hasattr(model_stream, "__anext__"):
                    raise ModelProtocolError(
                        "streaming model client did not return an async iterator"
                    )
                try:
                    while True:
                        try:
                            item = await self._await_controlled(
                                anext(model_stream), token, deadline
                            )
                        except StopAsyncIteration:
                            break
                        if isinstance(item, ModelTextDelta):
                            if trace_collector is not None:
                                if record_step_text:
                                    trace_collector.text_delta(step, item.text)
                                try:
                                    trace_collector.model_call_text_delta(call_id, item.text)
                                except Exception:
                                    pass
                            if response is not None:
                                raise ModelProtocolError(
                                    "stream emitted text after its terminal response"
                                )
                            if publish_text:
                                if answer_attempt_id is None:
                                    raise ModelProtocolError(
                                        "answer text requires an attempt identity"
                                    )
                                yield TextDelta(
                                    step=step,
                                    text=item.text,
                                    attempt_id=answer_attempt_id,
                                )
                        elif isinstance(item, ModelResponse):
                            if response is not None:
                                raise ModelProtocolError(
                                    "stream emitted more than one terminal response"
                                )
                            response = self._normalize_response(item)
                            if trace_collector is not None:
                                try:
                                    trace_collector.model_call_response(call_id, response)
                                except Exception:
                                    pass
                            if on_response is not None:
                                on_response(response)
                        else:
                            raise ModelProtocolError("stream emitted an unsupported model item")
                finally:
                    close = getattr(model_stream, "aclose", None)
                    if callable(close):
                        close_result = close()
                        if inspect.isawaitable(close_result):
                            await close_result
                if response is None:
                    raise ModelProtocolError("stream ended without a terminal model response")
            else:
                response = self._normalize_response(
                    await self._await_controlled(self.model.complete(request), token, deadline)
                )
                if trace_collector is not None:
                    try:
                        trace_collector.model_call_response(call_id, response)
                    except Exception:
                        pass
                if on_response is not None:
                    on_response(response)

            self._check_controls(token, deadline)
            if (
                purpose in {"primary_answer", "degraded_answer"}
                and response is not None
                and isinstance(response.message, FinalMessage)
                and response.finish_reason == "length"
            ):
                raise AnswerOutputTruncated()
            call_status = "completed"
            invocation_result = _ModelInvocationResult(
                response=response,
                duration_seconds=max(0.0, monotonic() - started),
            )
        except (asyncio.CancelledError, GeneratorExit) as exc:
            call_status = "cancelled"
            call_error = exc
            raise
        except AgentCancelledError as exc:
            call_status = "cancelled"
            call_error = exc
            raise
        except AgentDeadlineExceeded as exc:
            call_status = "deadline"
            call_error = exc
            raise
        except ModelContextWindowError as exc:
            wrapped = ModelContextWindowExceeded(
                cause=exc,
                provider_code=exc.provider_code,
                status_code=exc.status_code,
            )
            call_error = wrapped
            raise wrapped from exc
        except AgentRuntimeError as exc:
            call_error = exc
            raise
        except Exception as exc:
            if (
                trace_collector is not None
                and isinstance(exc, ModelResponseDiagnosticError)
                and exc.diagnostics is not None
            ):
                try:
                    trace_collector.model_call_failure_diagnostics(
                        call_id,
                        step=step,
                        purpose=purpose,
                        diagnostics=exc.diagnostics,
                    )
                except Exception:
                    pass
            wrapped = ModelProviderError(
                f"model provider request failed: {exc}",
                cause=exc,
            )
            call_error = wrapped
            raise wrapped from exc
        finally:
            if trace_collector is not None:
                try:
                    trace_collector.model_call_finished(
                        call_id,
                        status=call_status,
                        duration_seconds=max(0.0, monotonic() - started),
                        error=call_error,
                    )
                except Exception:
                    pass

        if invocation_result is None:
            raise ModelProtocolError("model invocation ended without a result")
        yield invocation_result

    async def _invoke_model(
        self,
        request: ModelRequest,
        *,
        purpose: Literal["execution", "primary_answer", "degraded_answer", "compaction"],
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
        publish_text: bool,
        output_budget: OutputBudget | None = None,
        answer_attempt_id: str | None = None,
        record_step_text: bool = True,
        on_response: Callable[[ModelResponse], None] | None = None,
    ) -> tuple[ModelResponse, float]:
        """Consume a model invocation that must not publish answer text."""

        if publish_text:
            raise ModelProtocolError(
                "_invoke_model cannot publish text; consume _stream_model_invocation instead"
            )
        invocation_result: _ModelInvocationResult | None = None
        async with aclosing(
            self._stream_model_invocation(
                request,
                purpose=purpose,
                token=token,
                deadline=deadline,
                step=step,
                trace_collector=trace_collector,
                publish_text=False,
                output_budget=output_budget,
                answer_attempt_id=answer_attempt_id,
                record_step_text=record_step_text,
                on_response=on_response,
            )
        ) as invocation_stream:
            async for invocation_item in invocation_stream:
                if isinstance(invocation_item, TextDelta):
                    raise ModelProtocolError(
                        "non-answer model invocation produced a text event"
                    )
                if invocation_result is not None:
                    raise ModelProtocolError("model invocation emitted more than one result")
                invocation_result = invocation_item
        if invocation_result is None:
            raise ModelProtocolError("model invocation ended without a result")
        return invocation_result.response, invocation_result.duration_seconds

    async def _generate_compaction_summary(
        self,
        request: ModelRequest,
        *,
        kind: Literal["history", "turn_prefix"] = "history",
        attempt: int = 1,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
    ) -> CompactionSummaryResult:
        """Generate one validated summary candidate without committing it."""

        self._check_controls(token, deadline)
        _validate_compaction_call(request, kind=kind)
        started = monotonic()
        usage: dict[str, Any] = {}

        def capture_response(received: ModelResponse) -> None:
            nonlocal usage
            usage = deepcopy(received.usage)

        try:
            response, _ = await self._invoke_model(
                request,
                purpose="compaction",
                token=token,
                deadline=deadline,
                step=step,
                trace_collector=trace_collector,
                publish_text=False,
                record_step_text=False,
                on_response=capture_response,
            )
            self._check_controls(token, deadline)
            summary = validate_compaction_response(response)
            self._check_controls(token, deadline)
            duration_seconds = max(0.0, monotonic() - started)
            result = CompactionSummaryResult(
                summary=summary,
                usage=usage,
                duration_seconds=duration_seconds,
            )
            if trace_collector is not None:
                trace_collector.compaction_call(
                    kind=kind,
                    attempt=attempt,
                    step=step,
                    status="generated",
                    duration_seconds=duration_seconds,
                    usage=result.usage,
                    error_code=None,
                )
            return result
        except AgentCancelledError as exc:
            self._record_compaction_call(
                trace_collector,
                kind=kind,
                attempt=attempt,
                step=step,
                status="cancelled",
                started=started,
                usage=usage,
                error_code=exc.code,
            )
            raise
        except AgentDeadlineExceeded as exc:
            self._record_compaction_call(
                trace_collector,
                kind=kind,
                attempt=attempt,
                step=step,
                status="deadline_exceeded",
                started=started,
                usage=usage,
                error_code=exc.code,
            )
            raise
        except Exception as exc:
            self._record_compaction_call(
                trace_collector,
                kind=kind,
                attempt=attempt,
                step=step,
                status="failed",
                started=started,
                usage=usage,
                error_code=getattr(exc, "code", None),
            )
            raise

    async def _generate_compaction_summary_with_retry(
        self,
        request: ModelRequest,
        *,
        kind: Literal["history", "turn_prefix"],
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
    ) -> CompactionSummaryResult:
        max_attempts = self.limits.compaction_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            self._check_controls(token, deadline)
            try:
                return await self._generate_compaction_summary(
                    request,
                    kind=kind,
                    attempt=attempt,
                    token=token,
                    deadline=deadline,
                    step=step,
                    trace_collector=trace_collector,
                )
            except (AgentCancelledError, AgentDeadlineExceeded, asyncio.CancelledError):
                raise
            except ModelProviderError as exc:
                is_transient = isinstance(exc.cause, ModelTransientError)
                if is_transient and attempt < max_attempts:
                    delay_seconds = _COMPACTION_RETRY_DELAYS_SECONDS[attempt - 1]
                    if trace_collector is not None:
                        trace_collector.compaction_retry(
                            step=step,
                            kind=kind,
                            failed_attempt=attempt,
                            next_attempt=attempt + 1,
                            delay_seconds=delay_seconds,
                            error_code=exc.code,
                        )
                    await self._await_controlled(
                        asyncio.sleep(delay_seconds),
                        token,
                        deadline,
                    )
                    self._check_controls(token, deadline)
                    continue
                reason_code = "transient_retries_exhausted" if is_transient else exc.code
                failure = _CompactionFailureDetails(
                    summary_kind=kind,
                    attempt_count=attempt,
                    reason_code=reason_code,
                    cause=exc,
                )
                raise failure from exc
            except (CompactionSummaryError, ModelProtocolError) as exc:
                failure = _CompactionFailureDetails(
                    summary_kind=kind,
                    attempt_count=attempt,
                    reason_code=getattr(exc, "code", "invalid_summary_response"),
                    cause=exc,
                )
                raise failure from exc
        raise AssertionError("summary retry loop exited without a result or failure")

    async def _compact_session_history(
        self,
        *,
        execution_history: Any,
        request_id: Any,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        recent_history_tokens: int,
        max_input_bytes: int,
        trace_collector: AgentTraceCollector | None,
        trigger: Literal["explicit", "watermark", "overflow"] = "explicit",
        stage: Literal["execution", "primary_answer"] = "execution",
    ) -> bool:
        """Generate and atomically commit one session-history compaction."""

        try:
            return await self._compact_session_history_candidate(
                execution_history=execution_history,
                request_id=request_id,
                token=token,
                deadline=deadline,
                step=step,
                recent_history_tokens=recent_history_tokens,
                max_input_bytes=max_input_bytes,
                trace_collector=trace_collector,
            )
        except (AgentCancelledError, AgentDeadlineExceeded, asyncio.CancelledError):
            raise
        except _CompactionFailureDetails as exc:
            raise CompactionFailedError(
                step=step,
                trigger=trigger,
                stage=stage,
                summary_kind=exc.summary_kind,
                reason_code=exc.reason_code,
                attempt_count=exc.attempt_count,
                cause=exc.cause,
            ) from exc.cause
        except (CompactionSummaryError, HistoryCompactionRangeError, ModelProtocolError) as exc:
            raise CompactionFailedError(
                step=step,
                trigger=trigger,
                stage=stage,
                summary_kind=None,
                reason_code=getattr(exc, "code", "invalid_compaction_input"),
                attempt_count=0,
                cause=exc,
            ) from exc
        except ValueError as exc:
            reason_code = getattr(exc, "code", None)
            if reason_code not in _SESSION_COMPACTION_FAILURE_CODES:
                raise
            raise CompactionFailedError(
                step=step,
                trigger=trigger,
                stage=stage,
                summary_kind=None,
                reason_code=reason_code,
                attempt_count=0,
                cause=exc,
            ) from exc

    async def _compact_session_history_candidate(
        self,
        *,
        execution_history: Any,
        request_id: Any,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        recent_history_tokens: int,
        max_input_bytes: int,
        trace_collector: AgentTraceCollector | None,
    ) -> bool:

        self._check_controls(token, deadline)
        if type(recent_history_tokens) is not int or recent_history_tokens <= 0:
            raise HistoryCompactionRangeError("invalid_recent_history_budget")
        if type(max_input_bytes) is not int or max_input_bytes <= 0:
            raise CompactionSummaryError("invalid_summary_budget")
        snapshot_method = getattr(execution_history, "context_snapshot", None)
        if not callable(snapshot_method):
            raise ModelProtocolError("execution history does not provide a context snapshot")
        snapshot = snapshot_method()
        if not getattr(execution_history, "initialized", False):
            raise ModelProtocolError("execution history is not initialized")
        if snapshot.current_request_id != request_id:
            raise ModelProtocolError("execution history request does not match the active request")
        current_index = snapshot.current_user_index
        current_user = snapshot.current_user_message
        if (
            current_user is None
            or type(current_index) is not int
            or current_index < 0
            or current_index >= len(snapshot.messages)
            or snapshot.messages[current_index] != current_user
            or not isinstance(snapshot.messages[current_index], UserMessage)
        ):
            raise ModelProtocolError("execution history has no valid current user message")

        preparation = prepare_compaction(
            snapshot.messages,
            recent_history_tokens=recent_history_tokens,
            bytes_per_token=self.limits.context_estimate_bytes_per_token,
        )
        if preparation is None:
            return False

        removable_message_count = preparation.cut_index - (
            1 if current_index < preparation.cut_index else 0
        )
        if removable_message_count < 1:
            return False

        # Build and validate every request before spending a model call. A bad
        # second-stage payload must not leave a first-stage candidate behind.
        history_request: ModelRequest | None = None
        turn_prefix_request: ModelRequest | None = None
        if preparation.history_messages:
            try:
                history_output_tokens = resolve_compaction_output_tokens(
                    kind="history",
                    reserve_tokens=self.limits.compaction_reserve_tokens,
                    model_max_output_tokens=self.limits.compaction_model_max_output_tokens,
                )
                history_request = build_history_compaction_request(
                    previous_summary=snapshot.summary,
                    history_messages=preparation.history_messages,
                    max_input_bytes=max_input_bytes,
                    max_output_tokens=history_output_tokens,
                )
                _validate_compaction_call(history_request, kind="history")
            except (CompactionSummaryError, ModelProtocolError) as exc:
                raise _CompactionFailureDetails(
                    summary_kind="history",
                    attempt_count=0,
                    reason_code=getattr(exc, "code", "invalid_compaction_request"),
                    cause=exc,
                ) from exc
        if preparation.turn_prefix_messages:
            try:
                turn_prefix_output_tokens = resolve_compaction_output_tokens(
                    kind="turn_prefix",
                    reserve_tokens=self.limits.compaction_reserve_tokens,
                    model_max_output_tokens=self.limits.compaction_model_max_output_tokens,
                )
                turn_prefix_request = build_turn_prefix_compaction_request(
                    turn_prefix_messages=preparation.turn_prefix_messages,
                    max_input_bytes=max_input_bytes,
                    max_output_tokens=turn_prefix_output_tokens,
                )
                _validate_compaction_call(turn_prefix_request, kind="turn_prefix")
            except (CompactionSummaryError, ModelProtocolError) as exc:
                raise _CompactionFailureDetails(
                    summary_kind="turn_prefix",
                    attempt_count=0,
                    reason_code=getattr(exc, "code", "invalid_compaction_request"),
                    cause=exc,
                ) from exc
        if history_request is None and turn_prefix_request is None:
            return False

        history_summary = snapshot.summary
        if history_request is not None:
            history_result = await self._generate_compaction_summary_with_retry(
                history_request,
                kind="history",
                token=token,
                deadline=deadline,
                step=step,
                trace_collector=trace_collector,
            )
            history_summary = history_result.summary
            self._check_controls(token, deadline)

        candidate_summary = history_summary
        if turn_prefix_request is not None:
            turn_prefix_result = await self._generate_compaction_summary_with_retry(
                turn_prefix_request,
                kind="turn_prefix",
                token=token,
                deadline=deadline,
                step=step,
                trace_collector=trace_collector,
            )
            turn_prefix = f"**Turn Context (split turn):**\n\n{turn_prefix_result.summary}"
            candidate_summary = (
                f"{candidate_summary}\n\n---\n\n{turn_prefix}" if candidate_summary else turn_prefix
            )
            self._check_controls(token, deadline)
        if not candidate_summary:
            return False

        self._check_controls(token, deadline)
        try:
            execution_history.commit_compaction(
                request_id=request_id,
                base_revision=snapshot.revision,
                summary=candidate_summary,
                cut_index=preparation.cut_index,
            )
        except ValueError as exc:
            reason_code = getattr(exc, "code", None)
            if reason_code not in _SESSION_COMPACTION_FAILURE_CODES:
                raise
            raise _CompactionFailureDetails(
                summary_kind=None,
                attempt_count=0,
                reason_code=reason_code,
                cause=exc,
            ) from exc
        return True

    @staticmethod
    def _record_compaction_call(
        trace_collector: AgentTraceCollector | None,
        *,
        kind: Literal["history", "turn_prefix"],
        attempt: int,
        step: int,
        status: str,
        started: float,
        usage: dict[str, Any],
        error_code: str | None,
    ) -> None:
        if trace_collector is None:
            return
        trace_collector.compaction_call(
            kind=kind,
            attempt=attempt,
            step=step,
            status=status,
            duration_seconds=max(0.0, monotonic() - started),
            usage=usage,
            error_code=error_code,
        )

    async def _execute_tools_stream(
        self,
        calls: list[ToolCall],
        step: int,
        token: CancellationToken,
        deadline: _Deadline,
        sink: EventSink | None,
        results: list[ToolResultMessage],
        trace_collector: AgentTraceCollector | None,
        execution_history: Any | None = None,
        request_id: Any | None = None,
    ) -> AsyncIterator[AgentEvent]:
        resolved_task_keys: dict[str, str | None] = {}
        invalid_task_key_results: dict[str, ToolResultMessage] = {}

        def prepare_task_ownership(item: ToolCall, plan: TaskPlan | None) -> None:
            task_key = plan.current_key if plan is not None else None
            if self.task_state_coordinator is None or not self._is_materializing(item):
                resolved_task_keys[item.id] = task_key
                return
            try:
                definition = self.tools.get(item.name)
            except KeyError:
                resolved_task_keys[item.id] = task_key
                return
            if definition.input_model is None:
                resolved_task_keys[item.id] = task_key
                return
            try:
                arguments = definition.input_model.model_validate(item.arguments)
            except ValidationError:
                # ToolRegistry remains responsible for reporting schema errors.
                resolved_task_keys[item.id] = task_key
                return
            requested_key = getattr(arguments, "task_key", None)
            try:
                task_key = self.task_state_coordinator.resolve_source_task_key(
                    requested_key,
                    plan=plan,
                )
            except ValueError:
                assert plan is not None
                invalid_task_key_results[item.id] = ToolResultMessage(
                    tool_call_id=item.id,
                    status="error",
                    error=ToolError(
                        code="invalid_arguments",
                        message=f"invalid arguments for tool {item.name}",
                        details={
                            "task_key": requested_key,
                            "available_task_keys": [planned.key for planned in plan.items],
                        },
                    ),
                )
            else:
                resolved_task_keys[item.id] = task_key

        async def execute_and_record(item: ToolCall) -> ToolResultMessage:
            result = invalid_task_key_results.get(item.id)
            if result is None:
                result = await self.tools.execute(
                    item,
                    timeout=self._tool_timeout(item, deadline),
                )
            if execution_history is not None and request_id is not None:
                execution_history.record(request_id, result, kind="tool_result")
                execution_history.remember_artifact_locators(item, result)
            return result

        index = 0
        while index < len(calls):
            self._check_controls(token, deadline)
            call = calls[index]
            if self._is_parallel_safe(call):
                end = index + 1
                while end < len(calls) and self._is_parallel_safe(calls[end]):
                    end += 1
                group = calls[index:end]
            else:
                group = [call]

            plan = (
                self.task_state_coordinator.plan_snapshot()
                if self.task_state_coordinator is not None
                else None
            )
            for item in group:
                prepare_task_ownership(item, plan)
            for item in group:
                self._check_controls(token, deadline)
                event = ToolStarted(
                    step=step,
                    tool_call_id=item.id,
                    tool_name=item.name,
                )
                yield await self._publish(event, sink)

            started = {item.id: monotonic() for item in group}
            operations = [execute_and_record(item) for item in group]
            group_results = await self._await_controlled(
                asyncio.gather(*operations),
                token,
                deadline,
            )
            for item, result in zip(group, group_results, strict=True):
                duration = max(0.0, monotonic() - started[item.id])
                if result.status == "ok" and self.task_state_coordinator is not None:
                    self.task_state_coordinator.record_tool_result(
                        item,
                        result,
                        task_key=resolved_task_keys.get(item.id),
                    )
                if result.status == "ok":
                    event = ToolCompleted(
                        step=step,
                        tool_call_id=item.id,
                        tool_name=item.name,
                        duration=duration,
                    )
                else:
                    assert result.error is not None
                    event = ToolFailed(
                        step=step,
                        tool_call_id=item.id,
                        tool_name=item.name,
                        duration=duration,
                        error_code=result.error.code,
                        error_message=result.error.message,
                    )
                yield await self._publish(event, sink)
                if trace_collector is not None:
                    trace_collector.tool_result(step, result, duration, call=item)
                if result.status == "ok":
                    if trace_collector is not None and self.task_state_coordinator is not None:
                        owners = self.task_state_coordinator.source_owners_snapshot()
                        trace_collector.checkpoint_source_owners(step, owners)
                        if item.name == "task.checkpoint":
                            trace_collector.source_owners_after_checkpoint(
                                step,
                                checkpoint_key=item.arguments.get("key"),
                                source_owners=owners,
                            )
                results.append(result)
            index += len(group)

    def _is_materializing(self, call: ToolCall) -> bool:
        try:
            return self.tools.get(call.name).context_effect is ToolContextEffect.MATERIALIZING
        except KeyError:
            return False

    def _is_parallel_safe(self, call: ToolCall) -> bool:
        try:
            return self.tools.get(call.name).parallel_safe
        except KeyError:
            return False

    def _tool_timeout(self, call: ToolCall, deadline: _Deadline) -> float | None:
        try:
            definition_timeout = self.tools.get(call.name).timeout
        except KeyError:
            definition_timeout = None
        timeout = definition_timeout or self.limits.default_tool_timeout
        remaining = deadline.remaining()
        if remaining is not None:
            if remaining <= 0:
                raise AgentDeadlineExceeded
            timeout = remaining if timeout is None else min(timeout, remaining)
        return timeout

    @staticmethod
    def _normalize_response(raw_response: Any) -> ModelResponse:
        if isinstance(raw_response, ModelResponse):
            response = raw_response
        elif isinstance(raw_response, (AssistantMessage, FinalMessage)):
            response = ModelResponse(message=raw_response)
        else:
            try:
                response = ModelResponse.model_validate(raw_response)
            except ValidationError as exc:
                raise ModelProtocolError(f"invalid model response: {exc}") from exc

        message = response.message
        if isinstance(message, AssistantMessage) and not message.tool_calls:
            if message.content is None:
                raise ModelProtocolError("assistant response had neither content nor tool calls")
            return ModelResponse(
                message=FinalMessage(content=message.content),
                finish_reason=response.finish_reason,
                usage=response.usage,
            )
        return response

    @staticmethod
    def _check_controls(token: CancellationToken, deadline: _Deadline) -> None:
        token.raise_if_cancelled()
        deadline.raise_if_expired()

    async def _await_controlled(
        self,
        awaitable: Awaitable[Any],
        token: CancellationToken,
        deadline: _Deadline,
    ) -> Any:
        try:
            self._check_controls(token, deadline)
        except (AgentCancelledError, AgentDeadlineExceeded):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise
        operation = asyncio.ensure_future(awaitable)
        cancellation_wait = asyncio.create_task(token.wait())
        remaining = deadline.remaining()
        deadline_wait = (
            asyncio.create_task(asyncio.sleep(remaining)) if remaining is not None else None
        )
        waiters: set[asyncio.Task[Any]] = {operation, cancellation_wait}
        if deadline_wait is not None:
            waiters.add(deadline_wait)
        try:
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if operation in done:
                return await operation
            if cancellation_wait in done:
                operation.cancel()
                raise AgentCancelledError
            operation.cancel()
            raise AgentDeadlineExceeded
        finally:
            for waiter in waiters:
                if waiter is not operation and not waiter.done():
                    waiter.cancel()
            await asyncio.gather(
                *(waiter for waiter in waiters if waiter is not operation),
                return_exceptions=True,
            )
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def _publish(self, event: AgentEvent, call_sink: EventSink | None) -> AgentEvent:
        for sink in (self.event_sink, call_sink):
            if sink is None:
                continue
            result = sink(event)
            if inspect.isawaitable(result):
                await result
        return event


def _append_system_instruction(
    messages: Sequence[Message],
    instruction: str,
) -> list[Message]:
    """Append an ephemeral instruction to a copied transcript."""

    instruction_messages = list(messages)
    for index, message in enumerate(instruction_messages):
        if isinstance(message, SystemMessage):
            instruction_messages[index] = message.model_copy(
                update={"content": f"{message.content}\n\n{instruction}"}
            )
            return instruction_messages
    instruction_messages.insert(0, SystemMessage(content=instruction))
    return instruction_messages


def _validate_compaction_call(
    request: ModelRequest, *, kind: Literal["history", "turn_prefix"]
) -> None:
    if (
        request.tools
        or request.step is not None
        or type(request.max_output_tokens) is not int
        or request.max_output_tokens <= 0
        or request.metadata.get("purpose") != "context_compaction"
        or request.metadata.get("compaction_kind") != kind
    ):
        raise ModelProtocolError("invalid compaction summary request")


def _project_session_context(
    messages: Sequence[Message],
    execution_history: Any | None,
) -> list[Message]:
    """Build an ephemeral model-facing session background projection."""

    copied_messages = [message.model_copy(deep=True) for message in messages]
    if execution_history is None:
        return copied_messages

    summary = getattr(execution_history, "summary", None)
    locators = tuple(getattr(execution_history, "artifact_locators", ()))
    if not summary and not locators:
        return copied_messages

    payload = {
        "summary": summary,
        "artifact_locators": [
            {
                "ref": locator.ref,
                "source_tool": locator.source_tool,
                "query_hint": locator.query_hint,
            }
            for locator in locators
        ],
    }
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _append_system_instruction(
        copied_messages,
        f"{_SESSION_CONTEXT_DESCRIPTION}\nSession context data:\n{data}",
    )


def _project_answer_messages(
    messages: Sequence[Message],
    execution_history: Any | None,
    execution_instruction: str | None,
) -> list[Message]:
    """Project answer conversation without execution-only operating rules."""

    conversation = [message.model_copy(deep=True) for message in messages]
    if execution_instruction is not None:
        conversation = [
            message
            for message in conversation
            if not (isinstance(message, SystemMessage) and message.content == execution_instruction)
        ]
    return _project_session_context(conversation, execution_history)


def _history_set_effective(history: Any, messages: Sequence[Message]) -> None:
    setter = getattr(history, "set_effective", None)
    if callable(setter):
        setter(list(messages))


def _runtime_history_messages(history: Any, system_instruction: str | None) -> list[Message]:
    messages = [message.model_copy(deep=True) for message in history.effective_messages()]
    if system_instruction is not None:
        messages.insert(0, SystemMessage(content=system_instruction))
    return messages


def _latest_compaction_record(history: Any, request_id: Any) -> Any:
    records = getattr(history, "compaction_records", ())
    if not records or records[-1].request_id != request_id:
        raise ModelProtocolError("compaction commit record is not available")
    return records[-1]


def _normalize_compaction_steps(steps: Sequence[int]) -> frozenset[int]:
    normalized: set[int] = set()
    for step in steps:
        if type(step) is not int or step <= 0:
            raise ModelProtocolError("compact_before_steps must contain positive integers")
        normalized.add(step)
    return frozenset(normalized)


def _validate_compaction_entry(history: Any | None, request_id: Any | None) -> None:
    if history is None or request_id is None:
        raise ModelProtocolError(
            "compact_before_steps requires initialized execution history and request_id"
        )
    if not getattr(history, "initialized", False):
        raise ModelProtocolError("execution history is not initialized")
    snapshot_method = getattr(history, "context_snapshot", None)
    if not callable(snapshot_method):
        raise ModelProtocolError("execution history does not provide a context snapshot")
    snapshot = snapshot_method()
    if snapshot.current_request_id != request_id:
        raise ModelProtocolError("execution history request does not match the active request")


def _persistent_history_messages(
    messages: Sequence[Message],
    system_instruction: str | None,
) -> list[Message]:
    if system_instruction is None:
        return [message.model_copy(deep=True) for message in messages]
    return [
        message.model_copy(deep=True)
        for message in messages
        if not (isinstance(message, SystemMessage) and message.content == system_instruction)
    ]


def _has_reliable_tool_results(
    calls: Sequence[ToolCall],
    results: Sequence[ToolResultMessage],
) -> bool:
    """Return whether this request produced a successful non-control observation."""

    names = {call.id: call.name for call in calls}
    for result in results:
        tool_name = names.get(result.tool_call_id)
        if (
            result.status != "ok"
            or tool_name is None
            or tool_name in {"task.plan", "task.checkpoint"}
            or _is_receipt_only(result.content)
        ):
            continue
        return True
    return False


def _is_receipt_only(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_artifact_observation")
    return isinstance(marker, dict) and marker.get("state") == "receipt_only"


def _record_delivery(
    history: Any,
    request_id: Any,
    final: FinalMessage,
    request_messages: Sequence[Message],
    system_instruction: str | None,
) -> None:
    record_delivery = getattr(history, "record_delivery", None)
    if callable(record_delivery):
        record_delivery(request_id, final)
    _history_set_effective(
        history,
        [*_persistent_history_messages(request_messages, system_instruction), final],
    )


def _build_answer_request(
    *,
    instruction: str,
    runtime_prompt: str,
    shared_instruction: str | None = None,
    messages: Sequence[Message],
    context: Any,
    step: int,
    max_output_tokens: int | None = None,
) -> ModelRequest:
    return ModelRequest(
        messages=[
            *(
                [SystemMessage(content=shared_instruction)]
                if shared_instruction is not None
                else []
            ),
            SystemMessage(content=instruction),
            SystemMessage(content=runtime_prompt),
            *_answer_conversation(messages),
            SystemMessage(content=context.render()),
        ],
        tools=[],
        step=step,
        max_output_tokens=max_output_tokens,
    )


def _answer_attempt_status(error: AgentRuntimeError) -> str:
    if isinstance(error, AgentDeadlineExceeded):
        return "timeout"
    return "error"


def _answer_conversation(messages: Sequence[Message]) -> list[Message]:
    """Keep the full effective execution transcript for the answer model."""

    return [message.model_copy(deep=True) for message in messages]


__all__ = ["AgentRuntime", "CancellationToken", "EventSink"]
