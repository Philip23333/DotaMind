from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.runtime_context import ContextPressure, capture_request_time
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    SystemMessage,
    ToolCall,
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

ANCHOR = "2026-10-17T23:59:59+08:00"


def _assert_anchor(request, expected=ANCHOR):
    assert request.metadata["request_time"] == expected
    prompt = next(
        m.content
        for m in request.messages
        if isinstance(m, SystemMessage) and m.content.startswith("Runtime state:\n")
    )
    assert "Date: " + expected[:10] in prompt
    assert "Datetime: " + expected in prompt
    assert "Timezone: Asia/Shanghai" in prompt
    assert "not a source update time or a match timestamp" in prompt


def test_capture_uses_explicit_beijing_zone_and_offset(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz.key == "Asia/Shanghai"
            return datetime(2026, 10, 17, 16, 0, 1, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("app.vnext.agent.runtime_context.datetime", FrozenDatetime)
    assert capture_request_time() == "2026-10-18T00:00:01+08:00"


@pytest.mark.parametrize("scenario", ["normal", "tools", "overflow", "degraded", "watermark"])
def test_all_business_requests_keep_one_anchor_across_stage_rebuilds(monkeypatch, scenario):
    captures = []

    def capture():
        captures.append(ANCHOR)
        return ANCHOR

    monkeypatch.setattr("app.vnext.agent.runtime.capture_request_time", capture)
    registry = ToolRegistry()
    plans = [_final("execution conclusion")]
    if scenario == "tools":
        register_calculate_tool(registry)
        plans.append(
            lambda _: ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[
                        ToolCall(id="calc", name="math.calculate", arguments={"expression": "6*7"})
                    ]
                )
            )
        )
    if scenario in {"overflow", "degraded"}:
        plans.extend([_overflow(), _summary()])
    if scenario == "degraded":
        plans.append(lambda _: ModelResponse.from_final("truncated draft", finish_reason="length"))
    if scenario == "watermark":
        forced = False

        def capacity(request, limits, **kwargs):
            nonlocal forced
            result = assess_request_capacity(request, limits, **kwargs)
            if request.step > 1 and not forced:
                forced = True
                return replace(result, pressure=ContextPressure.HIGH)
            return result

        monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)
        plans.append(_summary())
    plans.append(_final("answer"))
    model = _PlannedModel(plans)
    history, request_id = _history()
    final = _run(AgentRuntime(model, registry, limits=_limits()), history, request_id)
    assert final.content == "answer"
    assert captures == [ANCHOR]
    business = [r for r in model.requests if r.metadata.get("purpose") != "context_compaction"]
    assert len(business) >= 2
    for request in business:
        _assert_anchor(request)


def test_next_user_request_gets_fresh_anchor_on_same_runtime(monkeypatch):
    next_day = "2026-10-18T00:00:02+08:00"
    clocks = iter([ANCHOR, next_day])
    monkeypatch.setattr("app.vnext.agent.runtime.capture_request_time", lambda: next(clocks))
    model = ScriptedModelClient(
        [ModelResponse.from_final(text) for text in ["c1", "a1", "c2", "a2"]]
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=_limits(context_window_tokens=None))
    asyncio.run(runtime.run([UserMessage(content="today?")]))
    asyncio.run(runtime.run([UserMessage(content="today again?")]))
    for request in model.requests[:2]:
        _assert_anchor(request)
    for request in model.requests[2:]:
        _assert_anchor(request, next_day)
