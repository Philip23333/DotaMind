from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    CompactionFailedError,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    build_history_compaction_request,
    build_turn_prefix_compaction_request,
    prepare_compaction,
)
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


def _request_bytes(request: ModelRequest) -> int:
    return len(
        json.dumps(
            request.model_dump(mode="json"),
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
        FinalMessage(content="first completed answer"),
        UserMessage(content="second historical question"),
        second_assistant,
        second_result,
        FinalMessage(content="second completed answer"),
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
    return sum(
        (_message_bytes(message) + 1) // 2
        for message in (
            UserMessage(content="second historical question"),
            *second_group[:2],
            FinalMessage(content="second completed answer"),
            current,
        )
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
        limits=limits or AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
        task_state_coordinator=task_state_coordinator,
        event_sink=event_sink,
    )


def _compact(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: UUID,
    *,
    recent_history_tokens: int,
    trace: AgentTraceCollector | None = None,
    token: CancellationToken | None = None,
    deadline: _Deadline | None = None,
    max_input_bytes: int = 100_000,
) -> bool:
    async def run() -> bool:
        try:
            return await asyncio.wait_for(
                runtime._compact_session_history(
                    execution_history=history,
                    request_id=request_id,
                    token=token or CancellationToken(),
                    deadline=deadline or _Deadline(2),
                    step=4,
                    recent_history_tokens=recent_history_tokens,
                    max_input_bytes=max_input_bytes,
                    trace_collector=trace,
                ),
                timeout=2,
            )
        except CompactionFailedError as exc:
            raise exc.cause from exc

    return asyncio.run(run())


def _history_with_split_turn(
    *, query: str = "current long request", early_progress: str = "early progress"
) -> tuple[SessionExecutionHistory, UUID, UserMessage, tuple, int]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    current = UserMessage(content=query)
    history.begin_request(
        request_id,
        query,
        initial_messages=[
            UserMessage(content="older request"),
            FinalMessage(content="older answer"),
        ],
    )
    group = _artifact_group("split")
    messages = [
        UserMessage(content="older request"),
        FinalMessage(content="older answer"),
        current,
        AssistantMessage(content=early_progress),
        group[0],
        group[1],
        AssistantMessage(content="recent progress"),
        FinalMessage(content="recent final"),
    ]
    history.set_effective(messages)
    recent_tokens = (
        (_message_bytes(group[0]) + _message_bytes(group[1]) + 1) // 2
        + (_message_bytes(messages[-2]) + 1) // 2
        + (_message_bytes(messages[-1]) + 1) // 2
    )
    return history, request_id, current, group, recent_tokens


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
        recent_history_tokens=_recent_budget_for_second_group(second_group, current),
        trace=trace,
    )

    assert result is True
    assert len(model.requests) == 1
    assert model.requests[0].max_output_tokens == 13_107
    data = _request_data(model.requests[0])
    assert "1 full body" in json.dumps(data, ensure_ascii=False)
    assert "2 full body" not in json.dumps(data, ensure_ascii=False)
    assert all(message.get("content") != "current question" for message in data["history"])
    assert history.summary == "summary one"
    assert history.effective_messages() == [
        UserMessage(content="second historical question"),
        second_group[0],
        second_group[1],
        FinalMessage(content="second completed answer"),
        current,
    ]
    assert history.revision == 2
    assert history.compaction_records[0].cut_index == 4
    assert history.compaction_records[0].current_user_index_before == 8
    assert history.records == before_records
    assert history.artifact_locators == before_locators
    assert trace.snapshot()["compaction_calls"][0]["status"] == "generated"


def test_split_turn_summaries_commit_once_after_both_requests_succeed() -> None:
    history, request_id, current, _, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "updated history",
                finish_reason="stop",
                usage={"completion_tokens": 3},
            ),
            ModelResponse.from_final(
                "turn progress",
                finish_reason="stop",
                usage={"completion_tokens": 4},
            ),
        ]
    )
    trace = AgentTraceCollector()
    before = history.context_snapshot()

    assert _compact(
        _runtime(model), history, request_id, recent_history_tokens=recent_tokens, trace=trace
    )

    assert [request.metadata["compaction_kind"] for request in model.requests] == [
        "history",
        "turn_prefix",
    ]
    assert [request.max_output_tokens for request in model.requests] == [13_107, 8_192]
    assert [call["kind"] for call in trace.snapshot()["compaction_calls"]] == [
        "history",
        "turn_prefix",
    ]
    assert len(history.compaction_records) == 1
    assert history.revision == before.revision + 1
    assert history.summary == (
        "updated history\n\n---\n\n**Turn Context (split turn):**\n\nturn progress"
    )
    assert history.effective_messages()[0] == current
    assert sum(message == current for message in history.effective_messages()) == 1


def test_second_summary_failure_discards_first_candidate_and_keeps_session_state() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("candidate history", finish_reason="stop"),
            ModelResponse.from_final(
                "truncated turn",
                finish_reason="length",
                usage={"completion_tokens": 9},
            ),
        ]
    )
    trace = AgentTraceCollector()
    before = history.context_snapshot()
    before_records = history.records

    with pytest.raises(CompactionSummaryError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_tokens=recent_tokens,
            trace=trace,
        )

    after = history.context_snapshot()
    assert error.value.code == "summary_output_truncated"
    assert [request.metadata["compaction_kind"] for request in model.requests] == [
        "history",
        "turn_prefix",
    ]
    assert [call["status"] for call in trace.snapshot()["compaction_calls"]] == [
        "generated",
        "failed",
    ]
    assert trace.snapshot()["compaction_calls"][1]["usage"] == {"completion_tokens": 9}
    assert after.summary == before.summary
    assert after.messages == before.messages
    assert after.revision == before.revision
    assert history.records == before_records
    assert history.compaction_records == ()


def test_first_summary_failure_skips_turn_prefix_and_keeps_session_state() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "truncated history",
                finish_reason="length",
                usage={"completion_tokens": 8},
            )
        ]
    )
    trace = AgentTraceCollector()
    before = history.context_snapshot()
    before_records = history.records

    with pytest.raises(CompactionSummaryError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_tokens=recent_tokens,
            trace=trace,
        )

    assert error.value.code == "summary_output_truncated"
    assert [request.metadata["compaction_kind"] for request in model.requests] == ["history"]
    assert [call["kind"] for call in trace.snapshot()["compaction_calls"]] == ["history"]
    assert trace.snapshot()["compaction_calls"][0]["status"] == "failed"
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {"completion_tokens": 8}
    assert history.context_snapshot() == before
    assert history.records == before_records
    assert history.compaction_records == ()


def test_second_request_input_limit_is_checked_before_first_model_call() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn(
        query="current question " + "q" * 2_000,
        early_progress="progress " + "p" * 2_000,
    )
    model = ScriptedModelClient([])
    before = history.context_snapshot()
    preparation = prepare_compaction(
        before.messages,
        recent_history_tokens=recent_tokens,
        bytes_per_token=2,
    )
    assert preparation is not None
    history_request = build_history_compaction_request(
        previous_summary=before.summary,
        history_messages=preparation.history_messages,
        max_input_bytes=100_000,
        max_output_tokens=13_107,
    )
    turn_request = build_turn_prefix_compaction_request(
        turn_prefix_messages=preparation.turn_prefix_messages,
        max_input_bytes=100_000,
        max_output_tokens=8_192,
    )
    history_limit = _request_bytes(history_request)
    assert _request_bytes(turn_request) > history_limit

    with pytest.raises(CompactionSummaryError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_tokens=recent_tokens,
            max_input_bytes=history_limit,
        )

    assert error.value.code == "summary_input_too_large"
    assert model.requests == []
    assert history.context_snapshot() == before
    assert history.compaction_records == ()


def test_cancellation_after_history_summary_prevents_turn_prefix_call_and_commit() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn()
    token = CancellationToken()

    class CancelAfterFirstResponse:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            token.cancel()
            return ModelResponse.from_final(
                "candidate history",
                finish_reason="stop",
                usage={"completion_tokens": 5},
            )

    model = CancelAfterFirstResponse()
    trace = AgentTraceCollector()
    before = history.context_snapshot()

    with pytest.raises(AgentCancelledError):
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_tokens=recent_tokens,
            token=token,
            trace=trace,
        )

    assert len(model.requests) == 1
    assert model.requests[0].metadata["compaction_kind"] == "history"
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {"completion_tokens": 5}
    assert history.context_snapshot() == before
    assert history.compaction_records == ()


def test_stale_revision_after_both_summary_calls_rejects_atomic_commit() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn()

    class MutateAfterSecondResponse:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            if len(self.requests) == 2:
                extra = FinalMessage(content="concurrent completion")
                history.record(request_id, extra, kind="execution_final")
                history.set_effective([*history.effective_messages(), extra])
            return ModelResponse.from_final("candidate", finish_reason="stop")

    model = MutateAfterSecondResponse()
    trace = AgentTraceCollector()
    before = history.context_snapshot()

    with pytest.raises(SessionCompactionError) as error:
        _compact(
            _runtime(model),
            history,
            request_id,
            recent_history_tokens=recent_tokens,
            trace=trace,
        )

    assert error.value.code == "stale_context_revision"
    assert len(model.requests) == 2
    assert [call["status"] for call in trace.snapshot()["compaction_calls"]] == [
        "generated",
        "generated",
    ]
    assert history.summary == before.summary
    assert history.revision == before.revision + 1
    assert history.compaction_records == ()


def test_configured_model_output_limit_caps_both_summary_requests() -> None:
    history, request_id, _, _, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("history summary", finish_reason="stop"),
            ModelResponse.from_final("turn summary", finish_reason="stop"),
        ]
    )
    runtime = _runtime(
        model,
        limits=AgentLimits(
            application_max_output_tokens=4096,
            deadline_seconds=2,
            compaction_model_max_output_tokens=4096,
        ),
    )

    assert _compact(
        runtime,
        history,
        request_id,
        recent_history_tokens=recent_tokens,
    )
    assert [request.max_output_tokens for request in model.requests] == [4096, 4096]


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
        recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("history summary", finish_reason="stop"),
            ModelResponse.from_final("turn summary", finish_reason="stop"),
        ]
    )

    result = _compact(
        _runtime(model),
        history,
        request_id,
        recent_history_tokens=1,
    )

    assert result is True
    data = _request_data(model.requests[0])
    assert len(model.requests) == 2
    assert model.requests[0].metadata["compaction_kind"] == "history"
    assert model.requests[1].metadata["compaction_kind"] == "turn_prefix"
    assert data["history"] == [{"content": "old question", "role": "user"}]
    prefix = _request_data(model.requests[1])
    assert [item["content"] for item in prefix["turn_prefix"]].count("current question") == 1
    assert history.effective_messages() == [current, second_group[0], second_group[1]]
    assert history.summary == (
        "history summary\n\n---\n\n**Turn Context (split turn):**\n\nturn summary"
    )


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
        recent_history_tokens=recent_budget,
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
            recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
            recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
            recent_history_tokens=1,
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
            recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
            recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
                recent_history_tokens=_recent_budget_for_second_group(second_group, current),
                max_input_bytes=100_000,
                trace_collector=trace,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        appended = FinalMessage(content="during generation")
        history.record(request_id, appended, kind="execution_final")
        history.set_effective([*history.effective_messages(), appended])
        release.set()
        with pytest.raises(CompactionFailedError) as error:
            await asyncio.wait_for(task, timeout=1)
        assert error.value.reason_code == "stale_context_revision"
        assert error.value.summary_kind is None
        assert error.value.attempt_count == 0
        return model, trace

    model, trace = asyncio.run(exercise())

    assert len(model.requests) == 1
    assert history.summary is None
    assert history.effective_messages()[-1] == FinalMessage(content="during generation")
    assert history.compaction_records == ()
    assert trace.snapshot()["compaction_calls"] == [
        {
            "kind": "history",
            "attempt": 1,
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
            recent_history_tokens=first_recent,
        )
        is True
    )

    third_assistant, third_result, third_call = _artifact_group("3")
    history.remember_artifact_locators(third_call, third_result)
    history.set_effective(
        [
            *history.effective_messages(),
            FinalMessage(content="current completed answer"),
            third_assistant,
            third_result,
        ]
    )
    second_model = ScriptedModelClient(
        [ModelResponse.from_final("summary two", finish_reason="stop")]
    )
    second_recent = sum(
        (_message_bytes(message) + 1) // 2 for message in (third_assistant, third_result)
    )

    assert (
        _compact(
            _runtime(second_model),
            history,
            request_id,
            recent_history_tokens=second_recent,
        )
        is True
    )

    data = _request_data(second_model.requests[0])
    assert data["previous_summary"] == "summary one"
    encoded = json.dumps(data, ensure_ascii=False)
    assert "1 full body" not in encoded
    assert "2 full body" in encoded
    assert "3 full body" not in encoded
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
            recent_history_tokens=_recent_budget_for_second_group(second_group, current),
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
    coordinator.record_tool_result(source_group[2], source_group[1], task_key="first")
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
            recent_history_tokens=sum(
                (_message_bytes(message) + 1) // 2 for message in (*second_group[:2], current)
            ),
        )
        is True
    )
    request_start, effective_messages = runtime._rebuild_after_compaction(
        execution_history=history,
        request_id=request_id,
        request_start=0,
        request_start_before=0,
        step=4,
        trigger="watermark",
        trace_collector=None,
    )

    assert request_start == 0
    assert effective_messages == history.effective_messages()
    expected_owners = (
        [
            {
                "tool_call_id": source_group[2].id,
                "tool_name": source_group[2].name,
                "task_key": "first",
            }
        ]
        if retained
        else []
    )
    assert coordinator.source_owners_snapshot() == expected_owners
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
            recent_history_tokens=1,
        )

    assert model.requests == []
