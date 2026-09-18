"""A thin native tool-calling loop with bounded, observable execution."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from time import monotonic
from typing import Any

from pydantic import ValidationError

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    AnswerResolutionMode,
    ExecutionOutcome,
    ExecutionStopReason,
    build_failure_answer,
    resolve_answer,
)
from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    AgentRuntimeError,
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
from app.vnext.agent.instructions import ANSWER_INSTRUCTION
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
)
from app.vnext.tools.definition import ToolContextEffect
from app.vnext.tools.registry import ToolRegistry

EventSink = Callable[[AgentEvent], Awaitable[None] | None]


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

    async def run(
        self,
        messages: Sequence[Message],
        *,
        cancellation_token: CancellationToken | None = None,
        event_sink: EventSink | None = None,
        trace_collector: AgentTraceCollector | None = None,
    ) -> FinalMessage:
        """Run to a final message, while ``run_stream`` exposes every event."""

        final: FinalMessage | None = None
        async for event in self.run_stream(
            messages,
            cancellation_token=cancellation_token,
            event_sink=event_sink,
            trace_collector=trace_collector,
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
    ) -> AsyncIterator[AgentEvent]:
        """Yield ephemeral runtime events in execution order."""

        token = cancellation_token or CancellationToken()
        sink = event_sink
        execution_deadline = _Deadline(self.limits.deadline_seconds)
        materialization_budget = MaterializationBudget(
            self.limits.max_materialized_context_bytes
        )
        started_at = execution_deadline.started
        step = 0
        outcome: ExecutionOutcome | None = None
        request_messages: list[Message] = []

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
                time_pressure = classify_time_pressure(
                    remaining_seconds=execution_deadline.remaining(),
                    budget_seconds=self.limits.deadline_seconds,
                )
                runtime_context = RuntimeContext.from_state(
                    current_step=step,
                    max_steps=self.limits.max_steps,
                    tools_available=True,
                    time_pressure=time_pressure,
                )
                turn_messages = request_messages
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
                    task_context_messages = list(request_messages)
                request = ModelRequest(
                    messages=turn_messages,
                    tools=self.tools.schemas(),
                    step=step,
                )
                if trace_collector is not None:
                    trace_collector.model_request(
                        request,
                        runtime_context=runtime_context,
                        conversation_messages=request_messages,
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
                        released_bytes = materialization_budget.release(event.tool_call_id)
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

            answer_context = AnswerContextBuilder().build(
                execution_messages=request_messages,
                outcome=outcome,
                task_state_coordinator=self.task_state_coordinator,
            )
            answer_messages = [
                SystemMessage(content=ANSWER_INSTRUCTION),
                *_answer_conversation(messages),
                SystemMessage(content=answer_context.render()),
            ]
            answer_request = ModelRequest(messages=answer_messages, tools=[], step=answer_step)
            if trace_collector is not None:
                trace_collector.model_request(answer_request)
                trace_collector.answer_stage(answer_request, answer_context)
            yield await self._publish(
                ModelRequested(
                    step=answer_step,
                    message_count=len(answer_request.messages),
                    tool_count=0,
                ),
                sink,
            )
            answer_deadline = _Deadline(self.limits.answer_timeout_seconds)
            response, duration, answer_text_events = await self._invoke_model(
                answer_request,
                token=token,
                deadline=answer_deadline,
                step=answer_step,
                trace_collector=trace_collector,
                publish_text=True,
            )
            for text_event in answer_text_events:
                yield await self._publish(text_event, sink)
            answer = response.message
            if trace_collector is not None:
                trace_collector.model_response(answer_step, response, duration)
            yield await self._publish(
                ModelResponded(
                    step=answer_step,
                    has_tool_calls=isinstance(answer, AssistantMessage)
                    and bool(answer.tool_calls),
                    duration=duration,
                ),
                sink,
            )
            if not isinstance(answer, FinalMessage):
                raise ModelProtocolError("answer stage model requested tools")
            if trace_collector is not None:
                trace_collector.terminal(
                    status="completed", error_code=None, error_message=None
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

    async def _invoke_model(
        self,
        request: ModelRequest,
        *,
        token: CancellationToken,
        deadline: _Deadline,
        step: int,
        trace_collector: AgentTraceCollector | None,
        publish_text: bool,
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
                            response = self._normalize_response(item)
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
    ) -> AsyncIterator[AgentEvent]:
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
            operations = [
                self.tools.execute(item, timeout=self._tool_timeout(item, deadline))
                for item in group
            ]
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
                decision = materialization_budget.admit(item.id, raw_bytes=raw_bytes)
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
                        release = self.task_state_coordinator.consume_partition_release()
                        if release is not None and trace_collector is not None:
                            trace_collector.partition_evidence_release(step, release)
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


def _answer_conversation(messages: Sequence[Message]) -> list[Message]:
    """Keep the caller conversation while excluding execution tool history."""

    return [
        message
        for message in messages
        if not isinstance(message, ToolResultMessage)
        and not (isinstance(message, AssistantMessage) and message.tool_calls)
    ]


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
