from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    ExecutionOutcome,
    ExecutionStopReason,
    resolve_answer,
)
from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.instructions import ANSWER_INSTRUCTION
from app.vnext.agent.runtime import AgentRuntime, _build_answer_request
from app.vnext.agent.runtime_context import ContextPressure
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.calculate import register_calculate_tool
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient
from tests.vnext.test_runtime_overflow_recovery import (
    _final,
    _history,
    _limits,
    _overflow,
    _PlannedModel,
    _run,
    _summary,
)

CONCLUSION = "  Larl 在 20:00 的净值是 8657。\n来源仍需核对。  "


def _has_conclusion(request) -> bool:
    return any(
        isinstance(message, AssistantMessage) and message.content == CONCLUSION
        for message in request.messages
    )


@pytest.mark.parametrize("finish_reason", ["stop", "length", None])
def test_verbatim_conclusion_is_request_local_and_not_delivered(finish_reason) -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(CONCLUSION, finish_reason=finish_reason),
            ModelResponse.from_final("delivered answer"),
        ]
    )
    trace = AgentTraceCollector()
    result = _run(
        AgentRuntime(model, ToolRegistry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
    )
    assert result.content == "delivered answer"
    assert not _has_conclusion(model.requests[0])
    assert _has_conclusion(model.requests[1])
    assert sum(_has_conclusion(request) for request in model.requests) == 1
    assert any(
        isinstance(message, SystemMessage)
        and f"Execution finish_reason: {finish_reason!r}" in message.content
        for message in model.requests[1].messages
    )
    assert not any(
        message.content == CONCLUSION
        for message in history.effective_messages()
        if hasattr(message, "content")
    )
    assert "delivered answer" in str(history.effective_messages())
    assert json.dumps(CONCLUSION, ensure_ascii=False) in json.dumps(
        trace.snapshot(), ensure_ascii=False
    )


@pytest.mark.parametrize("degrade", [False, True])
def test_overflow_rebuild_and_degraded_answer_keep_original_conclusion(degrade) -> None:
    history, request_id = _history()
    plans = [_final(CONCLUSION), _overflow(), _summary()]
    if degrade:
        # Truncation of the answer draft must never replace the execution conclusion.
        plans.append(lambda request: ModelResponse.from_final("bad draft", finish_reason="length"))
    plans.append(_final("delivered answer"))
    model = _PlannedModel(plans)
    result = _run(AgentRuntime(model, ToolRegistry(), limits=_limits()), history, request_id)
    assert result.content == "delivered answer"
    answers = [
        request
        for request in model.requests
        if any(
            isinstance(message, SystemMessage) and "Execution has ended." in message.content
            for message in request.messages
        )
    ]
    assert len(answers) == (3 if degrade else 2)
    assert all(_has_conclusion(request) for request in answers)
    assert all(
        sum(
            isinstance(message, AssistantMessage) and message.content == CONCLUSION
            for message in request.messages
        )
        == 1
        for request in answers
    )


@pytest.mark.parametrize(
    "reason", [ExecutionStopReason.PLAN_COMPLETE, ExecutionStopReason.DEADLINE]
)
def test_no_conclusion_is_explicit_without_synthesizing_previous_text(reason) -> None:
    outcome = ExecutionOutcome(reason=reason, steps=1)
    context = AnswerContextBuilder().build(
        outcome=outcome,
        execution_messages=[],
        task_state_coordinator=None,
        resolution=resolve_answer(outcome=outcome, task_state_coordinator=None),
    )
    request = _build_answer_request(
        instruction=ANSWER_INSTRUCTION,
        runtime_prompt="answer",
        messages=[UserMessage(content="q")],
        context=context,
        step=2,
    )
    assert any(
        isinstance(message, SystemMessage) and "conclusion: unavailable" in message.content
        for message in request.messages
    )
    assert not any(isinstance(message, AssistantMessage) for message in request.messages)


def test_large_conclusion_is_not_silently_omitted_to_fit_capacity() -> None:
    history, request_id = _history()
    huge = "original conclusion " * 10_000
    model = _PlannedModel([_final(huge), _summary()])
    result = _run(
        AgentRuntime(model, ToolRegistry(), limits=_limits(context_window_tokens=20_000)),
        history,
        request_id,
    )
    assert huge != result.content
    # No answer call was made with a shortened or silently missing conclusion.
    for request in model.requests[1:]:
        if any(
            isinstance(message, SystemMessage) and "Execution has ended." in message.content
            for message in request.messages
        ):
            assert any(
                isinstance(message, AssistantMessage) and message.content == huge
                for message in request.messages
            )


def test_next_run_does_not_reuse_previous_execution_conclusion() -> None:
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(CONCLUSION),
            ModelResponse.from_final("answer one"),
            ModelResponse.from_final("new conclusion"),
            ModelResponse.from_final("answer two"),
        ]
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=_limits(context_window_tokens=None))
    asyncio.run(runtime.run([UserMessage(content="one")]))
    asyncio.run(runtime.run([UserMessage(content="two")]))
    assert _has_conclusion(model.requests[1])
    assert not _has_conclusion(model.requests[3])
    assert any(
        isinstance(message, AssistantMessage) and message.content == "new conclusion"
        for message in model.requests[3].messages
    )


def test_watermark_rebuild_retains_conclusion_outside_compacted_history(monkeypatch) -> None:
    forced = False

    def capacity(request, limits, **kwargs):
        nonlocal forced
        result = assess_request_capacity(request, limits, **kwargs)
        if _has_conclusion(request) and not forced:
            forced = True
            return replace(result, pressure=ContextPressure.HIGH)
        return result

    monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)
    history, request_id = _history()
    model = _PlannedModel([_final(CONCLUSION), _summary(), _final("answer")])
    result = _run(AgentRuntime(model, ToolRegistry(), limits=_limits()), history, request_id)
    assert result.content == "answer"
    assert forced
    assert model.requests[1].metadata["purpose"] == "context_compaction"
    assert not _has_conclusion(model.requests[1])
    assert _has_conclusion(model.requests[2])


def test_answer_tool_continuation_keeps_conclusion_and_original_evidence() -> None:
    history, request_id = _history()
    registry = ToolRegistry()
    register_calculate_tool(registry)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(CONCLUSION),
            ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[
                        ToolCall(
                            id="calculate", name="math.calculate", arguments={"expression": "2+3"}
                        ),
                    ]
                )
            ),
            ModelResponse.from_final("answer"),
        ]
    )
    result = _run(AgentRuntime(model, registry, limits=_limits()), history, request_id)
    assert result.content == "answer"
    assert all(_has_conclusion(request) for request in model.requests[1:])
    assert any(
        isinstance(message, ToolResultMessage) and message.tool_call_id == "old-call"
        for message in model.requests[-1].messages
    )
    assert any(
        isinstance(message, ToolResultMessage) and message.tool_call_id == "calculate"
        for message in model.requests[-1].messages
    )
    assert not any(
        isinstance(message, AssistantMessage) and message.content == CONCLUSION
        for message in history.effective_messages()
    )
