"""A thin native tool-calling loop with bounded, observable execution."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from time import monotonic
from typing import Any

from pydantic import ValidationError

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    AgentRuntimeError,
    MaxStepsExceeded,
    MaxToolCallsExceeded,
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
from app.vnext.agent.limits import AgentLimits
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    StreamingModelClient,
    ToolCall,
    ToolResultMessage,
)
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
    def __init__(self, seconds: float | None) -> None:
        self.started = monotonic()
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
    ) -> None:
        self.model = model
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.event_sink = event_sink

    async def run(
        self,
        messages: Sequence[Message],
        *,
        cancellation_token: CancellationToken | None = None,
        event_sink: EventSink | None = None,
    ) -> FinalMessage:
        """Run to a final message, while ``run_stream`` exposes every event."""

        final: FinalMessage | None = None
        async for event in self.run_stream(
            messages,
            cancellation_token=cancellation_token,
            event_sink=event_sink,
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
    ) -> AsyncIterator[AgentEvent]:
        """Yield ephemeral runtime events in execution order."""

        token = cancellation_token or CancellationToken()
        sink = event_sink
        deadline = _Deadline(self.limits.deadline_seconds)
        started_at = deadline.started
        step = 0
        tool_calls_used = 0

        try:
            request_messages = list(messages)
            # Validate the initial transcript before model dispatch.  This also
            # makes a defensive copy so a caller's list is never mutated.
            request_messages = ModelRequest(messages=request_messages, tools=[]).messages
            event = AgentStarted()
            yield await self._publish(event, sink)

            while True:
                step += 1
                if step > self.limits.max_steps:
                    raise MaxStepsExceeded(self.limits.max_steps)
                self._check_controls(token, deadline)

                request = ModelRequest(
                    messages=request_messages,
                    tools=self.tools.schemas(),
                    step=step,
                )
                event = ModelRequested(
                    step=step,
                    message_count=len(request_messages),
                    tool_count=len(request.tools),
                )
                yield await self._publish(event, sink)

                model_started = monotonic()
                try:
                    stream = getattr(self.model, "stream", None)
                    if callable(stream):
                        response = None
                        model_stream = stream(request)
                        if inspect.isawaitable(model_stream):
                            model_stream = await self._await_controlled(
                                model_stream,
                                token,
                                deadline,
                            )
                        if not hasattr(model_stream, "__anext__"):
                            raise ModelProtocolError(
                                "streaming model client did not return an async iterator"
                            )
                        try:
                            while True:
                                try:
                                    item = await self._await_controlled(
                                        anext(model_stream),
                                        token,
                                        deadline,
                                    )
                                except StopAsyncIteration:
                                    break
                                if isinstance(item, ModelTextDelta):
                                    if response is not None:
                                        raise ModelProtocolError(
                                            "stream emitted text after its terminal response"
                                        )
                                    event = TextDelta(step=step, text=item.text)
                                    yield await self._publish(event, sink)
                                elif isinstance(item, ModelResponse):
                                    if response is not None:
                                        raise ModelProtocolError(
                                            "stream emitted more than one terminal response"
                                        )
                                    response = self._normalize_response(item)
                                else:
                                    raise ModelProtocolError(
                                        "stream emitted an unsupported model item"
                                    )
                        finally:
                            close = getattr(model_stream, "aclose", None)
                            if callable(close):
                                result = close()
                                if inspect.isawaitable(result):
                                    await result
                        if response is None:
                            raise ModelProtocolError(
                                "stream ended without a terminal model response"
                            )
                    else:
                        raw_response = await self._await_controlled(
                            self.model.complete(request),
                            token,
                            deadline,
                        )
                        response = self._normalize_response(raw_response)
                except (AgentCancelledError, AgentDeadlineExceeded):
                    raise
                except AgentRuntimeError:
                    raise
                except Exception as exc:
                    raise ModelProviderError(
                        f"model provider request failed: {exc}",
                        cause=exc,
                    ) from exc

                self._check_controls(token, deadline)
                assistant = response.message
                has_tool_calls = isinstance(assistant, AssistantMessage) and bool(
                    assistant.tool_calls
                )
                event = ModelResponded(
                    step=step,
                    has_tool_calls=has_tool_calls,
                    duration=max(0.0, monotonic() - model_started),
                )
                yield await self._publish(event, sink)

                if isinstance(assistant, FinalMessage):
                    event = AgentCompleted(
                        step=step,
                        duration=max(0.0, monotonic() - started_at),
                        final=assistant,
                    )
                    yield await self._publish(event, sink)
                    return

                request_messages.append(assistant)
                calls = assistant.tool_calls
                if not calls:
                    # Some compatible providers omit a distinct finish marker.
                    # A text-only assistant response is still a final answer at
                    # this boundary; the adapter normally already maps it to
                    # FinalMessage, but native fakes can use AssistantMessage.
                    if assistant.content is None:
                        raise ModelProtocolError(
                            "assistant response had neither content nor tool calls"
                        )
                    final = FinalMessage(content=assistant.content)
                    event = AgentCompleted(
                        step=step,
                        duration=max(0.0, monotonic() - started_at),
                        final=final,
                    )
                    yield await self._publish(event, sink)
                    return

                if tool_calls_used + len(calls) > self.limits.max_tool_calls:
                    raise MaxToolCallsExceeded(
                        self.limits.max_tool_calls,
                        len(calls),
                        tool_calls_used,
                    )
                tool_calls_used += len(calls)

                results: list[ToolResultMessage] = []
                async for tool_event in self._execute_tools_stream(
                    calls,
                    step,
                    token,
                    deadline,
                    sink,
                    results,
                ):
                    yield tool_event
                request_messages.extend(results)
                self._check_controls(token, deadline)

        except AgentCancelledError as exc:
            event = AgentCancelled(
                step=step or None,
                error_message=str(exc),
            )
            yield await self._publish(event, sink)
            raise
        except AgentRuntimeError as exc:
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
            event = AgentFailed(
                step=step or None,
                duration=max(0.0, monotonic() - started_at),
                error_code=wrapped.code,
                error_message=str(wrapped),
            )
            yield await self._publish(event, sink)
            raise wrapped from exc

    async def _execute_tools_stream(
        self,
        calls: list[ToolCall],
        step: int,
        token: CancellationToken,
        deadline: _Deadline,
        sink: EventSink | None,
        results: list[ToolResultMessage],
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
                results.append(result)
            index += len(group)

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


__all__ = ["AgentRuntime", "CancellationToken", "EventSink"]
