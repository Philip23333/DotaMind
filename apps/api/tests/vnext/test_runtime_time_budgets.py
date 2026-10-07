from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from uuid import uuid4

from pydantic import BaseModel

import app.vnext.agent.runtime as runtime_module
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _ClockedRuntime(AgentRuntime):
    async def _await_controlled(self, awaitable, token, deadline):
        self._check_controls(token, deadline)
        result = await awaitable
        self._check_controls(token, deadline)
        return result


class _EchoInput(BaseModel):
    value: int


class _EchoOutput(BaseModel):
    value: int


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input value.",
            input_model=_EchoInput,
            output_model=_EchoOutput,
            handler=_echo,
        )
    )
    return registry


def _tool_turn(call_id: str, value: int) -> ModelResponse:
    return ModelResponse(
        message=AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id=call_id, name="echo", arguments={"value": value})],
        )
    )


async def _echo(args: _EchoInput) -> _EchoOutput:
    return _EchoOutput(value=args.value)


def _after(clock: _Clock, seconds: float, result: object) -> Awaitable[object]:
    async def finish() -> object:
        clock.advance(seconds)
        if isinstance(result, Exception):
            raise result
        return result

    return finish()


def _runtime_prompt(request: ModelRequest) -> str:
    return next(
        message.content
        for message in request.messages
        if isinstance(message, SystemMessage) and "Runtime state:" in message.content
    )


def test_execution_prompt_tracks_40_and_20_percent_deadline_boundaries(
    monkeypatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime_module, "monotonic", clock)
    model = ScriptedModelClient(
        [
            _after(clock, 60, _tool_turn("first", 1)),
            _after(clock, 20, _tool_turn("second", 2)),
            ModelResponse.from_final("execution done"),
            ModelResponse.from_final("answer"),
        ]
    )
    collector = AgentTraceCollector()
    runtime = _ClockedRuntime(
        model,
        _registry(),
        limits=AgentLimits(
            deadline_seconds=100,
            answer_timeout_seconds=60,
            application_max_output_tokens=4096,
        ),
    )

    result = asyncio.run(runtime.run([UserMessage(content="hello")], trace_collector=collector))

    assert result.content == "answer"
    assert "Time pressure:\nhealthy" in _runtime_prompt(model.requests[0])
    assert "Time pressure:\nlimited" in _runtime_prompt(model.requests[1])
    assert "Time pressure:\ncritical" in _runtime_prompt(model.requests[2])
    execution_contexts = [
        step["runtime_context"]
        for step in collector.snapshot()["steps"]
        if step["runtime_context"] is not None
    ]
    assert [context["time_pressure"] for context in execution_contexts] == [
        "healthy",
        "limited",
        "critical",
    ]


def test_answer_gets_a_fresh_budget_after_execution_uses_its_deadline(
    monkeypatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime_module, "monotonic", clock)
    model = ScriptedModelClient(
        [
            _after(clock, 9, ModelResponse.from_final("execution")),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = _ClockedRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=10,
            answer_timeout_seconds=60,
            application_max_output_tokens=4096,
        ),
    )

    result = asyncio.run(runtime.run([UserMessage(content="hello")]))

    assert result.content == "answer"
    answer_prompt = _runtime_prompt(model.requests[1])
    assert "Stage:\nanswer" in answer_prompt
    assert "Time pressure:\nhealthy" in answer_prompt
    assert "Tools available:\nno" in answer_prompt
    assert "Remaining turns:" not in answer_prompt


def test_degraded_answer_uses_remaining_primary_answer_budget(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime_module, "monotonic", clock)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            _after(clock, 45, ValueError("provider unavailable")),
            ModelResponse.from_final("degraded answer"),
        ]
    )
    collector = AgentTraceCollector()
    runtime = _ClockedRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=10,
            answer_timeout_seconds=60,
            application_max_output_tokens=4096,
        ),
    )

    result = asyncio.run(runtime.run([UserMessage(content="hello")], trace_collector=collector))

    assert result.content == "degraded answer"
    assert len(model.requests) == 3
    assert "Time pressure:\nhealthy" in _runtime_prompt(model.requests[1])
    assert "Time pressure:\nlimited" in _runtime_prompt(model.requests[2])
    assert [attempt["kind"] for attempt in collector.snapshot()["answer_attempts"]] == [
        "primary",
        "degraded",
    ]


def test_exhausted_answer_budget_skips_degraded_model_call(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime_module, "monotonic", clock)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            _after(clock, 61, ValueError("provider unavailable")),
        ]
    )
    collector = AgentTraceCollector()
    runtime = _ClockedRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=10,
            answer_timeout_seconds=60,
            application_max_output_tokens=4096,
        ),
    )

    result = asyncio.run(runtime.run([UserMessage(content="hello")], trace_collector=collector))

    assert "detailed final response" in result.content
    assert len(model.requests) == 2
    attempts = collector.snapshot()["answer_attempts"]
    assert attempts[0]["kind"] == "primary"
    assert attempts[1]["kind"] == "degraded"
    assert attempts[1]["status"] == "timeout"
    assert collector.snapshot()["answer_fallback"] == "deterministic"


def test_answer_runtime_prompt_is_capacity_counted_but_not_persisted(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(runtime_module, "monotonic", clock)
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(
        request_id,
        "hello",
        initial_messages=[UserMessage(content="hello")],
    )
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    limits = AgentLimits(
        deadline_seconds=10,
        answer_timeout_seconds=60,
        context_window_tokens=100_000,
        application_max_output_tokens=256,
        context_safety_margin_tokens=64,
    )
    collector = AgentTraceCollector()

    result = asyncio.run(
        _ClockedRuntime(model, ToolRegistry(), limits=limits).run(
            messages,
            execution_history=history,
            request_id=request_id,
            trace_collector=collector,
        )
    )

    assert result.content == "answer"
    answer_request = model.requests[1]
    prompt = _runtime_prompt(answer_request)
    assert "Stage:\nanswer" in prompt
    answer_check = next(
        item
        for item in collector.snapshot()["context_capacity_checks"]
        if item["stage"] == "primary_answer" and item["phase"] == "before_model"
    )
    assert (
        answer_check["capacity"]["context_bytes"]
        == collector.snapshot()["answer_stage"]["context_bytes"]
    )
    assert all(
        "Runtime state:" not in str(message.model_dump(mode="json"))
        for message in history.effective_messages()
    )


def test_tool_specific_timeout_overrides_configured_default() -> None:
    default_runtime = AgentRuntime(
        ScriptedModelClient([]),
        _registry(),
        limits=AgentLimits(
            default_tool_timeout=12.5,
            application_max_output_tokens=4096,
        ),
    )
    default_call = ToolCall(id="default", name="echo", arguments={"value": 1})

    explicit_registry = ToolRegistry()
    explicit_registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input value.",
            input_model=_EchoInput,
            output_model=_EchoOutput,
            handler=_echo,
            timeout=3.5,
        )
    )
    explicit_runtime = AgentRuntime(
        ScriptedModelClient([]),
        explicit_registry,
        limits=AgentLimits(
            default_tool_timeout=12.5,
            application_max_output_tokens=4096,
        ),
    )
    explicit_call = ToolCall(id="explicit", name="echo", arguments={"value": 1})

    assert default_runtime._tool_timeout(default_call, _Deadline(None)) == 12.5
    assert explicit_runtime._tool_timeout(explicit_call, _Deadline(None)) == 3.5
