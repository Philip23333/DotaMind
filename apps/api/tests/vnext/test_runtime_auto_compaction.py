from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.compaction_budget import resolve_compaction_output_tokens
from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentRuntimeError,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.events import AgentFailed, CompactionFailed, ModelRequested, ToolStarted
from app.vnext.agent.generation_recovery import build_rejected_tool_call_history
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.output_budget import derive_output_budget
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.runtime_context import ContextPressure
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.errors import ModelToolCallBatchRejected
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    RawToolCall,
    RejectedAssistantMessage,
    RejectedToolCallBatch,
    ToolArgumentFailure,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _EchoInput(BaseModel):
    text: str


class _EchoOutput(BaseModel):
    text: str


def _echo_registry(*, output_size: int = 0, calls: list[str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()

    async def echo(arguments: _EchoInput) -> _EchoOutput:
        if calls is not None:
            calls.append(arguments.text)
        return _EchoOutput(text=arguments.text + ("x" * output_size))

    registry.register(
        ToolDefinition(
            name="echo",
            description="Return bounded test evidence.",
            input_model=_EchoInput,
            output_model=_EchoOutput,
            handler=echo,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _echo_call(call_id: str, text: str = "value") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="echo",
        arguments={"text": text},
    )


def _rejected_batch_error(raw_argument_size: int, *, call_count: int = 1) -> ModelProviderError:
    raw_arguments = '{"text":"' + ("x" * raw_argument_size)
    batch = RejectedToolCallBatch(
        reason="invalid_tool_arguments",
        calls=[
            RawToolCall(
                index=0,
                id="rejected-long-call",
                name="echo",
                provider_name="echo",
                raw_arguments=raw_arguments,
            )
        ]
        + [
            RawToolCall(
                index=index,
                id=f"rejected-peer-{index}",
                name="echo",
                provider_name="echo",
                raw_arguments='{"text":"peer"}',
            )
            for index in range(1, call_count)
        ],
        argument_failures=[
            ToolArgumentFailure(
                call_index=0,
                kind="invalid_json",
                message="unterminated string",
                position=len(raw_arguments),
                line=1,
                column=len(raw_arguments) + 1,
            )
        ],
        finish_reason="tool_calls",
    )
    return ModelProviderError(
        "model provider request failed",
        cause=ModelToolCallBatchRejected(batch=batch),
    )


def _history(
    initial_messages: list[object] | None = None,
) -> tuple[SessionExecutionHistory, object]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = initial_messages or [UserMessage(content="current question")]
    history.begin_request(
        request_id,
        "current question",
        initial_messages=messages,  # type: ignore[arg-type]
    )
    return history, request_id


def _history_with_old_group(*, size: int = 8_000) -> tuple[SessionExecutionHistory, object]:
    call = _echo_call("old-call", "old")
    return _history(
        [
            UserMessage(content="old question"),
            AssistantMessage(tool_calls=[call]),
            ToolResultMessage(
                tool_call_id=call.id,
                content={"text": "old evidence " + ("x" * size)},
            ),
            UserMessage(content="current question"),
        ]
    )


def _history_with_old_groups(
    *,
    first_size: int = 9_000,
    second_size: int = 1_000,
) -> tuple[SessionExecutionHistory, object]:
    first_call = _echo_call("old-call-1", "old-1")
    second_call = _echo_call("old-call-2", "old-2")
    return _history(
        [
            UserMessage(content="old question"),
            AssistantMessage(tool_calls=[first_call]),
            ToolResultMessage(
                tool_call_id=first_call.id,
                content={"text": "old evidence one " + ("x" * first_size)},
            ),
            AssistantMessage(tool_calls=[second_call]),
            ToolResultMessage(
                tool_call_id=second_call.id,
                content={"text": "old evidence two " + ("x" * second_size)},
            ),
            UserMessage(content="current question"),
        ]
    )


def _committed_history(
    source: SessionExecutionHistory,
    *,
    cut_index: int,
    summary: str = "compressed background",
) -> SessionExecutionHistory:
    history, request_id = _history(source.effective_messages())
    history.commit_compaction(
        request_id=request_id,  # type: ignore[arg-type]
        base_revision=history.revision,
        summary=summary,
        cut_index=cut_index,
    )
    return history


def _double_compacted_history(source: SessionExecutionHistory) -> SessionExecutionHistory:
    history, request_id = _history(source.effective_messages())
    history.commit_compaction(
        request_id=request_id,  # type: ignore[arg-type]
        base_revision=history.revision,
        summary="summary one",
        cut_index=3,
    )
    new_call = _echo_call("new-call", "new")
    history.set_effective(
        [
            *history.effective_messages(),
            AssistantMessage(tool_calls=[new_call]),
            ToolResultMessage(
                tool_call_id=new_call.id,
                content={"text": "new evidence " + ("x" * 6_000)},
            ),
        ]
    )
    history.commit_compaction(
        request_id=request_id,  # type: ignore[arg-type]
        base_revision=history.revision,
        summary="summary two",
        cut_index=3,
    )
    return history


def _probe_request(
    history: SessionExecutionHistory,
    registry: ToolRegistry,
    *,
    limits: AgentLimits,
) -> ModelRequest:
    runtime = AgentRuntime(ScriptedModelClient([]), registry, limits=limits)
    request, *_ = runtime._build_execution_request(  # noqa: SLF001
        request_messages=history.effective_messages(),
        execution_history=history,
        step=1,
        deadline=_Deadline(None),
    )
    return request


def _limits_for_available(
    available_input_tokens: int,
    *,
    recent_tokens: int = 1,
    test_trigger_percent: int | None = 80,
) -> AgentLimits:
    reserve = 64
    margin = 16
    return AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        compaction_keep_recent_tokens=recent_tokens,
        compaction_max_input_bytes=100_000,
        compaction_reserve_tokens=160,
        context_window_tokens=available_input_tokens + reserve + margin,
        application_max_output_tokens=reserve,
        context_safety_margin_tokens=margin,
        context_estimate_bytes_per_token=1,
        context_compaction_test_trigger_percent=test_trigger_percent,
    )


async def _run_with_timeout(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: object,
    **kwargs: object,
):
    return await asyncio.wait_for(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            **kwargs,
        ),
        timeout=3,
    )


def _run(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: object,
    **kwargs: object,
):
    return asyncio.run(_run_with_timeout(runtime, history, request_id, **kwargs))


def test_context_capacity_can_be_disabled_while_output_cap_stays_finite() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _echo_registry(),
        limits=AgentLimits(deadline_seconds=5, application_max_output_tokens=4096),
    )

    _run(runtime, *_history(), trace_collector=trace)

    assert model.requests[0].max_output_tokens == 4096
    assert model.requests[1].max_output_tokens == 4096
    assert "context_capacity_checks" not in trace.snapshot()


def test_compaction_reserve_defines_the_production_watermark_trigger() -> None:
    request = ModelRequest(
        messages=[UserMessage(content="x" * 3_200)],
        max_output_tokens=500,
    )
    small_reserve = AgentLimits(
        context_window_tokens=5_000,
        application_max_output_tokens=500,
        context_safety_margin_tokens=200,
        context_estimate_bytes_per_token=1,
        compaction_reserve_tokens=2,
    )
    large_reserve = small_reserve.model_copy(update={"compaction_reserve_tokens": 2_000})

    small = assess_request_capacity(request, small_reserve)
    large = assess_request_capacity(request, large_reserve)

    assert small is not None and large is not None
    assert small.production_trigger_input_tokens == 4_999
    assert large.production_trigger_input_tokens == 3_001
    assert small.pressure is ContextPressure.NORMAL
    assert large.pressure is ContextPressure.HIGH


@pytest.mark.parametrize("case", ["missing", "uninitialized", "mismatch"])
def test_auto_compaction_validates_history_before_execution(case: str) -> None:
    model = ScriptedModelClient([])
    calls: list[str] = []
    runtime = AgentRuntime(
        model,
        _echo_registry(calls=calls),
        limits=_limits_for_available(10_000),
    )
    if case == "missing":
        execution_history = None
        active_request_id = None
    elif case == "uninitialized":
        execution_history = SessionExecutionHistory()
        active_request_id = uuid4()
    else:
        execution_history, _ = _history()
        active_request_id = uuid4()
    before_messages = (
        execution_history.effective_messages() if execution_history is not None else None
    )
    before_records = execution_history.records if execution_history is not None else None
    before_revision = execution_history.revision if execution_history is not None else None

    with pytest.raises(ModelProtocolError):
        _run(
            runtime,
            execution_history,
            active_request_id,
        ) if execution_history is not None else asyncio.run(
            asyncio.wait_for(
                runtime.run(
                    [UserMessage(content="current question")],
                    execution_history=None,
                    request_id=None,
                ),
                timeout=3,
            )
        )

    assert model.requests == []
    assert calls == []
    if execution_history is not None:
        assert execution_history.effective_messages() == before_messages
        assert execution_history.records == before_records
        assert execution_history.revision == before_revision


def test_auto_mode_sets_request_output_cap_and_traces_budget() -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _echo_registry(),
        limits=AgentLimits(
            context_window_tokens=10_000,
            application_max_output_tokens=37,
            context_safety_margin_tokens=10,
            compaction_reserve_tokens=160,
            deadline_seconds=5,
        ),
    )

    _run(runtime, history, request_id, trace_collector=trace)

    assert model.requests[0].max_output_tokens == 37
    output_budget = trace.snapshot()["steps"][0]["output_budget"]
    assert output_budget["expected_output_tokens"] == 37
    assert output_budget["actual_output_tokens"] == model.requests[0].max_output_tokens
    checks = trace.snapshot()["context_capacity_checks"]
    assert [check["stage"] for check in checks] == ["execution", "primary_answer"]
    assert [check["phase"] for check in checks] == ["before_model", "before_model"]
    assert all(check["capacity"]["pressure"] == "normal" for check in checks)
    capacity = checks[0]["capacity"]
    assert capacity["context_window_tokens"] == 10_000
    assert capacity["estimated_input_tokens"] > 0
    assert capacity["expected_output_tokens"] == 37
    assert capacity["actual_output_tokens"] == 37
    assert capacity["remaining_output_tokens"] is not None
    assert capacity["clipped_by_context"] is False
    assert capacity["safety_margin_tokens"] == 10
    assert capacity["compaction_reserve_tokens"] == 160
    assert capacity["production_trigger_input_tokens"] == 9841
    assert capacity["test_trigger_percent"] is None
    assert capacity["trigger_input_tokens"] == capacity["production_trigger_input_tokens"]


def test_tool_schemas_are_included_in_runtime_capacity() -> None:
    limits = AgentLimits(
        context_window_tokens=10_000,
        application_max_output_tokens=64,
        context_safety_margin_tokens=16,
        compaction_reserve_tokens=160,
        deadline_seconds=5,
    )
    plain_history, plain_id = _history()
    tool_history, tool_id = _history()
    plain_trace = AgentTraceCollector()
    tool_trace = AgentTraceCollector()
    plain_model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    tool_model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(
        AgentRuntime(plain_model, ToolRegistry(), limits=limits),
        plain_history,
        plain_id,
        trace_collector=plain_trace,
    )
    _run(
        AgentRuntime(tool_model, _echo_registry(), limits=limits),
        tool_history,
        tool_id,
        trace_collector=tool_trace,
    )

    plain_bytes = plain_trace.snapshot()["context_capacity_checks"][0]["capacity"]["context_bytes"]
    tool_bytes = tool_trace.snapshot()["context_capacity_checks"][0]["capacity"]["context_bytes"]
    assert tool_bytes > plain_bytes


def test_high_watermark_compacts_once_and_rebuilds_execution_request() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens + 1)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "compressed background",
                finish_reason="stop",
                usage={"input_tokens": 9},
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector()

    _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert len(model.requests) == 2
    assert model.requests[0].tools == []
    assert model.requests[1].tools
    assert model.requests[1].max_output_tokens == 64
    assert "old evidence" not in str(model.requests[1].messages)
    snapshot = trace.snapshot()
    assert [
        item["phase"]
        for item in snapshot["context_capacity_checks"]
        if item["stage"] == "execution"
    ] == [
        "before_compaction",
        "before_model",
    ]
    assert snapshot["compaction_commits"][0]["trigger"] == "watermark"
    assert len(snapshot["compaction_commits"]) == 1


def test_rejected_batch_compacts_atomically_and_keeps_correction_count_and_budget() -> None:
    history, request_id = _history_with_old_group(size=18_000)
    registry = _echo_registry()
    first_rejection = _rejected_batch_error(12_000, call_count=2)
    assert isinstance(first_rejection.cause, ModelToolCallBatchRejected)
    rejected_assistant, rejected_results = build_rejected_tool_call_history(
        first_rejection.cause.batch
    )
    after_rejection, _ = _history(
        [*history.effective_messages(), rejected_assistant, *rejected_results]
    )
    compacted_probe = _committed_history(
        after_rejection,
        cut_index=3,
        summary="compressed background",
    )
    base_limits = AgentLimits(
        context_window_tokens=1_000_000,
        application_max_output_tokens=8_000,
        context_safety_margin_tokens=16,
        compaction_reserve_tokens=160,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
        context_estimate_bytes_per_token=1,
        deadline_seconds=5,
        answer_timeout_seconds=5,
    )
    initial_probe = _probe_request(history, registry, limits=base_limits)
    rejected_probe = _probe_request(after_rejection, registry, limits=base_limits)
    compacted_probe_request = _probe_request(compacted_probe, registry, limits=base_limits)
    selected_limits: AgentLimits | None = None
    for window in range(1_000, 40_000, 50):
        candidate_limits = base_limits.model_copy(update={"context_window_tokens": window})
        initial_capacity = assess_request_capacity(initial_probe, candidate_limits)
        rejected_capacity = assess_request_capacity(rejected_probe, candidate_limits)
        compacted_capacity = assess_request_capacity(compacted_probe_request, candidate_limits)
        assert initial_capacity is not None
        assert rejected_capacity is not None
        assert compacted_capacity is not None
        initial_budget = derive_output_budget(initial_probe, candidate_limits)
        compacted_budget = derive_output_budget(compacted_probe_request, candidate_limits)
        if (
            initial_capacity.pressure is ContextPressure.NORMAL
            and rejected_capacity.pressure in {ContextPressure.HIGH, ContextPressure.CRITICAL}
            and compacted_capacity.pressure is ContextPressure.NORMAL
            and initial_budget.actual_output_tokens < compacted_budget.actual_output_tokens
        ):
            selected_limits = candidate_limits
            break

    assert selected_limits is not None, (
        "could not find budgets that isolate post-rejection compaction"
    )

    executed: list[str] = []
    second_rejection = _rejected_batch_error(32)

    class Model:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final("compressed background", finish_reason="stop")
            if request.step == 1:
                raise _rejected_batch_error(12_000, call_count=2)
            if request.step == 2:
                raise second_rejection
            if request.step == 3:
                return ModelResponse.from_assistant(
                    AssistantMessage(tool_calls=[_echo_call("corrected-call", "recovered")])
                )
            if request.step == 4:
                return ModelResponse.from_final("execution done")
            return ModelResponse.from_final("answer")

    model = Model()
    registry = _echo_registry(calls=executed)
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, registry, limits=selected_limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "answer"
    assert executed == ["recovered"]
    snapshot = trace.snapshot()
    execution_checks = [
        item for item in snapshot["context_capacity_checks"] if item["stage"] == "execution"
    ]
    assert execution_checks[0]["phase"] == "before_model"
    assert execution_checks[0]["capacity"]["pressure"] == "normal"
    assert execution_checks[1]["phase"] == "before_compaction"
    assert execution_checks[1]["capacity"]["pressure"] in {"high", "critical"}
    assert execution_checks[2]["phase"] == "before_model"
    assert execution_checks[2]["capacity"]["pressure"] == "normal"
    assert [item["consecutive_rejections"] for item in snapshot["generation_recoveries"]] == [1, 2]
    assert [commit["trigger"] for commit in snapshot["compaction_commits"]] == ["watermark"]
    assert len(history.compaction_records) == 1

    retry_request = next(
        request for request in model.requests if request.step == 2 and request.tools
    )
    assert measure_request_context_bytes(retry_request) < measure_request_context_bytes(
        rejected_probe
    )
    retry_budget = derive_output_budget(retry_request, selected_limits)
    initial_budget = derive_output_budget(initial_probe, selected_limits)
    assert retry_request.max_output_tokens == retry_budget.actual_output_tokens
    assert retry_budget.actual_output_tokens > initial_budget.actual_output_tokens
    step_two_trace = next(item for item in snapshot["steps"] if item["step"] == 2)
    assert (
        step_two_trace["output_budget"]["actual_output_tokens"]
        == retry_request.max_output_tokens
    )

    rejection_index = next(
        index
        for index, message in enumerate(retry_request.messages)
        if isinstance(message, RejectedAssistantMessage)
    )
    rejected_message = retry_request.messages[rejection_index]
    assert isinstance(rejected_message, RejectedAssistantMessage)
    assert len(rejected_message.tool_calls) == 2
    assert len(rejected_message.tool_calls[0].raw_arguments) > 12_000
    paired_results = retry_request.messages[
        rejection_index + 1 : rejection_index + 1 + len(rejected_message.tool_calls)
    ]
    assert len(paired_results) == 2
    assert all(isinstance(message, ToolResultMessage) for message in paired_results)
    assert [message.tool_call_id for message in paired_results] == [
        call.id for call in rejected_message.tool_calls
    ]
    assert all(message.executed is False for message in paired_results)
    assert retry_request.max_output_tokens is not None
    assert retry_request.metadata.get("purpose") is None

    summary_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") == "context_compaction"
    ]
    assert summary_requests
    assert all(request.tools == [] for request in summary_requests)
    for request in summary_requests:
        kind = request.metadata["compaction_kind"]
        assert request.max_output_tokens == resolve_compaction_output_tokens(
            kind=kind,
            reserve_tokens=selected_limits.compaction_reserve_tokens,
            model_max_output_tokens=selected_limits.compaction_model_max_output_tokens,
        )


def test_production_formula_triggers_a_real_compaction_without_test_override() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        context_window_tokens=1_000_000,
        application_max_output_tokens=64,
        context_safety_margin_tokens=16,
        context_estimate_bytes_per_token=1,
        compaction_reserve_tokens=160,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
    )
    candidate = _probe_request(history, registry, limits=probe_limits)
    estimate = assess_request_capacity(candidate, probe_limits)
    assert estimate is not None
    limits = probe_limits.model_copy(
        update={"context_window_tokens": estimate.estimated_input_tokens + 120}
    )
    actual_candidate = _probe_request(history, registry, limits=limits)
    actual_capacity = assess_request_capacity(actual_candidate, limits)
    assert actual_capacity is not None
    assert actual_capacity.pressure is ContextPressure.HIGH
    assert actual_capacity.test_trigger_percent is None

    model = ScriptedModelClient(
        [
            ModelResponse.from_final("compressed background", finish_reason="stop"),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector()
    _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert len(trace.snapshot()["compaction_commits"]) == 1
    assert trace.snapshot()["compaction_commits"][0]["trigger"] == "watermark"
    assert (
        trace.snapshot()["context_capacity_checks"][0]["capacity"]["trigger_input_tokens"]
        == trace.snapshot()["context_capacity_checks"][0]["capacity"][
            "production_trigger_input_tokens"
        ]
    )
    assert model.requests[0].metadata.get("purpose") == "context_compaction"
    assert len(model.requests) == 3


def test_test_override_compacts_the_same_history_before_production_boundary() -> None:
    probe_history, _ = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = AgentLimits(
        context_window_tokens=1_000_000,
        application_max_output_tokens=64,
        context_safety_margin_tokens=16,
        context_estimate_bytes_per_token=1,
        compaction_reserve_tokens=160,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
    )
    request = _probe_request(probe_history, registry, limits=probe_limits)
    capacity = assess_request_capacity(request, probe_limits)
    assert capacity is not None
    estimated_input = capacity.estimated_input_tokens
    window = estimated_input * 4

    def limits(test_percent: int | None) -> AgentLimits:
        return AgentLimits(
            deadline_seconds=5,
            answer_timeout_seconds=5,
            context_window_tokens=window,
            application_max_output_tokens=64,
            context_safety_margin_tokens=16,
            context_estimate_bytes_per_token=1,
            compaction_reserve_tokens=160,
            compaction_keep_recent_tokens=1,
            compaction_max_input_bytes=100_000,
            context_compaction_test_trigger_percent=test_percent,
        )

    production_history, production_request_id = _history_with_old_group()
    production_model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    production_trace = AgentTraceCollector()
    _run(
        AgentRuntime(production_model, _echo_registry(), limits=limits(None)),
        production_history,
        production_request_id,
        trace_collector=production_trace,
    )

    test_history, test_request_id = _history_with_old_group()
    test_model = ScriptedModelClient(
        [
            ModelResponse.from_final("compressed background", finish_reason="stop"),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    test_trace = AgentTraceCollector()
    _run(
        AgentRuntime(test_model, _echo_registry(), limits=limits(20)),
        test_history,
        test_request_id,
        trace_collector=test_trace,
    )

    production_snapshot = production_trace.snapshot()
    test_snapshot = test_trace.snapshot()
    assert production_snapshot.get("compaction_commits", []) == []
    production_capacity = production_snapshot["context_capacity_checks"][0]["capacity"]
    assert production_capacity["pressure"] == "normal"
    assert len(production_model.requests) == 2
    assert len(test_snapshot["compaction_commits"]) == 1
    assert test_snapshot["compaction_commits"][0]["trigger"] == "watermark"
    test_capacity = test_snapshot["context_capacity_checks"][0]["capacity"]
    assert test_capacity["estimated_input_tokens"] == production_capacity["estimated_input_tokens"]
    assert test_capacity["test_trigger_percent"] == 20
    assert test_capacity["trigger_input_tokens"] < test_capacity["production_trigger_input_tokens"]
    assert len(test_model.requests) == 3
    summary_request = next(
        item for item in test_model.requests if item.metadata.get("purpose") == "context_compaction"
    )
    assert summary_request.max_output_tokens == resolve_compaction_output_tokens(
        kind="history",
        reserve_tokens=160,
        model_max_output_tokens=None,
    )

    explicit_history, explicit_request_id = _history_with_old_group()
    explicit_model = ScriptedModelClient(
        [
            ModelResponse.from_final("compressed background", finish_reason="stop"),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    explicit_trace = AgentTraceCollector()
    _run(
        AgentRuntime(explicit_model, _echo_registry(), limits=limits(None)),
        explicit_history,
        explicit_request_id,
        compact_before_steps=(1,),
        trace_collector=explicit_trace,
    )
    explicit_summary = next(
        item
        for item in explicit_model.requests
        if item.metadata.get("purpose") == "context_compaction"
    )
    assert explicit_summary == summary_request
    assert (
        explicit_trace.snapshot()["compaction_commits"][0]["cut_index"]
        == test_snapshot["compaction_commits"][0]["cut_index"]
    )


def test_explicit_compaction_wins_when_watermark_is_also_high() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens + 1)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("compressed background", finish_reason="stop"),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector()

    _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        compact_before_steps=(1,),
        trace_collector=trace,
    )

    assert len(model.requests) == 2
    assert len(trace.snapshot()["compaction_calls"]) == 1
    assert trace.snapshot()["compaction_commits"][0]["trigger"] == "explicit"


def test_high_without_a_compactable_range_continues_to_model() -> None:
    history, request_id = _history()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    candidate = _probe_request(history, registry, limits=probe_limits)
    capacity = assess_request_capacity(candidate, probe_limits)
    assert capacity is not None
    limits = _limits_for_available(capacity.estimated_input_tokens + 10)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()

    _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert len(model.requests) == 1
    assert model.requests[0].tools
    assert "compaction_calls" not in trace.snapshot()
    execution_checks = [
        item for item in trace.snapshot()["context_capacity_checks"] if item["stage"] == "execution"
    ]
    assert execution_checks[-1]["capacity"]["pressure"] == "high"


def test_critical_after_compaction_enters_answer_capacity_exit() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens - 64)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "compressed background",
                finish_reason="stop",
                usage={"n": 1},
            ),
            ModelResponse.from_final("execution"),
        ]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert "available context budget" in result.content
    assert len(model.requests) == 1
    assert len(trace.snapshot()["compaction_commits"]) == 1
    assert trace.snapshot()["execution_outcome"]["reason"] == "context_capacity"
    assert [
        item["phase"]
        for item in trace.snapshot()["context_capacity_checks"]
        if item["stage"] == "execution"
    ] == [
        "before_compaction",
        "before_model",
    ]


def test_auto_compaction_cancellation_does_not_commit_or_execute() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens + 1)
    token = CancellationToken()

    class CancelOnSummary:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            token.cancel()
            return ModelResponse.from_final(
                "summary",
                finish_reason="stop",
                usage={"input_tokens": 3},
            )

    model = CancelOnSummary()
    trace = AgentTraceCollector()

    with pytest.raises(AgentCancelledError):
        _run(
            AgentRuntime(model, registry, limits=limits),
            history,
            request_id,
            cancellation_token=token,
            trace_collector=trace,
        )

    assert len(model.requests) == 1
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {"input_tokens": 3}


def test_continuous_watermarks_compact_again_after_new_tool_output() -> None:
    history, request_id = _history_with_old_groups()
    calls: list[str] = []
    registry = _echo_registry(output_size=6_000, calls=calls)
    probe_limits = _limits_for_available(100_000, recent_tokens=500)
    compacted = _double_compacted_history(history)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(
        final_capacity.estimated_input_tokens + 1_536,
        recent_tokens=500,
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("summary one", finish_reason="stop"),
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_echo_call("new-call", "new")])
            ),
            ModelResponse.from_final("summary two history", finish_reason="stop"),
            ModelResponse.from_final("summary two turn prefix", finish_reason="stop"),
            ModelResponse.from_final("execution final"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector()
    events: list[object] = []

    async def collect(event: object) -> None:
        events.append(event)

    _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        event_sink=collect,
        trace_collector=trace,
    )

    assert calls == ["new"], {
        "requests": [(request.step, request.metadata) for request in model.requests],
        "compaction_calls": trace.snapshot().get("compaction_calls"),
        "commits": trace.snapshot().get("compaction_commits"),
        "outcome": trace.snapshot().get("execution_outcome"),
    }
    assert len(model.requests) == 6, {
        "requests": [
            (request.step, request.metadata, request.max_output_tokens)
            for request in model.requests
        ],
        "calls": [
            (call["step"], call["kind"], call["status"], call["error_code"])
            for call in trace.snapshot()["compaction_calls"]
        ],
        "commits": trace.snapshot()["compaction_commits"],
        "checks": [
            (
                item["stage"],
                item["phase"],
                item["capacity"]["pressure"],
                item["capacity"]["context_bytes"],
                item["capacity"]["test_input_budget_tokens"],
            )
            for item in trace.snapshot()["context_capacity_checks"]
        ],
        "outcome": trace.snapshot()["execution_outcome"],
    }
    assert [request.step for request in (model.requests[1], model.requests[4])] == [1, 2]
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [
        1,
        2,
        3,
    ]
    assert [event.step for event in events if isinstance(event, ToolStarted)] == [1]

    snapshot = trace.snapshot()
    commits = snapshot["compaction_commits"]
    assert [commit["step"] for commit in commits] == [1, 2]
    assert [call["kind"] for call in snapshot["compaction_calls"]] == [
        "turn_prefix",
        "history",
        "turn_prefix",
    ]
    assert all(commit["trigger"] == "watermark" for commit in commits)
    assert all(commit["new_revision"] > commit["base_revision"] for commit in commits)
    before_compaction = [
        item
        for item in snapshot["context_capacity_checks"]
        if item["stage"] == "execution" and item["phase"] == "before_compaction"
    ]
    assert [item["capacity"]["pressure"] for item in before_compaction] == [
        "critical",
        "high",
    ]
    before_model = [
        item
        for item in snapshot["context_capacity_checks"]
        if item["stage"] == "execution" and item["phase"] == "before_model"
    ]
    assert [item["capacity"]["context_bytes"] for item in before_model] == [
        measure_request_context_bytes(model.requests[1]),
        measure_request_context_bytes(model.requests[4]),
    ]
    assert [item["step"] for item in snapshot["steps"] if "model_request" in item] == [
        1,
        2,
        3,
    ]


def test_tool_schema_can_cross_the_watermark_trigger_line() -> None:
    history, _ = _history()
    probe_limits = _limits_for_available(100_000)
    plain_request = _probe_request(history, ToolRegistry(), limits=probe_limits)
    tool_request = _probe_request(history, _echo_registry(), limits=probe_limits)
    plain_capacity = assess_request_capacity(plain_request, probe_limits)
    tool_capacity = assess_request_capacity(tool_request, probe_limits)
    assert plain_capacity is not None and tool_capacity is not None
    assert tool_capacity.estimated_input_tokens > plain_capacity.estimated_input_tokens

    crossing: tuple[AgentLimits, object, object] | None = None
    for test_trigger_percent in (99, 95, 90, 80):
        for available in range(
            plain_capacity.estimated_input_tokens + 1,
            tool_capacity.estimated_input_tokens * 2 + 1,
        ):
            limits = _limits_for_available(
                available,
                test_trigger_percent=test_trigger_percent,
            )
            plain = assess_request_capacity(plain_request, limits)
            with_tool = assess_request_capacity(tool_request, limits)
            if (
                plain is not None
                and with_tool is not None
                and plain.pressure is ContextPressure.NORMAL
                and with_tool.pressure is ContextPressure.HIGH
            ):
                crossing = (limits, plain, with_tool)
                break
        if crossing is not None:
            break

    assert crossing is not None
    _, plain, with_tool = crossing
    assert plain.pressure is ContextPressure.NORMAL
    assert with_tool.pressure is ContextPressure.HIGH


def test_critical_without_compactable_range_fails_before_business_execution() -> None:
    history, request_id = _history()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    candidate = _probe_request(history, registry, limits=probe_limits)
    capacity = assess_request_capacity(candidate, probe_limits)
    assert capacity is not None
    limits = _limits_for_available(capacity.estimated_input_tokens - 64)
    before_messages = history.effective_messages()
    before_records = history.records
    model = ScriptedModelClient([])
    trace = AgentTraceCollector()
    events: list[object] = []

    async def collect(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        event_sink=collect,
        trace_collector=trace,
    )

    assert "available context budget" in result.content
    assert model.requests == []
    assert history.effective_messages()[:-1] == before_messages
    assert history.records[:-1] == before_records
    assert history.compaction_records == ()
    assert trace.snapshot()["execution_outcome"]["reason"] == "context_capacity"
    assert not any(isinstance(event, (ModelRequested, ToolStarted)) for event in events)


def test_auto_summary_validation_failure_does_not_commit_or_execute() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens + 1)
    before_messages = history.effective_messages()
    before_records = history.records
    model = ScriptedModelClient([ModelResponse.from_final("truncated", finish_reason="length")])
    trace = AgentTraceCollector()
    events: list[object] = []

    async def collect(event: object) -> None:
        events.append(event)

    with pytest.raises(AgentRuntimeError) as error:
        _run(
            AgentRuntime(model, registry, limits=limits),
            history,
            request_id,
            event_sink=collect,
            trace_collector=trace,
        )

    assert error.value.code == "context_compaction_failed"
    assert error.value.details == {
        "trigger": "watermark",
        "stage": "execution",
        "summary_kind": "history",
        "reason_code": "summary_output_truncated",
        "attempt_count": 1,
    }
    assert len(model.requests) == 1
    assert model.requests[0].tools == []
    assert not any(isinstance(event, (ModelRequested, ToolStarted)) for event in events)
    assert [
        type(event) for event in events if isinstance(event, CompactionFailed | AgentFailed)
    ] == [
        CompactionFailed,
        AgentFailed,
    ]
    assert history.effective_messages() == before_messages
    assert history.records == before_records
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"][0]["status"] == "failed"


def test_summary_input_byte_limit_fails_before_model_call_or_commit() -> None:
    history, request_id = _history_with_old_group()
    limits = _limits_for_available(100_000, test_trigger_percent=1).model_copy(
        update={"compaction_max_input_bytes": 1}
    )
    model = ScriptedModelClient([])
    trace = AgentTraceCollector()
    before_messages = history.effective_messages()
    before_records = history.records

    with pytest.raises(AgentRuntimeError) as error:
        _run(
            AgentRuntime(model, _echo_registry(), limits=limits),
            history,
            request_id,
            trace_collector=trace,
        )

    assert error.value.code == "context_compaction_failed"
    assert error.value.details["reason_code"] == "summary_input_too_large"
    assert model.requests == []
    assert history.effective_messages() == before_messages
    assert history.records == before_records
    assert history.compaction_records == ()
