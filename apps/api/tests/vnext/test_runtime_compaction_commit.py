from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.evidence_summary_lifecycle import CompactionSummaryError
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import (
    SessionCompactionError,
    SessionExecutionHistory,
)
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _LookupInput(BaseModel):
    query: str


class _LookupOutput(BaseModel):
    value: str


def _message_bytes(message: object) -> int:
    return len(
        json.dumps(
            message.model_dump(mode="json"),  # type: ignore[union-attr]
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _artifact_group(prefix: str) -> tuple[AssistantMessage, ToolResultMessage, ToolCall]:
    call = ToolCall(
        id=f"{prefix}-call",
        name="lookup",
        arguments={"query": prefix},
    )
    result = ToolResultMessage(
        tool_call_id=call.id,
        content={
            "externalized": True,
            "artifact_ref": "artifact:tool:" + (prefix[0] * 32),
            "value": {"body": f"{prefix} full body"},
        },
    )
    return AssistantMessage(tool_calls=[call]), result, call


def _inline_group(prefix: str) -> tuple[AssistantMessage, ToolResultMessage, ToolCall]:
    call = ToolCall(
        id=f"{prefix}-inline-call",
        name="lookup",
        arguments={"query": prefix},
    )
    result = ToolResultMessage(
        tool_call_id=call.id,
        content={"records": [{"label": f"synthetic {prefix}"}]},
    )
    return AssistantMessage(tool_calls=[call]), result, call


def _history_with_two_groups() -> tuple[
    SessionExecutionHistory,
    UUID,
    list[UserMessage | AssistantMessage | ToolResultMessage],
    tuple[AssistantMessage, ToolResultMessage, ToolCall],
    tuple[AssistantMessage, ToolResultMessage, ToolCall],
]:
    first_assistant, first_result, first_call = _artifact_group("1")
    second_assistant, second_result, second_call = _artifact_group("2")
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = [
        UserMessage(content="old question"),
        first_assistant,
        first_result,
        second_assistant,
        second_result,
        UserMessage(content="current question"),
    ]
    history.begin_request(
        request_id,
        "current question",
        initial_messages=messages,
    )
    history.remember_artifact_locators(first_call, first_result)
    history.remember_artifact_locators(second_call, second_result)
    return (
        history,
        request_id,
        messages,
        (first_assistant, first_result, first_call),
        (
            second_assistant,
            second_result,
            second_call,
        ),
    )


def _recent_budget_for_second_group(
    second_group: tuple[AssistantMessage, ToolResultMessage, ToolCall],
    current: UserMessage,
) -> int:
    return (
        _message_bytes(second_group[0]) + _message_bytes(second_group[1]) + _message_bytes(current)
    )


def _runtime(
    model: object,
    *,
    registry: ToolRegistry | None = None,
    task_state_coordinator: TaskStateCoordinator | None = None,
    event_sink=None,
    limits: AgentLimits | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        registry or ToolRegistry(),
        limits=limits or AgentLimits(deadline_seconds=2),
        task_state_coordinator=task_state_coordinator,
        event_sink=event_sink,
    )


def _compact(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: UUID,
    *,
    recent_history_bytes: int,
    trace: AgentTraceCollector | None = None,
    token: CancellationToken | None = None,
    deadline: _Deadline | None = None,
    max_input_bytes: int = 100_000,
) -> bool:
    return asyncio.run(
        runtime._compact_session_history(
            execution_history=history,
            request_id=request_id,
            token=token or CancellationToken(),
            deadline=deadline or _Deadline(2),
            step=4,
            recent_history_bytes=recent_history_bytes,
            max_input_bytes=max_input_bytes,
            trace_collector=trace,
        )
    )


def _request_data(request: ModelRequest) -> dict[str, object]:
    assert len(request.messages) == 2
    assert isinstance(request.messages[1], UserMessage)
    return json.loads(request.messages[1].content)


def test_first_compaction_selects_generates_and_commits_one_range() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    before_records = history.records
    before_locators = history.artifact_locators
    current = messages[-1]
    assert isinstance(current, UserMessage)
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "summary one",
                finish_reason="stop",
                usage={"completion_tokens": 5},
            )
        ]
    )
    trace = AgentTraceCollector()
    runtime = _runtime(model)

    result = _compact(
        runtime,
        history,
        request_id,
        recent_history_bytes=_recent_budget_for_second_group(second_group, current),
        trace=trace,
    )

    assert result is True
    assert len(model.requests) == 1
    assert model.requests[0].max_output_tokens == 13_107
    data = _request_data(model.requests[0])
    assert data["current_user_message"] == "current question"
    assert "1 full body" in json.dumps(data, ensure_ascii=False)
    assert "2 full body" not in json.dumps(data, ensure_ascii=False)
    assert all(message.get("content") != "current question" for message in data["history"])
    assert history.summary == "summary one"
    assert history.effective_messages() == [second_group[0], second_group[1], current]
    assert history.revision == 2
    assert history.compaction_records[0].cut_index == 3
    assert history.compaction_records[0].current_user_index_before == 5
    assert history.records == before_records
    assert history.artifact_locators == before_locators
    assert trace.snapshot()["compaction_calls"][0]["status"] == "generated"


def test_configured_model_output_limit_caps_history_summary_request() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    model = ScriptedModelClient([ModelResponse.from_final("summary", finish_reason="stop")])
    runtime = _runtime(
        model,
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_model_max_output_tokens=4096,
        ),
    )

    assert _compact(
        runtime,
        history,
        request_id,
        recent_history_bytes=_recent_budget_for_second_group(second_group, current),
    )
    assert model.requests[0].max_output_tokens == 4096


def test_summary_larger_than_old_8k_byte_limit_is_committed() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    summary = "合成摘要" + "x" * 8190
    assert len(summary.encode("utf-8")) > 8 * 1024
    model = ScriptedModelClient([ModelResponse.from_final(summary, finish_reason="stop")])

    assert _compact(
        _runtime(model),
        history,
        request_id,
        recent_history_bytes=_recent_budget_for_second_group(second_group, current),
    )

    assert history.summary == summary
    assert len(model.requests) == 1
    assert model.requests[0].max_output_tokens == 13_107
    assert len(history.compaction_records) == 1


def test_current_user_in_compaction_prefix_is_not_duplicated_after_commit() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    current = UserMessage(content="current question")
    history.begin_request(
        request_id,
        current.content,
        initial_messages=[UserMessage(content="old question"), current],
    )
    second_group = _artifact_group("2")
    history.set_effective(
        [UserMessage(content="old question"), current, second_group[0], second_group[1]]
    )
    model = ScriptedModelClient([ModelResponse.from_final("summary", finish_reason="stop")])

    result = _compact(
        _runtime(model),
        history,
        request_id,
        recent_history_bytes=1,
    )

    assert result is True
    data = _request_data(model.requests[0])
    assert data["current_user_message"] == "current question"
    assert [item["content"] for item in data["history"]].count("current question") == 0
    assert history.effective_messages() == [current, second_group[0], second_group[1]]


@pytest.mark.parametrize("case", ["only_current", "recent_window", "current_prefix"])
def test_no_compaction_range_returns_false_without_model_or_state_change(case: str) -> None:
    if case == "only_current":
        history = SessionExecutionHistory()
        request_id = uuid4()
        history.begin_request(
            request_id,
            "current question",
            initial_messages=[UserMessage(content="current question")],
        )
        recent_budget = 1
    else:
        history, request_id, messages, _, second_group = _history_with_two_groups()
        current = messages[-1]
        assert isinstance(current, UserMessage)
        if case == "recent_window":
            recent_budget = 1_000_000
        else:
            history = SessionExecutionHistory()
            request_id = uuid4()
            current_group = _artifact_group("3")
            history.begin_request(
                request_id,
                "current question",
                initial_messages=[UserMessage(content="current question")],
            )
            history.set_effective(
                [UserMessage(content="current question"), current_group[0], current_group[1]]
            )
            recent_budget = _message_bytes(current_group[0]) + _message_bytes(current_group[1])
    before_effective = history.effective_messages()
    before_revision = history.revision
    before_records = history.records
    model = ScriptedModelClient([])

    result = _compact(
        _runtime(model),
        history,
        request_id,
        recent_history_bytes=recent_budget,
    )

    assert result is False
    assert model.requests == []
    assert history.effective_messages() == before_effective
    assert history.revision == before_revision
    assert history.records == before_records
    assert history.compaction_records == ()


def test_input_budget_failure_does_not_call_model_or_commit() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    before_effective = history.effective_messages()
    before_revision = history.revision
    model = ScriptedModelClient([])

    with pytest.raises(CompactionSummaryError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
            max_input_bytes=1,
        )

    assert error.value.code == "summary_input_too_large"
    assert model.requests == []
    assert history.effective_messages() == before_effective
    assert history.revision == before_revision
    assert history.compaction_records == ()


@pytest.mark.parametrize(
    ("response", "error_type", "error_code"),
    [
        (ModelProviderError("provider failed"), ModelProviderError, "model_provider_error"),
        (
            ModelResponse.from_final("summary", finish_reason="length"),
            CompactionSummaryError,
            "summary_output_truncated",
        ),
        (
            ModelResponse.from_final(" ", finish_reason="stop"),
            CompactionSummaryError,
            "empty_summary",
        ),
    ],
)
def test_generation_failure_propagates_and_does_not_commit(
    response: ModelResponse | Exception,
    error_type: type[Exception],
    error_code: str,
) -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    model = ScriptedModelClient([response])
    trace = AgentTraceCollector()

    with pytest.raises(error_type) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
            trace=trace,
        )

    assert getattr(error.value, "code", None) == error_code
    assert len(model.requests) == 1
    assert history.summary is None
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"][0]["status"] == "failed"


def test_truncated_candidate_preserves_previous_summary_boundary_and_revision() -> None:
    history, request_id, _, _, _ = _history_with_two_groups()
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="previous accepted summary",
        cut_index=3,
    )
    before = history.context_snapshot()
    before_records = history.compaction_records
    model = ScriptedModelClient([ModelResponse.from_final("partial", finish_reason="length")])

    with pytest.raises(CompactionSummaryError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_bytes=1,
        )

    assert error.value.code == "summary_output_truncated"
    after = history.context_snapshot()
    assert after.summary == before.summary == "previous accepted summary"
    assert after.revision == before.revision
    assert after.messages == before.messages
    assert history.compaction_records == before_records


def test_compaction_cancellation_before_model_call_keeps_state() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    token = CancellationToken()
    token.cancel()
    model = ScriptedModelClient([])
    before = history.effective_messages()

    with pytest.raises(AgentCancelledError):
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
            token=token,
        )

    assert model.requests == []
    assert history.effective_messages() == before
    assert history.compaction_records == ()


def test_compaction_deadline_before_model_call_keeps_state() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    model = ScriptedModelClient([])

    with pytest.raises(AgentDeadlineExceeded):
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
            deadline=_Deadline(0),
        )

    assert model.requests == []
    assert history.compaction_records == ()


def test_compaction_version_change_during_generation_is_not_overwritten() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    started = asyncio.Event()
    release = asyncio.Event()

    class WaitingModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            started.set()
            await release.wait()
            return ModelResponse.from_final(
                "new summary",
                finish_reason="stop",
                usage={"completion_tokens": 11},
            )

    async def exercise() -> tuple[WaitingModel, AgentTraceCollector]:
        model = WaitingModel()
        trace = AgentTraceCollector()
        task = asyncio.create_task(
            _runtime(model)._compact_session_history(
                execution_history=history,
                request_id=request_id,
                token=CancellationToken(),
                deadline=_Deadline(2),
                step=4,
                recent_history_bytes=_recent_budget_for_second_group(second_group, current),
                max_input_bytes=100_000,
                trace_collector=trace,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        appended = FinalMessage(content="during generation")
        history.record(request_id, appended, kind="execution_final")
        history.set_effective([*history.effective_messages(), appended])
        release.set()
        with pytest.raises(SessionCompactionError) as error:
            await asyncio.wait_for(task, timeout=1)
        assert error.value.code == "stale_context_revision"
        return model, trace

    model, trace = asyncio.run(exercise())

    assert len(model.requests) == 1
    assert history.summary is None
    assert history.effective_messages()[-1] == FinalMessage(content="during generation")
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"] == [
        {
            "step": 4,
            "status": "generated",
            "duration_seconds": trace.snapshot()["compaction_calls"][0]["duration_seconds"],
            "usage": {"completion_tokens": 11},
            "error_code": None,
        }
    ]


def test_two_compactions_use_previous_summary_and_only_current_retained_history() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    first_model = ScriptedModelClient(
        [ModelResponse.from_final("summary one", finish_reason="stop")]
    )
    first_recent = _recent_budget_for_second_group(second_group, current)

    assert (
        _compact(
            _runtime(first_model),
            history,
            request_id,
            recent_history_bytes=first_recent,
        )
        is True
    )

    third_assistant, third_result, third_call = _artifact_group("3")
    history.remember_artifact_locators(third_call, third_result)
    history.set_effective([*history.effective_messages(), third_assistant, third_result])
    second_model = ScriptedModelClient(
        [ModelResponse.from_final("summary two", finish_reason="stop")]
    )
    second_recent = _message_bytes(third_assistant) + _message_bytes(third_result)

    assert (
        _compact(
            _runtime(second_model),
            history,
            request_id,
            recent_history_bytes=second_recent,
        )
        is True
    )

    data = _request_data(second_model.requests[0])
    assert data["previous_summary"] == "summary one"
    encoded = json.dumps(data, ensure_ascii=False)
    assert "1 full body" not in encoded
    assert "2 full body" in encoded
    assert "3 full body" not in encoded
    assert data["current_user_message"] == "current question"
    assert [item["content"] for item in data["history"]].count("current question") == 0
    assert history.summary == "summary two"
    assert history.effective_messages() == [
        current,
        third_assistant,
        third_result,
    ]
    records = history.compaction_records
    assert len(records) == 2
    assert records[1].previous_compaction_id == records[0].compaction_id
    assert len(first_model.requests) == 1
    assert len(second_model.requests) == 1


def test_compaction_does_not_reset_task_state_execute_tools_or_publish_events() -> None:
    history, request_id, messages, _, second_group = _history_with_two_groups()
    current = messages[-1]
    assert isinstance(current, UserMessage)
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "first", "objective": "First"},
            {"key": "second", "objective": "Second"},
        ]
    )
    before_plan = coordinator.plan_snapshot()
    called = False

    async def forbidden_tool(_args: _LookupInput) -> _LookupOutput:
        nonlocal called
        called = True
        raise AssertionError("compaction must not execute business tools")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="A business tool that must remain untouched.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=forbidden_tool,
        )
    )
    events: list[object] = []
    model = ScriptedModelClient([ModelResponse.from_final("summary", finish_reason="stop")])

    assert (
        _compact(
            _runtime(
                model,
                registry=registry,
                task_state_coordinator=coordinator,
                event_sink=events.append,
            ),
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
        )
        is True
    )

    assert called is False
    assert coordinator.plan_snapshot() == before_plan
    assert events == []


@pytest.mark.parametrize(("source_position", "retained"), [("first", False), ("second", True)])
def test_compaction_refresh_keeps_only_inline_sources_in_effective_history(
    source_position: str,
    retained: bool,
) -> None:
    source_group = _inline_group("source")
    other_first = _artifact_group("1")
    other_second = _artifact_group("2")
    first_group = source_group if source_position == "first" else other_first
    second_group = source_group if source_position == "second" else other_second
    current = UserMessage(content="current question")
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = [
        UserMessage(content="old question"),
        first_group[0],
        first_group[1],
        second_group[0],
        second_group[1],
        current,
    ]
    history.begin_request(request_id, current.content, initial_messages=messages)

    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "first", "objective": "First"},
            {"key": "second", "objective": "Second"},
        ]
    )
    coordinator.record_inline_tool_result(source_group[2], source_group[1], task_key="first")
    coordinator.refresh(messages)
    runtime = _runtime(
        ScriptedModelClient([ModelResponse.from_final("summary", finish_reason="stop")]),
        registry=ToolRegistry(),
        task_state_coordinator=coordinator,
    )

    assert (
        _compact(
            runtime,
            history,
            request_id,
            recent_history_bytes=_recent_budget_for_second_group(second_group, current),
        )
        is True
    )
    request_start, effective_messages, _ = runtime._rebuild_after_compaction(
        execution_history=history,
        request_id=request_id,
        request_start=0,
        request_start_before=0,
        materialized_bytes_before=0,
        step=4,
        trigger="watermark",
        trace_collector=None,
    )

    assert request_start == 0
    assert effective_messages == history.effective_messages()
    assert coordinator.active_evidence_lease() is None
    candidate_ids = [
        item["tool_call_id"] for item in coordinator.context_payload()["checkpoint_candidates"]
    ]
    assert candidate_ids == ([source_group[2].id] if retained else [])


def test_compaction_rejects_invalid_session_request_without_model_call() -> None:
    history = SessionExecutionHistory()
    model = ScriptedModelClient([])

    with pytest.raises(ModelProtocolError):
        _compact(
            _runtime(model),
            history,
            uuid4(),
            recent_history_bytes=1,
        )

    assert model.requests == []
