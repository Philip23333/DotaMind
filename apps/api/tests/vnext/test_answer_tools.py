import asyncio
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.answer_tools import AnswerToolSession
from app.vnext.agent.errors import AgentCancelledError
from app.vnext.agent.events import AgentCompleted, TextDelta, ToolStarted
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
)
from app.vnext.llm.errors import ModelContextWindowError
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.run_state import ProductRunStateProjector
from app.vnext.product.runtime_projection import apply_runtime_event
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.calculate import register_calculate_tool
from app.vnext.tools.definition import ToolAccess, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedStreamingModelClient


def _call(name="math.calculate", arguments=None, ident="calc"):
    return ToolCall(
        id=ident,
        name=name,
        arguments=arguments or {"expression": "1478-1010", "result_unit": "seconds"},
    )


def _registry():
    registry = ToolRegistry()
    register_calculate_tool(registry)
    return registry


def _tool_response(calls):
    return ModelResponse(message=AssistantMessage(tool_calls=calls))


def test_permissions_use_properties_not_tool_names():
    class Empty(BaseModel):
        pass

    invoked = []
    registry = _registry()
    for name, access, read_only in [
        ("provider.fetch", ToolAccess.EXTERNAL_DATA, True),
        ("local.read", ToolAccess.LOCAL_ARTIFACT_READ, True),
        ("local.write", ToolAccess.PURE_COMPUTE, False),
    ]:
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                input_model=Empty,
                output_model=Empty,
                access=access,
                read_only=read_only,
                handler=lambda args: invoked.append(args) or {},
            )
        )
    session = AnswerToolSession(registry)
    assert {t.name for t in session.schemas()} == {"math.calculate", "local.read"}
    result = asyncio.run(session.execute(_call("provider.fetch", {"x": 1}), timeout=1))
    assert result.status == "error"
    assert not invoked


def test_duplicate_errors_count_towards_twelve_calls():
    async def run():
        session = AnswerToolSession(_registry())
        first = await session.execute(_call(), timeout=1)
        assert first.status == "ok"
        for index in range(11):
            result = await session.execute(_call(ident=str(index)), timeout=1)
            assert "identical" in result.error.message
        assert session.calls == 12
        assert session.schemas() == []
        assert session.returned_bytes <= 240 * 1024

    asyncio.run(run())


def test_large_reads_are_not_admitted_and_utf8_is_metered():
    class Empty(BaseModel):
        pass

    class Output(BaseModel):
        value: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read",
            description="read",
            input_model=Empty,
            output_model=Output,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
            externalize_result=False,
            handler=lambda args: {"value": "中" * 20_000},
        )
    )
    session = AnswerToolSession(registry)
    result = asyncio.run(session.execute(ToolCall(id="big", name="read", arguments={}), timeout=1))
    assert result.status == "error"
    assert "byte limit" in result.error.message
    assert session.returned_bytes == session.size(result)
    assert "中" not in str(result)


def test_cumulative_bytes_reject_large_result_but_allow_narrow_recovery():
    class Input(BaseModel):
        index: int

    class Output(BaseModel):
        value: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.read",
            description="read",
            input_model=Input,
            output_model=Output,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
            externalize_result=False,
            handler=lambda args: {"value": "中" * (11000 if args.index < 8 else 1)},
        )
    )

    async def run():
        session = AnswerToolSession(registry)
        for index in range(7):
            result = await session.execute(
                ToolCall(id=str(index), name="local.read", arguments={"index": index}), timeout=1
            )
            assert result.status == "ok"
        rejected = await session.execute(
            ToolCall(id="7", name="local.read", arguments={"index": 7}), timeout=1
        )
        assert rejected.status == "error"
        recovered = await session.execute(
            ToolCall(id="8", name="local.read", arguments={"index": 8}), timeout=1
        )
        assert recovered.status == "ok"
        assert session.returned_bytes <= 240 * 1024
        assert session.calls == 9

    asyncio.run(run())


def test_runtime_rechecks_artifact_then_calculates_and_retains_history():
    async def run():
        store = SessionArtifactStore()
        ref = await store.put({"purchase_times": [1010, 1478]})
        registry = _registry()
        register_artifact_tools(
            registry,
            ArtifactReader(store, ManualResolver()),
            ArtifactGrepper(store, ManualResolver()),
        )
        read = _call(
            "artifact.read", {"ref": ref, "mode": "read", "path": "purchase_times"}, "read"
        )
        model = ScriptedModelClient(
            [
                ModelResponse.from_final("execution finished"),
                _tool_response([read]),
                _tool_response([_call()]),
                ModelResponse.from_final("间隔 468 秒，即 07:48。"),
            ]
        )
        runtime = AgentRuntime(
            model=model, tools=registry, limits=AgentLimits(application_max_output_tokens=1024)
        )
        history = SessionExecutionHistory()
        request_id = uuid4()
        history.begin_request(
            request_id, "question", initial_messages=[UserMessage(content="question")]
        )
        collector = AgentTraceCollector()
        events = [
            event
            async for event in runtime.run_stream(
                [UserMessage(content="question")],
                execution_history=history,
                request_id=request_id,
                trace_collector=collector,
            )
        ]
        assert isinstance(events[-1], AgentCompleted)
        assert "07:48" in events[-1].final.content
        assert len(model.requests) == 4
        assert {t.name for t in model.requests[1].tools} == {
            "artifact.read",
            "artifact.grep",
            "math.calculate",
        }
        results = [m for m in model.requests[-1].messages if isinstance(m, ToolResultMessage)]
        assert results[0].content["value"] == [1010, 1478]
        assert results[1].content["label"] == "07:48"
        assert any(
            isinstance(m, ToolResultMessage) and m.tool_call_id == "calc"
            for m in history.effective_messages()
        )
        assert len([e for e in events if isinstance(e, ToolStarted)]) == 2

    asyncio.run(run())


def test_runtime_exhaustion_keeps_budget_closed_in_degraded_answer():
    calls = [
        _tool_response([_call(arguments={"expression": str(i)}, ident=str(i))]) for i in range(12)
    ]
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            *calls,
            RuntimeError("primary failure"),
            ModelResponse.from_final("verified partial answer"),
        ]
    )
    asyncio.run(
        AgentRuntime(
            model=model, tools=_registry(), limits=AgentLimits(application_max_output_tokens=1024)
        ).run([UserMessage(content="question")])
    )
    assert len(model.requests) == 15
    assert model.requests[-2].tools == []
    assert model.requests[-1].tools == []
    assert any(
        m.role == "system" and "Remaining calls: 0" in m.content
        for m in model.requests[-1].messages
    )


def test_overflow_recovery_does_not_reset_budget_or_repeat_calculation():
    class Model:
        def __init__(self):
            self.requests = []
            self.responses = [
                ModelResponse.from_final("execution"),
                _tool_response([_call()]),
                ModelContextWindowError(provider_code="context_length_exceeded", status_code=400),
                _tool_response([_call(ident="duplicate-after-recovery")]),
                ModelResponse.from_final("verified 07:48"),
            ]

        async def complete(self, request):
            self.requests.append(request)
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final(
                    "retained calculation evidence", finish_reason="stop"
                )
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    model = Model()
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(
        request_id,
        "question",
        initial_messages=[
            UserMessage(content="older question"),
            ModelResponse.from_final("old background " * 40).message,
            UserMessage(content="question"),
        ],
    )
    result = asyncio.run(
        AgentRuntime(
            model,
            _registry(),
            limits=AgentLimits(
                context_window_tokens=100_000,
                application_max_output_tokens=64,
                context_safety_margin_tokens=16,
                compaction_keep_recent_tokens=1,
                compaction_reserve_tokens=160,
                context_estimate_bytes_per_token=1,
            ),
        ).run(messages, execution_history=history, request_id=request_id)
    )
    assert result.content == "verified 07:48"
    results = [m for m in model.requests[-1].messages if isinstance(m, ToolResultMessage)]
    assert results[-1].status == "error"
    assert "identical" in results[-1].error.message
    assert any(
        m.role == "system" and "Remaining calls: 10" in m.content
        for m in model.requests[-1].messages
    )


def test_verification_commentary_does_not_leak_into_final_text():
    model = ScriptedStreamingModelClient(
        [
            [ModelResponse.from_final("execution")],
            [ModelTextDelta(text="I need to check"), _tool_response([_call()])],
            [ModelTextDelta(text="07:48"), ModelResponse.from_final("07:48")],
        ]
    )

    async def run():
        return [
            event
            async for event in AgentRuntime(
                model=model,
                tools=_registry(),
                limits=AgentLimits(application_max_output_tokens=1024),
            ).run_stream([UserMessage(content="question")])
        ]

    events = asyncio.run(run())
    projector = ProductRunStateProjector(uuid4(), "assistant")
    for event in events:
        apply_runtime_event(projector, event)
    state = projector.snapshot()
    assert state.answer.text == "07:48"
    assert state.stage == "answer"
    assert state.answer.attempt_id == events[-1].attempt_id


def test_answer_text_with_tools_streams_before_terminal_response():
    async def run():
        gate = asyncio.Event()
        text_seen = asyncio.Event()

        class Model:
            def __init__(self):
                self.index = 0

            async def stream(self, request):
                self.index += 1
                if self.index == 1:
                    yield ModelResponse.from_final("execution")
                    return
                assert request.tools
                yield ModelTextDelta(text="live final text")
                await gate.wait()
                yield ModelResponse.from_final("live final text")

        events = []

        async def consume():
            runtime = AgentRuntime(
                Model(), _registry(), limits=AgentLimits(application_max_output_tokens=1024)
            )
            async for event in runtime.run_stream([UserMessage(content="question")]):
                events.append(event)
                if isinstance(event, TextDelta):
                    text_seen.set()

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(text_seen.wait(), 1)
            assert not task.done()
            assert not any(isinstance(e, AgentCompleted) for e in events)
            gate.set()
            await task
            assert events[-1].final.content == "live final text"
        finally:
            gate.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_runtime_denies_external_call_and_allows_local_correction():
    class Empty(BaseModel):
        pass

    invoked = []
    registry = _registry()
    registry.register(
        ToolDefinition(
            name="provider.fetch",
            description="fetch",
            input_model=Empty,
            output_model=Empty,
            handler=lambda args: invoked.append(args) or {},
        )
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            _tool_response([ToolCall(id="denied", name="provider.fetch", arguments={})]),
            _tool_response([_call()]),
            ModelResponse.from_final("07:48"),
        ]
    )
    result = asyncio.run(
        AgentRuntime(
            model,
            registry,
            limits=AgentLimits(application_max_output_tokens=1024),
        ).run([UserMessage(content="question")])
    )
    assert result.content == "07:48"
    assert not invoked
    denied = next(m for m in model.requests[2].messages if isinstance(m, ToolResultMessage))
    assert denied.status == "error"
    assert "not permitted" in denied.error.message


def test_cancellation_stops_answer_tool_without_retry():
    class Empty(BaseModel):
        pass

    token = CancellationToken()

    async def cancel(args):
        token.cancel()
        await asyncio.sleep(0.01)
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.compute",
            description="compute",
            input_model=Empty,
            output_model=Empty,
            access=ToolAccess.PURE_COMPUTE,
            handler=cancel,
        )
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            _tool_response([ToolCall(id="cancel", name="local.compute", arguments={})]),
        ]
    )
    with pytest.raises(AgentCancelledError):
        asyncio.run(
            AgentRuntime(
                model,
                registry,
                limits=AgentLimits(application_max_output_tokens=1024),
            ).run([UserMessage(content="question")], cancellation_token=token)
        )
    assert len(model.requests) == 2
