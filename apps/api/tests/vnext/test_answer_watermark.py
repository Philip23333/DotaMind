from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import AgentCancelledError
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.runtime_context import ContextPressure
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import ArtifactGrepper, ArtifactReader, SessionArtifactStore
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
)
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.calculate import register_calculate_tool
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.test_execution_conclusion_handoff import CONCLUSION, _has_conclusion
from tests.vnext.test_runtime_overflow_recovery import _history, _limits, _run


def _calculation(ident, expression="1478-1010"):
    return ModelResponse.from_assistant(
        AssistantMessage(
            tool_calls=[
                ToolCall(id=ident, name="math.calculate", arguments={"expression": expression}),
            ]
        )
    )


def _has_result(request):
    return any(
        isinstance(m, ToolResultMessage) and m.tool_call_id == "first" for m in request.messages
    )


@pytest.mark.parametrize("degraded", [False, True])
def test_tool_result_watermark_compacts_before_next_answer_call(monkeypatch, degraded):
    forced = False

    def capacity(request, limits, **kwargs):
        nonlocal forced
        result = assess_request_capacity(request, limits, **kwargs)
        if _has_result(request) and not forced:
            forced = True
            return replace(result, pressure=ContextPressure.HIGH)
        return result

    monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)

    class Model:
        def __init__(self):
            self.requests = []
            self.summaries = 0
            self.responses = [ModelResponse.from_final(CONCLUSION)]
            if degraded:
                self.responses.append(ModelResponse.from_final("draft", finish_reason="length"))
            self.responses += [
                _calculation("first"),
                _calculation("duplicate"),
                _calculation("fresh", "2+3"),
                ModelResponse.from_final("answer"),
            ]

        async def complete(self, request):
            self.requests.append(request)
            if request.metadata.get("purpose") == "context_compaction":
                self.summaries += 1
                return ModelResponse.from_final(
                    "retained fact: interval 468 seconds", finish_reason="stop"
                )
            return self.responses.pop(0)

    model = Model()
    registry = ToolRegistry()
    register_calculate_tool(registry)
    history, request_id = _history()
    trace = AgentTraceCollector()
    result = _run(
        AgentRuntime(model, registry, limits=_limits()), history, request_id, trace_collector=trace
    )
    assert result.content == "answer"
    assert forced and model.summaries
    assert "retained fact: interval 468 seconds" in history.summary
    assert any(
        item["stage"] == ("degraded_answer" if degraded else "primary_answer")
        and item["phase"] == "before_compaction"
        for item in trace.snapshot()["context_capacity_checks"]
    )
    summary_index = next(
        i for i, r in enumerate(model.requests) if r.metadata.get("purpose") == "context_compaction"
    )
    resumed = next(
        r
        for r in model.requests[summary_index + 1 :]
        if r.metadata.get("purpose") != "context_compaction"
    )
    assert _has_conclusion(resumed)
    assert "old evidence" not in str(resumed.messages)
    final_results = [m for m in model.requests[-1].messages if isinstance(m, ToolResultMessage)]
    duplicate = next(m for m in final_results if m.tool_call_id == "duplicate")
    assert duplicate.status == "error" and "identical" in duplicate.error.message
    assert next(m for m in final_results if m.tool_call_id == "fresh").status == "ok"
    assert any(
        isinstance(m, SystemMessage) and "Calls attempted: 3" in m.content
        for m in model.requests[-1].messages
    )


def test_failed_duplicate_calls_do_not_repeat_no_progress_compaction(monkeypatch):
    attempts = []

    def capacity(request, limits, **kwargs):
        result = assess_request_capacity(request, limits, **kwargs)
        return replace(result, pressure=ContextPressure.HIGH) if _has_result(request) else result

    async def no_range(self, **kwargs):
        attempts.append(kwargs["stage"])
        return False

    monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)
    monkeypatch.setattr(AgentRuntime, "_compact_session_history", no_range)
    from tests.vnext.fakes import ScriptedModelClient

    model = ScriptedModelClient(
        [
            ModelResponse.from_final(CONCLUSION),
            _calculation("first"),
            _calculation("duplicate1"),
            _calculation("duplicate2"),
            ModelResponse.from_final("answer"),
        ]
    )
    registry = ToolRegistry()
    register_calculate_tool(registry)
    history, request_id = _history()
    result = _run(AgentRuntime(model, registry, limits=_limits()), history, request_id)
    assert result.content == "answer"
    assert attempts == ["primary_answer"]


def test_actual_capacity_repeated_compaction_and_reads_exceed_old_quotas():
    store = SessionArtifactStore()
    ref = asyncio.run(
        store.put({"rows": [{"index": i, "payload": "x" * 28_000} for i in range(14)]})
    )
    registry = ToolRegistry()
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    class Model:
        def __init__(self):
            self.requests = []
            self.index = -1
            self.summaries = 0

        async def complete(self, request):
            self.requests.append(request)
            if request.metadata.get("purpose") == "context_compaction":
                self.summaries += 1
                return ModelResponse.from_final(
                    "retained fixture observations", finish_reason="stop"
                )
            self.index += 1
            if self.index == 0:
                return ModelResponse.from_final(CONCLUSION)
            if self.index <= 14:
                return ModelResponse.from_assistant(
                    AssistantMessage(
                        tool_calls=[
                            ToolCall(
                                id=f"read-{self.index}",
                                name="artifact.read",
                                arguments={
                                    "ref": ref,
                                    "mode": "read",
                                    "path": "rows",
                                    "offset": self.index - 1,
                                    "limit": 1,
                                },
                            )
                        ]
                    )
                )
            return ModelResponse.from_final("answer")

    model = Model()
    history, request_id = _history()
    trace = AgentTraceCollector()
    limits = _limits(context_window_tokens=50_000).model_copy(
        update={
            "context_compaction_test_trigger_percent": 70,
        }
    )
    result = _run(
        AgentRuntime(model, registry, limits=limits), history, request_id, trace_collector=trace
    )
    assert result.content == "answer"
    assert model.index == 15  # Each read was requested once, without replay.
    assert model.summaries > 1
    assert len(trace.snapshot()["compaction_commits"]) > 1
    results = [
        m
        for r in model.requests
        for m in r.messages
        if isinstance(m, ToolResultMessage) and m.tool_call_id.startswith("read-")
    ]
    assert {m.tool_call_id for m in results} == {f"read-{i}" for i in range(1, 15)}
    assert all(m.status == "ok" for m in results)
    assert any(
        isinstance(m, SystemMessage) and "Calls attempted: 14" in m.content
        for m in model.requests[-1].messages
    )
    assert _has_conclusion(model.requests[-1])
    # Repeated compaction changed only context, not the stored document.
    assert asyncio.run(store.get(ref))["rows"][13]["payload"] == "x" * 28_000


@pytest.mark.parametrize("cancel", [False, True])
def test_tool_loop_compaction_obeys_existing_deadline_and_cancellation(monkeypatch, cancel):
    from tests.vnext.fakes import ScriptedModelClient

    token = CancellationToken()
    deadlines = []

    def capacity(request, limits, **kwargs):
        result = assess_request_capacity(request, limits, **kwargs)
        return replace(result, pressure=ContextPressure.HIGH) if _has_result(request) else result

    async def interrupted(self, **kwargs):
        deadlines.append(kwargs["deadline"])
        if cancel:
            token.cancel()
        else:
            kwargs["deadline"].expires_at = kwargs["deadline"].started - 1
        return False

    monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)
    monkeypatch.setattr(AgentRuntime, "_compact_session_history", interrupted)
    model = ScriptedModelClient([ModelResponse.from_final(CONCLUSION), _calculation("first")])
    registry = ToolRegistry()
    register_calculate_tool(registry)
    history, request_id = _history()
    runtime = AgentRuntime(model, registry, limits=_limits())
    if cancel:
        with pytest.raises(AgentCancelledError):
            _run(runtime, history, request_id, cancellation_token=token)
    else:
        result = _run(runtime, history, request_id, cancellation_token=token)
        assert "response limit" in result.content
    assert len(deadlines) == 1
    assert len(model.requests) == 2


def test_still_critical_after_tool_loop_compaction_does_not_send_overfull_request(monkeypatch):
    critical = False

    def capacity(request, limits, **kwargs):
        nonlocal critical
        result = assess_request_capacity(request, limits, **kwargs)
        critical = critical or _has_result(request)
        return replace(result, pressure=ContextPressure.CRITICAL) if critical else result

    monkeypatch.setattr("app.vnext.agent.runtime.assess_request_capacity", capacity)

    class Model:
        def __init__(self):
            self.business_calls = 0

        async def complete(self, request):
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final("retained facts", finish_reason="stop")
            self.business_calls += 1
            assert self.business_calls <= 2
            return (
                ModelResponse.from_final(CONCLUSION)
                if self.business_calls == 1
                else _calculation("first")
            )

    model = Model()
    registry = ToolRegistry()
    register_calculate_tool(registry)
    history, request_id = _history()
    result = _run(AgentRuntime(model, registry, limits=_limits()), history, request_id)
    assert "available context budget" in result.content
    assert model.business_calls == 2
    assert history.compaction_records
