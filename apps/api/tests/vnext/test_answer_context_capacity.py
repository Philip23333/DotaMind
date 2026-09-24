from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest
from pydantic import BaseModel

from app.vnext.agent.answer_stage import (
    AnswerContextBuilder,
    AnswerProjectionMode,
    ExecutionOutcome,
    ExecutionStopReason,
    resolve_answer,
)
from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import AgentCancelledError, CompactionFailedError
from app.vnext.agent.events import ModelRequested, ToolStarted
from app.vnext.agent.instructions import ANSWER_INSTRUCTION, DEGRADED_ANSWER_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import (
    AgentRuntime,
    CancellationToken,
    _build_answer_request,
    _project_session_context,
)
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient
from tests.vnext.test_runtime_auto_compaction import (
    _committed_history,
    _echo_call,
    _echo_registry,
    _history,
    _history_with_old_group,
    _history_with_old_groups,
    _limits_for_available,
    _probe_request,
    _run,
)
from tests.vnext.test_runtime_compaction_loop import _compaction_workflow_registry


class _LargeInput(BaseModel):
    query: str


class _LargeOutput(BaseModel):
    value: str


def _large_schema_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def large(_: _LargeInput) -> _LargeOutput:
        return _LargeOutput(value="unused")

    registry.register(
        ToolDefinition(
            name="large_schema_tool",
            description="A deliberately large capability description. " + ("schema " * 900),
            input_model=_LargeInput,
            output_model=_LargeOutput,
            handler=large,
        )
    )
    return registry


def _history_with_new_tool(
    source: SessionExecutionHistory,
    *,
    output_size: int,
) -> tuple[SessionExecutionHistory, object]:
    history, request_id = _history(source.effective_messages())
    call = _echo_call("new-call", "new")
    history.set_effective(
        [
            *history.effective_messages(),
            AssistantMessage(tool_calls=[call]),
            ToolResultMessage(
                tool_call_id=call.id,
                content={"text": "new evidence " + ("x" * output_size)},
            ),
        ]
    )
    return history, request_id


def _answer_request(
    history: SessionExecutionHistory,
    *,
    limits: AgentLimits,
    execution_messages: Sequence[object] | None = None,
    instruction: str = ANSWER_INSTRUCTION,
    projection_mode: AnswerProjectionMode = AnswerProjectionMode.PRIMARY,
    reason: ExecutionStopReason = ExecutionStopReason.MODEL_DONE,
    step: int = 2,
):
    projected_messages = (
        history.effective_messages() if execution_messages is None else execution_messages
    )
    outcome = ExecutionOutcome(reason=reason, steps=max(1, step - 1))
    resolution = resolve_answer(outcome=outcome, task_state_coordinator=None)
    context = AnswerContextBuilder().build(
        execution_messages=projected_messages,
        outcome=outcome,
        task_state_coordinator=None,
        resolution=resolution,
        projection_mode=projection_mode,
        effective_history_embedded=True,
    )
    return _build_answer_request(
        instruction=instruction,
        messages=_project_session_context(projected_messages, history),
        context=context,
        step=step,
        max_output_tokens=(
            limits.context_output_reserve_tokens
            if limits.context_window_tokens is not None
            else None
        ),
    )


def _find_limits(
    estimates: dict[str, object],
    predicate: Callable[[dict[str, object]], bool],
    *,
    recent_tokens: int = 1,
    max_steps: int = 3,
) -> AgentLimits:
    numeric_estimates = [
        value for name, value in estimates.items() if name != "requests" and isinstance(value, int)
    ]
    lower = max(1, min(numeric_estimates))
    upper = max(numeric_estimates) * 2 + 32
    for available in range(lower, upper + 1):
        limits = _limits_for_available(
            available,
            recent_tokens=recent_tokens,
            max_steps=max_steps,
        )
        capacities = {
            name: assess_request_capacity(request, limits)
            for name, request in estimates["requests"].items()  # type: ignore[union-attr]
        }
        if predicate(capacities):
            return limits
    raise AssertionError(f"no capacity boundary found for estimates: {estimates}")


def _capacity_estimates(
    requests: dict[str, object],
    *,
    probe_limits: AgentLimits,
) -> dict[str, int | dict[str, object]]:
    capacities = {
        name: assess_request_capacity(request, probe_limits) for name, request in requests.items()
    }
    return {
        "requests": requests,
        **{
            name: capacity.estimated_input_tokens
            for name, capacity in capacities.items()
            if capacity is not None
        },
    }


def _capacity_pressure(capacities: dict[str, object], name: str) -> str:
    capacity = capacities[name]
    assert capacity is not None
    return capacity.pressure.value  # type: ignore[union-attr]


def test_execution_critical_can_use_a_tool_free_answer_request() -> None:
    history, request_id = _history()
    registry = _large_schema_registry()
    probe_limits = _limits_for_available(100_000)
    execution_request = _probe_request(history, registry, limits=probe_limits)
    answer_request = _answer_request(
        history,
        limits=probe_limits,
        reason=ExecutionStopReason.CONTEXT_CAPACITY,
    )
    estimates = _capacity_estimates(
        {"execution": execution_request, "answer": answer_request},
        probe_limits=probe_limits,
    )
    limits = _find_limits(
        estimates,
        lambda capacities: (
            _capacity_pressure(capacities, "execution") == "critical"
            and _capacity_pressure(capacities, "answer") != "critical"
        ),
    )
    model = ScriptedModelClient([ModelResponse.from_final("answer")])
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

    assert result.content == "answer"
    assert len(model.requests) == 1
    assert model.requests[0].tools == []
    assert model.requests[0].max_output_tokens == limits.context_output_reserve_tokens
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [2]
    assert not any(isinstance(event, ToolStarted) for event in events)
    checks = trace.snapshot()["context_capacity_checks"]
    assert checks[0]["stage"] == "execution"
    assert checks[0]["capacity"]["pressure"] == "critical"
    assert checks[-1]["stage"] == "primary_answer"
    assert checks[-1]["capacity"]["pressure"] != "critical"
    assert trace.snapshot()["execution_outcome"]["reason"] == "context_capacity"


def _answer_compaction_case() -> tuple[
    SessionExecutionHistory,
    object,
    ToolRegistry,
    AgentLimits,
]:
    history, request_id = _history_with_old_group(size=1_000)
    registry = _echo_registry(output_size=2_500)
    after_tool, _ = _history_with_new_tool(history, output_size=2_500)
    compacted = _committed_history(after_tool, cut_index=4, summary="answer summary")
    probe_limits = _limits_for_available(100_000, recent_tokens=500, max_steps=2)
    execution_request = _probe_request(history, registry, limits=probe_limits)
    post_tool_execution = _probe_request(after_tool, registry, limits=probe_limits)
    before_answer = _answer_request(after_tool, limits=probe_limits, step=3)
    after_answer = _answer_request(compacted, limits=probe_limits, step=3)
    estimates = _capacity_estimates(
        {
            "execution": execution_request,
            "post_tool_execution": post_tool_execution,
            "before_answer": before_answer,
            "after_answer": after_answer,
        },
        probe_limits=probe_limits,
    )
    limits = _find_limits(
        estimates,
        lambda capacities: (
            _capacity_pressure(capacities, "execution") != "critical"
            and _capacity_pressure(capacities, "post_tool_execution") == "normal"
            and _capacity_pressure(capacities, "before_answer") in {"high", "critical"}
            and _capacity_pressure(capacities, "after_answer") != "critical"
        ),
        recent_tokens=500,
        max_steps=2,
    )
    return history, request_id, registry, limits


def test_primary_answer_can_compact_an_independently_large_answer_context() -> None:
    history, request_id, registry, limits = _answer_compaction_case()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_echo_call("new-call", "new")])
            ),
            ModelResponse.from_final("execution", finish_reason="stop"),
            ModelResponse.from_final("answer history summary", finish_reason="stop"),
            ModelResponse.from_final("answer summary", finish_reason="stop"),
            ModelResponse.from_final("answer"),
        ]
    )
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

    assert result.content == "answer"
    assert len(model.requests) == 5
    assert model.requests[0].tools
    compaction_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") == "context_compaction"
    ]
    assert [request.metadata["compaction_kind"] for request in compaction_requests] == [
        "history",
        "turn_prefix",
    ]
    assert model.requests[4].tools == []
    assert "old evidence" not in str(model.requests[4].messages)
    assert "answer history summary" in str(model.requests[4].messages)
    assert "answer summary" in str(model.requests[4].messages)
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [1, 2, 3]
    assert [commit["step"] for commit in trace.snapshot()["compaction_commits"]] == [3]
    assert trace.snapshot()["compaction_commits"][0]["trigger"] == "watermark"
    primary_checks = [
        item
        for item in trace.snapshot()["context_capacity_checks"]
        if item["stage"] == "primary_answer"
    ]
    assert [item["phase"] for item in primary_checks] == [
        "before_compaction",
        "before_model",
    ]
    assert primary_checks[-1]["capacity"]["context_bytes"] == measure_request_context_bytes(
        model.requests[4]
    )


def test_execution_capacity_attempt_is_not_repeated_by_primary_answer() -> None:
    history, request_id = _history_with_old_group()
    registry = _echo_registry()
    probe_limits = _limits_for_available(100_000)
    compacted = _committed_history(history, cut_index=3)
    final_request = _probe_request(compacted, registry, limits=probe_limits)
    final_capacity = assess_request_capacity(final_request, probe_limits)
    assert final_capacity is not None
    limits = _limits_for_available(final_capacity.estimated_input_tokens)
    model = ScriptedModelClient(
        [ModelResponse.from_final("compressed background", finish_reason="stop")]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert "context budget was exhausted" in result.content
    assert len(trace.snapshot()["compaction_calls"]) == 1
    assert [commit["step"] for commit in trace.snapshot()["compaction_commits"]] == [1]
    assert not any(
        item["stage"] == "primary_answer" and item["phase"] == "before_compaction"
        for item in trace.snapshot()["context_capacity_checks"]
    )
    assert len(model.requests) == 1


def test_final_message_does_not_reopen_primary_compaction_gate() -> None:
    history, request_id = _history_with_old_groups()
    registry = _echo_registry(output_size=4_000)
    probe_limits = _limits_for_available(100_000, recent_tokens=1, max_steps=2)
    first_compacted, _ = _history_with_old_groups()
    first_compacted = _committed_history(first_compacted, cut_index=3, summary="summary one")
    after_tool, _ = _history_with_new_tool(first_compacted, output_size=4_000)
    final_history = _committed_history(after_tool, cut_index=3, summary="summary two")
    final_execution = FinalMessage(content="execution")
    requests = {
        "initial": _probe_request(history, registry, limits=probe_limits),
        "after_first": _probe_request(first_compacted, registry, limits=probe_limits),
        "after_tool": _probe_request(after_tool, registry, limits=probe_limits),
        "answer_before": _answer_request(after_tool, limits=probe_limits, step=3),
        "answer_after": _answer_request(
            final_history,
            limits=probe_limits,
            execution_messages=[*final_history.effective_messages(), final_execution],
            step=3,
        ),
    }
    estimates = _capacity_estimates(requests, probe_limits=probe_limits)
    limits = _find_limits(
        estimates,
        lambda capacities: (
            _capacity_pressure(capacities, "initial") == "critical"
            and _capacity_pressure(capacities, "after_first") != "critical"
            and _capacity_pressure(capacities, "after_tool") != "critical"
            and _capacity_pressure(capacities, "answer_before") in {"high", "critical"}
            and _capacity_pressure(capacities, "answer_after") != "critical"
        ),
        recent_tokens=1,
        max_steps=2,
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("summary one", finish_reason="stop"),
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_echo_call("new-call", "new")])
            ),
            ModelResponse.from_final("summary two", finish_reason="stop"),
            ModelResponse.from_final("execution", finish_reason="stop"),
        ]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, registry, limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "execution"
    assert len(model.requests) == 4
    assert [commit["step"] for commit in trace.snapshot()["compaction_commits"]] == [1]
    assert [call["step"] for call in trace.snapshot()["compaction_calls"]] == [1]
    assert [
        item["stage"]
        for item in trace.snapshot()["context_capacity_checks"]
        if item["phase"] == "before_compaction"
    ] == ["execution", "execution"]
    primary_checks = [
        item
        for item in trace.snapshot()["context_capacity_checks"]
        if item["stage"] == "primary_answer"
    ]
    assert [item["phase"] for item in primary_checks] == ["before_model"]
    assert primary_checks[0]["capacity"]["pressure"] in {"normal", "high"}
    assert history.summary == "summary one"


def test_new_tool_progress_allows_real_primary_compaction() -> None:
    history, request_id = _history_with_old_groups()
    coordinator = TaskStateCoordinator()
    registry = _compaction_workflow_registry(coordinator)
    limits = _limits_for_available(16_000, recent_tokens=500, max_steps=3)
    plan_call = ToolCall(
        id="plan-call",
        name="task.plan",
        arguments={
            "items": [
                {"key": "first", "objective": "Collect first evidence"},
                {"key": "second", "objective": "Collect second evidence"},
            ]
        },
    )
    read_call = ToolCall(
        id="read-new",
        name="artifact.read",
        arguments={
            "ref": "artifact:test",
            "mode": "read",
            "path": "rows",
            "task_key": "first",
        },
    )
    checkpoint_call = ToolCall(
        id="checkpoint-first",
        name="task.checkpoint",
        arguments={
            "key": "first",
            "value": {"status": "first complete", "details": "x" * 4_000},
            "source_tool_call_ids": ["read-new"],
        },
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("summary before tool", finish_reason="stop"),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[plan_call])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[read_call])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[checkpoint_call])),
            ModelResponse.from_final("history after tool", finish_reason="stop"),
            ModelResponse.from_final("turn prefix after tool", finish_reason="stop"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector()
    events: list[object] = []

    async def collect(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(
            model,
            registry,
            limits=limits,
            task_state_coordinator=coordinator,
        ),
        history,
        request_id,
        event_sink=collect,
        trace_collector=trace,
    )

    snapshot = trace.snapshot()
    assert result.content == "answer", {
        "commits": [(item["step"], item["trigger"]) for item in snapshot["compaction_commits"]],
        "calls": [
            (item["step"], item["kind"], item["status"], item["error_code"])
            for item in snapshot["compaction_calls"]
        ],
        "checks": [
            (
                item["stage"],
                item["phase"],
                item["capacity"]["pressure"],
                item["capacity"]["context_bytes"],
            )
            for item in snapshot["context_capacity_checks"]
        ],
        "requests": [
            (request.step, request.metadata, request.max_output_tokens)
            for request in model.requests
        ],
        "answer": result.content,
    }
    assert [commit["step"] for commit in snapshot["compaction_commits"]] == [1, 4]
    assert len(snapshot["compaction_calls"]) == 3
    assert (
        sum(request.metadata.get("purpose") == "context_compaction" for request in model.requests)
        == 3
    )
    tool_starts = [event.tool_name for event in events if isinstance(event, ToolStarted)]
    assert tool_starts.count("artifact.read") == 1
    assert tool_starts.count("task.checkpoint") == 1
    assert "history after tool" in str(model.requests[-1].messages)
    assert "turn prefix after tool" in str(model.requests[-1].messages)
    assert [
        item["stage"]
        for item in snapshot["context_capacity_checks"]
        if item["phase"] == "before_compaction"
    ] == ["execution", "primary_answer"]


def _answer_capacity_case() -> tuple[SessionExecutionHistory, object, AgentLimits]:
    history, request_id = _history()
    probe_limits = _limits_for_available(100_000)
    execution = _probe_request(history, ToolRegistry(), limits=probe_limits)
    primary = _answer_request(history, limits=probe_limits)
    degraded = _answer_request(
        history,
        limits=probe_limits,
        instruction=DEGRADED_ANSWER_INSTRUCTION,
        projection_mode=AnswerProjectionMode.DEGRADED,
    )
    estimates = _capacity_estimates(
        {"execution": execution, "primary": primary, "degraded": degraded},
        probe_limits=probe_limits,
    )
    limits = _find_limits(
        estimates,
        lambda capacities: (
            _capacity_pressure(capacities, "execution") == "normal"
            and _capacity_pressure(capacities, "primary") == "critical"
        ),
    )
    return history, request_id, limits


def test_primary_critical_checks_degraded_answer_capacity() -> None:
    history, request_id, limits = _answer_capacity_case()
    model = ScriptedModelClient([ModelResponse.from_final("execution")])
    trace = AgentTraceCollector()
    events: list[object] = []

    async def collect(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(model, ToolRegistry(), limits=limits),
        history,
        request_id,
        event_sink=collect,
        trace_collector=trace,
    )

    assert "available context budget" in result.content
    assert [request.step for request in model.requests] == [1]
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [1]
    attempts = trace.snapshot()["answer_attempts"]
    assert attempts[0]["error_code"] == "context_capacity_exceeded"
    assert trace.snapshot()["context_capacity_checks"][-1]["stage"] == "degraded_answer"
    assert trace.snapshot()["context_capacity_checks"][-1]["capacity"]["pressure"] == "critical"
    assert trace.snapshot().get("compaction_calls", []) == []


def test_primary_answer_compaction_failure_does_not_commit() -> None:
    history, request_id, registry, limits = _answer_compaction_case()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_echo_call("new-call", "new")])
            ),
            ModelResponse.from_final("execution", finish_reason="stop"),
            ModelResponse.from_final(" ", finish_reason="stop"),
        ]
    )
    trace = AgentTraceCollector()
    events: list[object] = []

    with pytest.raises(CompactionFailedError) as error:
        _run(
            AgentRuntime(model, registry, limits=limits),
            history,
            request_id,
            trace_collector=trace,
            event_sink=lambda event: events.append(event),
        )

    assert error.value.code == "context_compaction_failed"
    assert error.value.stage == "primary_answer"
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"][-1]["status"] == "failed"
    assert trace.snapshot()["compaction_calls"][-1]["error_code"] == "empty_summary"
    assert trace.snapshot()["compaction_failures"] == [
        {
            "step": 3,
            "trigger": "watermark",
            "stage": "primary_answer",
            "summary_kind": "history",
            "reason_code": "empty_summary",
            "attempt_count": 1,
        }
    ]
    assert [request.metadata.get("purpose") for request in model.requests] == [
        None,
        None,
        "context_compaction",
    ]
    assert not trace.snapshot().get("answer_attempts")
    assert [event.kind for event in events if hasattr(event, "kind")][-2:] == [
        "compaction_failed",
        "agent_failed",
    ]


def test_primary_answer_compaction_cancellation_propagates_without_commit() -> None:
    history, request_id, registry, limits = _answer_compaction_case()
    token = CancellationToken()

    class CancelOnCompaction:
        def __init__(self) -> None:
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            if request.metadata.get("purpose") == "context_compaction":
                token.cancel()
                return ModelResponse.from_final("summary", finish_reason="stop")
            if request.tools and request.step == 1:
                return ModelResponse.from_assistant(
                    AssistantMessage(tool_calls=[_echo_call("new-call", "new")])
                )
            return ModelResponse.from_final("execution", finish_reason="stop")

    model = CancelOnCompaction()
    trace = AgentTraceCollector()

    with pytest.raises(AgentCancelledError):
        _run(
            AgentRuntime(model, registry, limits=limits),
            history,
            request_id,
            cancellation_token=token,
            trace_collector=trace,
        )

    assert len(model.requests) == 3
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"][-1]["status"] == "cancelled"
    assert [item["step"] for item in trace.snapshot()["steps"]] == [1, 2]


def test_primary_compaction_and_model_share_one_deadline() -> None:
    history, request_id, limits = _answer_capacity_case()
    model = ScriptedModelClient([ModelResponse.from_final("execution", finish_reason="stop")])
    runtime = AgentRuntime(model, ToolRegistry(), limits=limits)
    captured_deadlines: list[object] = []

    async def expire_compaction_deadline(**kwargs: object) -> bool:
        deadline = kwargs["deadline"]
        captured_deadlines.append(deadline)
        deadline.expires_at = deadline.started - 1  # type: ignore[attr-defined]
        return False

    runtime._compact_session_history = expire_compaction_deadline  # type: ignore[method-assign]
    trace = AgentTraceCollector()

    result = _run(runtime, history, request_id, trace_collector=trace)

    assert "available context budget" in result.content
    assert len(captured_deadlines) == 1
    assert len(model.requests) == 1
    assert trace.snapshot()["answer_attempts"][0]["error_code"] == "deadline_exceeded"
    assert trace.snapshot().get("compaction_commits", []) == []
