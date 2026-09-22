"""A thin native tool-calling loop with bounded, observable execution."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from copy import deepcopy
from time import monotonic
from typing import Any

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
from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    AgentRuntimeError,
    ContextCapacityExceeded,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
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
    build_compaction_request,
    select_compaction_range,
    validate_compaction_response,
)
from app.vnext.agent.instructions import ANSWER_INSTRUCTION, DEGRADED_ANSWER_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.materialization_budget import MaterializationBudget
from app.vnext.agent.runtime_context import RuntimeContext, classify_time_pressure
from app.vnext.agent.runtime_prompt import render_runtime_prompt
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.agent.transcript_rewrite import TranscriptRewriter
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
        transcript_rewriter: TranscriptRewriter | None = None,
        task_state_coordinator: TaskStateCoordinator | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.event_sink = event_sink
        self.system_instruction = system_instruction
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
        materialization_budget = MaterializationBudget(
            self.limits.max_materialized_context_bytes,
            initial_entries=_initial_materialization_entries(messages, self.tools),
        )
        started_at = execution_deadline.started
        step = 0
        outcome: ExecutionOutcome | None = None
        request_messages: list[Message] = []
        compaction_attempted_since_progress = False

        try:
            if self.system_instruction is not None and any(
                isinstance(message, SystemMessage) for message in messages
            ):
                raise ModelProtocolError(
                    "system messages are runtime-owned when system_instruction is configured"
                )
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

            while step < self.limits.max_steps:
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
                        auto_compaction_enabled=True,
                    )
                    candidate_capacity = assess_request_capacity(
                        execution_request_data[0], self.limits
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
                    materialized_bytes_before = materialization_budget.active_bytes
                    request_start_before = request_start
                    try:
                        compacted = await self._compact_session_history(
                            execution_history=execution_history,
                            request_id=request_id,
                            token=token,
                            deadline=execution_deadline,
                            step=step,
                            recent_history_bytes=self.limits.compaction_recent_history_bytes,
                            max_input_bytes=self.limits.compaction_max_input_bytes,
                            max_output_tokens=self.limits.compaction_max_output_tokens,
                            max_summary_bytes=self.limits.compaction_max_summary_bytes,
                            trace_collector=trace_collector,
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
                        request_start, request_messages, materialization_budget = (
                            self._rebuild_after_compaction(
                                execution_history=execution_history,
                                request_id=request_id,
                                request_start=request_start,
                                request_start_before=request_start_before,
                                materialized_bytes_before=materialized_bytes_before,
                                step=step,
                                trigger=compaction_trigger,
                                trace_collector=trace_collector,
                            )
                        )
                    execution_request_data = None

                if execution_request_data is None:
                    execution_request_data = self._build_execution_request(
                        request_messages=request_messages,
                        execution_history=execution_history,
                        step=step,
                        deadline=execution_deadline,
                        auto_compaction_enabled=auto_compaction_enabled,
                    )
                (
                    request,
                    runtime_context,
                    conversation_messages,
                    task_context_messages,
                    task_context_payload,
                ) = execution_request_data
                if auto_compaction_enabled:
                    final_capacity = assess_request_capacity(request, self.limits)
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
                if trace_collector is not None:
                    trace_collector.model_request(
                        request,
                        runtime_context=runtime_context,
                        conversation_messages=conversation_messages,
                        task_context_messages=task_context_messages,
                        task_context_payload=task_context_payload,
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
                    response, duration, _ = await self._invoke_model(
                        request,
                        token=token,
                        deadline=execution_deadline,
                        step=step,
                        trace_collector=trace_collector,
                        publish_text=False,
                    )
                except AgentDeadlineExceeded:
                    outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                    break
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
                        materialization_budget,
                        execution_history=execution_history,
                        request_id=request_id,
                    ):
                        yield tool_event
                    self._check_controls(token, execution_deadline)
                except AgentDeadlineExceeded:
                    outcome = ExecutionOutcome(ExecutionStopReason.DEADLINE, step)
                    break
                candidate_messages = [*request_messages, assistant, *results]
                if self.transcript_rewriter is None:
                    request_messages = candidate_messages
                else:
                    rewrite = self.transcript_rewriter.rewrite(candidate_messages)
                    request_messages = rewrite.messages
                    for event in rewrite.events:
                        event_index = event.metadata.get("message_index")
                        release_current = not isinstance(event_index, int) or (
                            event_index >= request_start
                        )
                        released_bytes = (
                            materialization_budget.release(
                                event.tool_call_id,
                                entry_key=f"current:{event.tool_call_id}",
                            )
                            if release_current
                            else 0
                        )
                        if trace_collector is not None:
                            trace_collector.transcript_rewrite(step, event)
                            if released_bytes > 0:
                                trace_collector.materialization_release(
                                    step,
                                    tool_call_id=event.tool_call_id,
                                    reason=event.reason,
                                    released_bytes=released_bytes,
                                    active_after_bytes=materialization_budget.active_bytes,
                                    limit_bytes=materialization_budget.limit_bytes,
                                )
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
                outcome = ExecutionOutcome(ExecutionStopReason.MAX_STEPS, step)
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
            )
            if trace_collector is not None:
                trace_collector.answer_resolution(
                    resolution,
                    execution_reason=outcome.reason,
                )
            answer_step = step + 1
            if resolution.mode is AnswerResolutionMode.FAILURE:
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
                    ),
                    sink,
                )
                return

            answer_context_builder = AnswerContextBuilder()
            primary_deadline = _Deadline(self.limits.answer_timeout_seconds)
            primary_started = monotonic()
            try:
                primary_context = answer_context_builder.build(
                    execution_messages=request_messages,
                    outcome=outcome,
                    task_state_coordinator=self.task_state_coordinator,
                    resolution=resolution,
                    projection_mode=AnswerProjectionMode.PRIMARY,
                    effective_history_embedded=True,
                )
                answer_messages = _project_session_context(request_messages, execution_history)
                answer_request = _build_answer_request(
                    instruction=ANSWER_INSTRUCTION,
                    messages=answer_messages,
                    context=primary_context,
                    step=answer_step,
                    max_output_tokens=(
                        self.limits.context_output_reserve_tokens
                        if auto_compaction_enabled
                        else None
                    ),
                )
                if auto_compaction_enabled:
                    primary_capacity = assess_request_capacity(answer_request, self.limits)
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
                        materialized_bytes_before = materialization_budget.active_bytes
                        request_start_before = request_start
                        try:
                            compacted = await self._compact_session_history(
                                execution_history=execution_history,
                                request_id=request_id,
                                token=token,
                                deadline=primary_deadline,
                                step=answer_step,
                                recent_history_bytes=(
                                    self.limits.compaction_recent_history_bytes
                                ),
                                max_input_bytes=self.limits.compaction_max_input_bytes,
                                max_output_tokens=self.limits.compaction_max_output_tokens,
                                max_summary_bytes=self.limits.compaction_max_summary_bytes,
                                trace_collector=trace_collector,
                            )
                        except CompactionSummaryError as exc:
                            raise ModelProtocolError(
                                f"answer compaction failed: {exc}"
                            ) from exc
                        if compacted:
                            request_start, request_messages, materialization_budget = (
                                self._rebuild_after_compaction(
                                    execution_history=execution_history,
                                    request_id=request_id,
                                    request_start=request_start,
                                    request_start_before=request_start_before,
                                    materialized_bytes_before=materialized_bytes_before,
                                    step=answer_step,
                                    trigger="watermark",
                                    trace_collector=trace_collector,
                                )
                            )
                            primary_context = answer_context_builder.build(
                                execution_messages=request_messages,
                                outcome=outcome,
                                task_state_coordinator=self.task_state_coordinator,
                                resolution=resolution,
                                projection_mode=AnswerProjectionMode.PRIMARY,
                                effective_history_embedded=True,
                            )
                            answer_messages = _project_session_context(
                                request_messages,
                                execution_history,
                            )
                            answer_request = _build_answer_request(
                                instruction=ANSWER_INSTRUCTION,
                                messages=answer_messages,
                                context=primary_context,
                                step=answer_step,
                                max_output_tokens=self.limits.context_output_reserve_tokens,
                            )
                    self._check_controls(token, primary_deadline)
                    final_capacity = assess_request_capacity(answer_request, self.limits)
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
                self._check_controls(token, primary_deadline)
                if trace_collector is not None:
                    trace_collector.model_request(answer_request)
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
                response, duration, answer_text_events = await self._invoke_model(
                    answer_request,
                    token=token,
                    deadline=primary_deadline,
                    step=answer_step,
                    trace_collector=trace_collector,
                    publish_text=True,
                )
                answer = response.message
                if not isinstance(answer, FinalMessage):
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
                for text_event in answer_text_events:
                    yield await self._publish(text_event, sink)
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
                if trace_collector is not None:
                    trace_collector.answer_attempt(
                        kind="primary",
                        step=answer_step,
                        status=_answer_attempt_status(exc),
                        duration_seconds=max(0.0, monotonic() - primary_started),
                        error_code=exc.code,
                    )

                degraded_step = answer_step + 1
                degraded_deadline = _Deadline(self.limits.degraded_answer_timeout_seconds)
                degraded_started = monotonic()
                degraded_context = answer_context_builder.build(
                    execution_messages=request_messages,
                    outcome=outcome,
                    task_state_coordinator=self.task_state_coordinator,
                    resolution=resolution,
                    projection_mode=AnswerProjectionMode.DEGRADED,
                    effective_history_embedded=True,
                )
                degraded_request = _build_answer_request(
                    instruction=DEGRADED_ANSWER_INSTRUCTION,
                    messages=_project_session_context(request_messages, execution_history),
                    context=degraded_context,
                    step=degraded_step,
                    max_output_tokens=(
                        self.limits.context_output_reserve_tokens
                        if auto_compaction_enabled
                        else None
                    ),
                )
                degraded_precheck_error: AgentRuntimeError | None = None
                if auto_compaction_enabled:
                    degraded_capacity = assess_request_capacity(degraded_request, self.limits)
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
                        self._check_controls(token, degraded_deadline)
                    except AgentDeadlineExceeded as exc:
                        degraded_precheck_error = exc
                if degraded_precheck_error is None:
                    if trace_collector is not None:
                        trace_collector.model_request(degraded_request)
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
                    (
                        degraded_response,
                        degraded_duration,
                        degraded_text_events,
                    ) = await self._invoke_model(
                        degraded_request,
                        token=token,
                        deadline=degraded_deadline,
                        step=degraded_step,
                        trace_collector=trace_collector,
                        publish_text=True,
                    )
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
                    for text_event in degraded_text_events:
                        yield await self._publish(text_event, sink)
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
                    if trace_collector is not None:
                        trace_collector.answer_attempt(
                            kind="degraded",
                            step=degraded_step,
                            status=_answer_attempt_status(degraded_exc),
                            duration_seconds=max(0.0, monotonic() - degraded_started),
                            error_code=degraded_exc.code,
                        )
                        trace_collector.answer_fallback("deterministic")
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

    def _build_execution_request(
        self,
        *,
        request_messages: Sequence[Message],
        execution_history: Any | None,
        step: int,
        deadline: _Deadline,
        auto_compaction_enabled: bool,
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
            max_steps=self.limits.max_steps,
            tools_available=True,
            time_pressure=time_pressure,
        )
        conversation_messages = _project_session_context(
            request_messages,
            execution_history,
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
            max_output_tokens=(
                self.limits.context_output_reserve_tokens
                if auto_compaction_enabled
                else None
            ),
        )
        return (
            request,
            runtime_context,
            conversation_messages,
            task_context_messages,
            task_context_payload,
        )

    def _rebuild_after_compaction(
        self,
        *,
        execution_history: Any,
        request_id: Any,
        request_start: int,
        request_start_before: int,
        materialized_bytes_before: int,
        step: int,
        trigger: str,
        trace_collector: AgentTraceCollector | None,
    ) -> tuple[int, list[Message], MaterializationBudget]:
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
        initial_entries = _initial_materialization_entries(
            request_messages,
            self.tools,
            request_start=request_start,
        )
        materialization_budget = MaterializationBudget(
            self.limits.max_materialized_context_bytes,
            initial_entries=initial_entries,
        )
        current_tool_call_ids = {
            key.removeprefix("current:")
            for key, _ in initial_entries
            if key.startswith("current:")
        }
        if self.transcript_rewriter is not None:
            set_scope = getattr(self.transcript_rewriter, "set_request_scope", None)
            if callable(set_scope):
                set_scope(request_start)
        if self.task_state_coordinator is not None:
            self.task_state_coordinator.set_request_scope(request_start)
            self.task_state_coordinator.retain_evidence_leases(current_tool_call_ids)
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
                materialized_bytes_before=materialized_bytes_before,
                materialized_bytes_after=materialization_budget.active_bytes,
            )
        return request_start, request_messages, materialization_budget

    async def _invoke_model(
        self,
        request: ModelRequest,
        *,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
        publish_text: bool,
        on_response: Callable[[ModelResponse], None] | None = None,
    ) -> tuple[ModelResponse, float, list[TextDelta]]:
        """Invoke one model request and optionally expose its text deltas."""

        started = monotonic()
        text_events: list[TextDelta] = []
        try:
            stream = getattr(self.model, "stream", None)
            if callable(stream):
                response = None
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
                                trace_collector.text_delta(step, item.text)
                            if response is not None:
                                raise ModelProtocolError(
                                    "stream emitted text after its terminal response"
                                )
                            if publish_text:
                                text_events.append(TextDelta(step=step, text=item.text))
                        elif isinstance(item, ModelResponse):
                            if response is not None:
                                raise ModelProtocolError(
                                    "stream emitted more than one terminal response"
                                )
                            normalized = self._normalize_response(item)
                            if on_response is not None:
                                on_response(normalized)
                            response = normalized
                        else:
                            raise ModelProtocolError("stream emitted an unsupported model item")
                finally:
                    close = getattr(model_stream, "aclose", None)
                    if callable(close):
                        result = close()
                        if inspect.isawaitable(result):
                            await result
                if response is None:
                    raise ModelProtocolError("stream ended without a terminal model response")
            else:
                raw_response = await self._await_controlled(
                    self.model.complete(request), token, deadline
                )
                response = self._normalize_response(raw_response)
                if on_response is not None:
                    on_response(response)
            self._check_controls(token, deadline)
            return response, max(0.0, monotonic() - started), text_events
        except (AgentCancelledError, AgentDeadlineExceeded):
            raise
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise ModelProviderError(
                f"model provider request failed: {exc}",
                cause=exc,
            ) from exc

    async def _generate_compaction_summary(
        self,
        request: ModelRequest,
        *,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        max_summary_bytes: int,
        trace_collector: AgentTraceCollector | None,
    ) -> CompactionSummaryResult:
        """Generate one validated summary candidate without committing it."""

        started = monotonic()
        response: ModelResponse | None = None
        usage: dict[str, Any] = {}

        def capture_response(received: ModelResponse) -> None:
            nonlocal usage
            usage = deepcopy(received.usage)

        try:
            self._check_controls(token, deadline)
            _validate_compaction_call(request, max_summary_bytes)
            response, _, _ = await self._invoke_model(
                request,
                token=token,
                deadline=deadline,
                step=step,
                trace_collector=None,
                publish_text=False,
                on_response=capture_response,
            )
            self._check_controls(token, deadline)
            summary = validate_compaction_response(
                response,
                max_summary_bytes=max_summary_bytes,
            )
            self._check_controls(token, deadline)
            duration_seconds = max(0.0, monotonic() - started)
            result = CompactionSummaryResult(
                summary=summary,
                usage=usage,
                duration_seconds=duration_seconds,
            )
            if trace_collector is not None:
                trace_collector.compaction_call(
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
                step=step,
                status="failed",
                started=started,
                usage=usage,
                error_code=getattr(exc, "code", None),
            )
            raise

    async def _compact_session_history(
        self,
        *,
        execution_history: Any,
        request_id: Any,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        recent_history_bytes: int,
        max_input_bytes: int,
        max_output_tokens: int,
        max_summary_bytes: int,
        trace_collector: AgentTraceCollector | None,
    ) -> bool:
        """Generate and atomically commit one session-history compaction."""

        self._check_controls(token, deadline)
        if type(recent_history_bytes) is not int or recent_history_bytes <= 0:
            raise HistoryCompactionRangeError("invalid_recent_history_budget")
        for budget in (max_input_bytes, max_output_tokens, max_summary_bytes):
            if type(budget) is not int or budget <= 0:
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

        selected = select_compaction_range(
            snapshot.messages,
            recent_history_bytes=recent_history_bytes,
        )
        if selected is None:
            return False

        current_user_prefix_index = (
            current_index if current_index < selected.cut_index else None
        )
        prefix_history_count = len(selected.prefix_messages) - (
            1 if current_user_prefix_index is not None else 0
        )
        if prefix_history_count < 1:
            return False

        request = build_compaction_request(
            previous_summary=snapshot.summary,
            current_user_message=current_user,
            prefix_messages=selected.prefix_messages,
            current_user_prefix_index=current_user_prefix_index,
            max_input_bytes=max_input_bytes,
            max_output_tokens=max_output_tokens,
        )
        result = await self._generate_compaction_summary(
            request,
            token=token,
            deadline=deadline,
            step=step,
            max_summary_bytes=max_summary_bytes,
            trace_collector=trace_collector,
        )
        self._check_controls(token, deadline)
        execution_history.commit_compaction(
            request_id=request_id,
            base_revision=snapshot.revision,
            summary=result.summary,
            cut_index=selected.cut_index,
        )
        return True

    @staticmethod
    def _record_compaction_call(
        trace_collector: AgentTraceCollector | None,
        *,
        step: int,
        status: str,
        started: float,
        usage: dict[str, Any],
        error_code: str | None,
    ) -> None:
        if trace_collector is None:
            return
        trace_collector.compaction_call(
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
        materialization_budget: MaterializationBudget,
        execution_history: Any | None = None,
        request_id: Any | None = None,
    ) -> AsyncIterator[AgentEvent]:
        async def execute_and_record(item: ToolCall) -> ToolResultMessage:
            result = await self.tools.execute(item, timeout=self._tool_timeout(item, deadline))
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
            candidates: list[tuple[tuple[int, int], int, ToolCall, ToolResultMessage, int]] = []
            plan = (
                self.task_state_coordinator.plan_snapshot()
                if self.task_state_coordinator is not None
                else None
            )
            for original_index, (item, result) in enumerate(
                zip(group, group_results, strict=True)
            ):
                if result.status != "ok" or not self._is_materializing(item):
                    continue
                raw_bytes = _serialized_size(result.model_dump(mode="json"))
                candidates.append(
                    (
                        _materialization_priority(item, original_index, plan),
                        original_index,
                        item,
                        result,
                        raw_bytes,
                    )
                )
            decisions = {}
            for _, _, item, _, raw_bytes in sorted(candidates, key=lambda value: value[0]):
                decision = materialization_budget.admit(
                    item.id,
                    raw_bytes=raw_bytes,
                    entry_key=f"current:{item.id}",
                )
                decisions[item.id] = decision
                if trace_collector is not None:
                    trace_collector.materialization_admission(
                        step,
                        decision=decision,
                        task_key=_materialization_telemetry_task_key(item, plan),
                        limit_bytes=materialization_budget.limit_bytes,
                    )
            raw_bytes_by_id = {item.id: raw_bytes for _, _, item, _, raw_bytes in candidates}
            for item, result in zip(group, group_results, strict=True):
                duration = max(0.0, monotonic() - started[item.id])
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
                    decision = decisions.get(item.id)
                    if decision is not None and decision.admitted:
                        if self.task_state_coordinator is not None:
                            self.task_state_coordinator.record_evidence_lease(
                                item.id,
                                task_key=item.arguments.get("task_key"),
                                raw_bytes=decision.raw_bytes,
                            )
                            if trace_collector is not None:
                                trace_collector.active_evidence_lease(
                                    step,
                                    self.task_state_coordinator.active_evidence_lease(),
                                )
                    elif decision is not None:
                        result = result.model_copy(
                            update={
                                "content": _deferred_materialization(
                                    raw_bytes_by_id[item.id]
                                )
                            }
                        )
                    if (
                        item.name == "task.checkpoint"
                        and self.task_state_coordinator is not None
                    ):
                        if result.status == "ok" and trace_collector is not None:
                            trace_collector.checkpoint_lease_snapshot(
                                step,
                                checkpoint_key=item.arguments.get("key"),
                                active_leases=(
                                    self.task_state_coordinator.active_evidence_leases_snapshot()
                                ),
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
                raise ModelProtocolError(
                    "assistant response had neither content nor tool calls"
                )
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
        self._check_controls(token, deadline)
        operation = asyncio.ensure_future(awaitable)
        cancellation_wait = asyncio.create_task(token.wait())
        remaining = deadline.remaining()
        deadline_wait = (
            asyncio.create_task(asyncio.sleep(remaining))
            if remaining is not None
            else None
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


def _validate_compaction_call(request: ModelRequest, max_summary_bytes: int) -> None:
    if type(max_summary_bytes) is not int or max_summary_bytes <= 0:
        raise CompactionSummaryError("invalid_summary_budget")
    if (
        request.tools
        or request.step is not None
        or request.max_output_tokens is None
        or request.metadata.get("purpose") != "context_compaction"
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
        if not (
            isinstance(message, SystemMessage)
            and message.content == system_instruction
        )
    ]


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


def _initial_materialization_entries(
    messages: Sequence[Message],
    tools: ToolRegistry,
    *,
    request_start: int | None = None,
) -> list[tuple[str, int]]:
    """Seed the request budget with raw heavyweight results already carried in history."""

    tool_names: dict[str, list[str]] = {}
    for message in messages:
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                tool_names.setdefault(call.id, []).append(call.name)

    entries: list[tuple[str, int]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, ToolResultMessage):
            continue
        names = tool_names.get(message.tool_call_id)
        tool_name = names.pop(0) if names else None
        if message.status != "ok" or tool_name is None:
            continue
        try:
            materializing = tools.get(tool_name).context_effect is ToolContextEffect.MATERIALIZING
        except KeyError:
            materializing = False
        if (
            not materializing
            or _is_receipt_content(message.content)
            or _is_deferred_materialization_content(message.content)
        ):
            continue
        entry_key = (
            f"history:{index}:{message.tool_call_id}"
            if request_start is None or index < request_start
            else f"current:{message.tool_call_id}"
        )
        entries.append(
            (
                entry_key,
                _serialized_size(message.model_dump(mode="json")),
            )
        )
    return entries


def _is_receipt_content(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_artifact_observation")
    return isinstance(marker, dict) and marker.get("state") == "receipt_only"


def _is_deferred_materialization_content(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_context_materialization")
    return isinstance(marker, dict) and marker.get("state") == "deferred"


def _build_answer_request(
    *,
    instruction: str,
    messages: Sequence[Message],
    context: Any,
    step: int,
    max_output_tokens: int | None = None,
) -> ModelRequest:
    return ModelRequest(
        messages=[
            SystemMessage(content=instruction),
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


def _materialization_priority(
    call: ToolCall,
    original_index: int,
    plan: Any,
) -> tuple[int, int]:
    if plan is None:
        return (0, original_index)
    owner_key = call.arguments.get("task_key") or plan.current_key
    if isinstance(owner_key, str):
        for order, item in enumerate(plan.items):
            if item.key == owner_key and item.status.value != "completed":
                return (order, original_index)
    return (len(plan.items), original_index)


def _materialization_telemetry_task_key(call: ToolCall, plan: Any) -> str | None:
    explicit_key = call.arguments.get("task_key")
    if isinstance(explicit_key, str):
        return explicit_key
    if plan is not None and isinstance(plan.current_key, str):
        return plan.current_key
    return None


def _deferred_materialization(raw_bytes: int) -> dict[str, Any]:
    return {
        "_context_materialization": {
            "state": "deferred",
            "reason": "budget_exceeded",
            "retryable": True,
            "raw_bytes": raw_bytes,
        }
    }


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


__all__ = ["AgentRuntime", "CancellationToken", "EventSink"]
