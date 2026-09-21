from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import AgentCancelledError
from app.vnext.agent.events import ToolCompleted
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    Message,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _ToolInput(BaseModel):
    value: int = 0


class _ToolOutput(BaseModel):
    value: str


def _call(call_id: str, name: str = "tool") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"value": 1})


def _history() -> tuple[SessionExecutionHistory, UUID, list[Message]]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = [UserMessage(content="question")]
    history.begin_request(request_id, "question", initial_messages=messages)
    return history, request_id, messages


def _registry(
    definitions: list[ToolDefinition],
    *,
    result_processor=None,
) -> ToolRegistry:
    registry = ToolRegistry(result_processor=result_processor)
    for definition in definitions:
        registry.register(definition)
    return registry


def _definition(
    name: str,
    handler,
    *,
    parallel_safe: bool = False,
    context_effect: ToolContextEffect = ToolContextEffect.BOUNDED,
    externalize_result: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        input_model=_ToolInput,
        output_model=_ToolOutput,
        handler=handler,
        parallel_safe=parallel_safe,
        context_effect=context_effect,
        externalize_result=externalize_result,
    )


def _tool_results(request: ModelRequest) -> list[ToolResultMessage]:
    return [
        message
        for message in request.messages
        if isinstance(message, ToolResultMessage)
    ]


def _externalizing_processor(store: SessionArtifactStore) -> ArtifactBackedToolResultProcessor:
    return ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))


def _large_output() -> str:
    return "x" * (13 * 1024)


def test_tool_completed_cancellation_records_raw_result_and_keeps_effective_history() -> None:
    async def tool(_: _ToolInput) -> _ToolOutput:
        return _ToolOutput(value="raw")

    model = ScriptedModelClient(
        [ModelResponse(message=AssistantMessage(tool_calls=[_call("call-1")]))]
    )
    runtime = AgentRuntime(model, _registry([_definition("tool", tool)]))
    history, request_id, messages = _history()
    token = CancellationToken()
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)
        if isinstance(event, ToolCompleted):
            token.cancel()

    async def exercise() -> None:
        with pytest.raises(AgentCancelledError):
            await runtime.run(
                messages,
                cancellation_token=token,
                event_sink=sink,
                execution_history=history,
                request_id=request_id,
            )

    asyncio.run(asyncio.wait_for(exercise(), 2))

    raw = [record for record in history.records if record.kind == "tool_result"]
    assert len(raw) == 1
    assert raw[0].message == ToolResultMessage(
        tool_call_id="call-1", content={"value": "raw"}
    )
    assert history.effective_messages() == messages


def test_parallel_cancellation_records_only_tools_that_returned() -> None:
    fast_finished = asyncio.Event()
    slow_started = asyncio.Event()

    async def fast(_: _ToolInput) -> _ToolOutput:
        fast_finished.set()
        return _ToolOutput(value="fast")

    async def slow(_: _ToolInput) -> _ToolOutput:
        slow_started.set()
        await asyncio.Event().wait()
        return _ToolOutput(value="slow")

    model = ScriptedModelClient(
        [
            ModelResponse(
                message=AssistantMessage(
                    tool_calls=[_call("fast", "fast"), _call("slow", "slow")]
                )
            )
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(
            [
                _definition("fast", fast, parallel_safe=True),
                _definition("slow", slow, parallel_safe=True),
            ]
        ),
    )
    history, request_id, messages = _history()
    token = CancellationToken()

    async def exercise() -> None:
        run = asyncio.create_task(
            runtime.run(
                messages,
                cancellation_token=token,
                execution_history=history,
                request_id=request_id,
            )
        )
        await asyncio.wait_for(slow_started.wait(), 2)
        await asyncio.wait_for(fast_finished.wait(), 2)
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await asyncio.wait_for(run, 2)

    asyncio.run(asyncio.wait_for(exercise(), 2))

    raw = [record for record in history.records if record.kind == "tool_result"]
    assert [record.message.tool_call_id for record in raw] == ["fast"]
    assert raw[0].message.content == {"value": "fast"}
    assert history.effective_messages() == messages


def test_successful_and_failed_tool_results_are_each_recorded_once() -> None:
    async def success(_: _ToolInput) -> _ToolOutput:
        return _ToolOutput(value="ok")

    async def failure(_: _ToolInput) -> _ToolOutput:
        raise RuntimeError("failed")

    model = ScriptedModelClient(
        [
            ModelResponse(
                message=AssistantMessage(
                    tool_calls=[_call("ok", "success"), _call("bad", "failure")]
                )
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry([_definition("success", success), _definition("failure", failure)]),
    )
    history, request_id, messages = _history()

    async def exercise() -> None:
        result = await runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
        )
        assert result.content == "answer"

    asyncio.run(asyncio.wait_for(exercise(), 2))

    raw = [record for record in history.records if record.kind == "tool_result"]
    assert [record.message.tool_call_id for record in raw] == ["ok", "bad"]
    assert [record.message.status for record in raw] == ["ok", "error"]
    assert len({record.message.tool_call_id for record in raw}) == 2
    assert [message.tool_call_id for message in _tool_results(
        ModelRequest(messages=history.effective_messages())
    )] == ["ok", "bad"]


def test_budget_rejection_records_raw_result_but_next_request_gets_deferred() -> None:
    async def materialize(args: _ToolInput) -> _ToolOutput:
        return _ToolOutput(value=f"raw-{args.value}")

    model = ScriptedModelClient(
        [
            ModelResponse(
                message=AssistantMessage(
                    tool_calls=[_call("a", "materialize"), _call("b", "materialize")]
                )
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(
            [
                _definition(
                    "materialize",
                    materialize,
                    parallel_safe=True,
                    context_effect=ToolContextEffect.MATERIALIZING,
                )
            ]
        ),
        limits=AgentLimits(max_materialized_context_bytes=1),
    )
    history, request_id, messages = _history()

    async def exercise() -> None:
        result = await runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
        )
        assert result.content == "answer"

    asyncio.run(asyncio.wait_for(exercise(), 2))

    raw = [record for record in history.records if record.kind == "tool_result"]
    assert [record.message.tool_call_id for record in raw] == ["a", "b"]
    assert [record.message.content for record in raw] == [
        {"value": "raw-1"},
        {"value": "raw-1"},
    ]
    next_results = _tool_results(model.requests[1])
    assert len(next_results) == 2
    assert all(
        result.content["_context_materialization"]["state"] == "deferred"  # type: ignore[index]
        for result in next_results
    )


def test_cancellation_preserves_externalized_locator_and_executes_tool_once() -> None:
    store = SessionArtifactStore()
    executions = 0

    async def externalize(_: _ToolInput) -> _ToolOutput:
        nonlocal executions
        executions += 1
        return _ToolOutput(value=_large_output())

    model = ScriptedModelClient(
        [ModelResponse(message=AssistantMessage(tool_calls=[_call("artifact")]))]
    )
    runtime = AgentRuntime(
        model,
        _registry(
            [
                _definition(
                    "tool",
                    externalize,
                    externalize_result=True,
                )
            ],
            result_processor=_externalizing_processor(store),
        ),
    )
    history, request_id, messages = _history()
    token = CancellationToken()

    async def sink(event: object) -> None:
        if isinstance(event, ToolCompleted):
            token.cancel()

    async def exercise() -> None:
        with pytest.raises(AgentCancelledError):
            await runtime.run(
                messages,
                cancellation_token=token,
                event_sink=sink,
                execution_history=history,
                request_id=request_id,
            )

    asyncio.run(asyncio.wait_for(exercise(), 2))

    assert executions == 1
    assert len(history.artifact_locators) == 1
    ref = history.artifact_locators[0].ref
    assert asyncio.run(store.get(ref)) == {"value": _large_output()}


def test_deferred_materialization_preserves_externalized_locator_and_executes_once() -> None:
    store = SessionArtifactStore()
    executions = 0

    async def materialize(_: _ToolInput) -> _ToolOutput:
        nonlocal executions
        executions += 1
        return _ToolOutput(value=_large_output())

    model = ScriptedModelClient(
        [
            ModelResponse(message=AssistantMessage(tool_calls=[_call("artifact")])),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(
            [
                _definition(
                    "tool",
                    materialize,
                    context_effect=ToolContextEffect.MATERIALIZING,
                    externalize_result=True,
                )
            ],
            result_processor=_externalizing_processor(store),
        ),
        limits=AgentLimits(max_materialized_context_bytes=1),
    )
    history, request_id, messages = _history()

    async def exercise() -> None:
        result = await runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
        )
        assert result.content == "answer"

    asyncio.run(asyncio.wait_for(exercise(), 2))

    assert executions == 1
    assert len(history.artifact_locators) == 1
    next_results = _tool_results(model.requests[1])
    assert next_results[0].content["_context_materialization"]["state"] == "deferred"  # type: ignore[index]
