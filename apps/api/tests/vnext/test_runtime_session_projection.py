from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.context_accounting import build_context_accounting
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, _project_session_context
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedTranscriptModelClient


class _LocatorOutput(BaseModel):
    externalized: bool
    artifact_ref: str
    value: dict[str, str]


class _LookupInput(BaseModel):
    query: str = ""


def _history(*, summary: str | None = None, locator: bool = False) -> tuple[
    SessionExecutionHistory, UUID
]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="old question"),
            FinalMessage(content="old answer"),
            UserMessage(content="current question"),
        ],
    )
    if summary is not None:
        history.commit_compaction(
            request_id=request_id,
            base_revision=history.revision,
            summary=summary,
            cut_index=2,
        )
    if locator:
        ref = "artifact:tool:" + "a" * 32
        history.remember_artifact_locators(
            ToolCall(id="lookup-call", name="lookup", arguments={"query": "Dota"}),
            ToolResultMessage(
                tool_call_id="lookup-call",
                content={
                    "externalized": True,
                    "artifact_ref": ref,
                    "value": {"ignored": "full artifact body"},
                },
            ),
        )
    return history, request_id


def _run(
    model: object,
    *,
    history: SessionExecutionHistory | None = None,
    request_id: UUID | None = None,
    registry: ToolRegistry | None = None,
    trace_collector: AgentTraceCollector | None = None,
    messages: list[Message] | None = None,
    system_instruction: str | None = None,
) -> FinalMessage:
    runtime = AgentRuntime(
        model,  # type: ignore[arg-type]
        registry or ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        system_instruction=system_instruction,
    )
    run_messages = messages
    if run_messages is None:
        run_messages = history.effective_messages() if history is not None else [
            UserMessage(content="current question")
        ]
    return asyncio.run(
        runtime.run(
            run_messages,
            execution_history=history,
            request_id=request_id,
            trace_collector=trace_collector,
        )
    )


def _payload(request: ModelRequest) -> dict[str, object] | None:
    marker = "Session context data:\n"
    for message in request.messages:
        if not isinstance(message, SystemMessage) or marker not in message.content:
            continue
        encoded = message.content.split(marker, 1)[1]
        value, _ = json.JSONDecoder().raw_decode(encoded)
        return value
    return None


def _context_system_messages(request: ModelRequest) -> list[SystemMessage]:
    return [
        message
        for message in request.messages
        if isinstance(message, SystemMessage) and "Session context data:" in message.content
    ]


def _canonical_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _locator(ref: str = "artifact:tool:" + "b" * 32) -> tuple[ToolCall, ToolResultMessage]:
    call = ToolCall(id="manual-call", name="lookup", arguments={"query": "teams"})
    result = ToolResultMessage(
        tool_call_id=call.id,
        content={
            "externalized": True,
            "artifact_ref": ref,
            "value": {"complete": "artifact body"},
        },
    )
    return call, result


def test_no_session_object_keeps_the_existing_model_request_shape() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    assert _run(model).content == "answer"
    assert len(model.requests) == 2
    assert all(_payload(request) is None for request in model.requests)
    assert model.requests[0].messages[-1] == UserMessage(content="current question")


def test_empty_session_does_not_add_a_placeholder_or_duplicate_current_question() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[UserMessage(content="current question")],
    )
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(model, history=history, request_id=request_id)

    assert all(_payload(request) is None for request in model.requests)
    for request in model.requests:
        assert sum(
            message == UserMessage(content="current question")
            for message in request.messages
        ) == 1


@pytest.mark.parametrize(
    ("summary", "has_locator", "expected_summary", "expected_locator_count"),
    [
        ("compressed summary", False, "compressed summary", 0),
        (None, True, None, 1),
        ("compressed summary", True, "compressed summary", 1),
    ],
)
def test_session_projection_has_exact_summary_and_fifo_locators(
    summary: str | None,
    has_locator: bool,
    expected_summary: str | None,
    expected_locator_count: int,
) -> None:
    history, request_id = _history(summary=summary, locator=has_locator)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(model, history=history, request_id=request_id)

    for request in model.requests:
        assert len(_context_system_messages(request)) == 1
        payload = _payload(request)
        assert payload == {
            "summary": expected_summary,
            "artifact_locators": (
                [
                    {
                        "ref": "artifact:tool:" + "a" * 32,
                        "source_tool": "lookup",
                        "query_hint": '{"query":"Dota"}',
                    }
                ]
                if expected_locator_count
                else []
            ),
        }
        assert sum(
            message == UserMessage(content="current question")
            for message in request.messages
        ) == 1
        assert all(
            not (
                isinstance(message, UserMessage)
                and message.content == "old question"
            )
            for message in request.messages
        ) if summary is not None else True


def test_locator_projection_preserves_fifo_order_without_artifact_body() -> None:
    history, request_id = _history()
    first_call, first_result = _locator("artifact:tool:" + "1" * 32)
    second_call, second_result = _locator("artifact:tool:" + "2" * 32)
    history.remember_artifact_locators(first_call, first_result)
    history.remember_artifact_locators(second_call, second_result)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(model, history=history, request_id=request_id)

    payload = _payload(model.requests[0])
    assert payload is not None
    assert [item["ref"] for item in payload["artifact_locators"]] == [
        "artifact:tool:" + "1" * 32,
        "artifact:tool:" + "2" * 32,
    ]
    assert "complete artifact body" not in json.dumps(payload, ensure_ascii=False)


def test_new_tool_locator_is_projected_on_the_next_request() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[UserMessage(content="current question")],
    )
    ref = "artifact:tool:" + "c" * 32

    async def lookup(_args: BaseModel) -> _LocatorOutput:
        return _LocatorOutput(
            externalized=True,
            artifact_ref=ref,
            value={"full": "body"},
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return a locatable result.",
            input_model=_LookupInput,
            output_model=_LocatorOutput,
            handler=lookup,
            externalize_result=False,
        )
    )
    call = ToolCall(id="lookup-call", name="lookup", arguments={})

    def first(request: ModelRequest) -> ModelResponse:
        assert _payload(request) is None
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[call]))

    def follow_up(request: ModelRequest) -> ModelResponse:
        payload = _payload(request)
        assert payload is not None
        assert payload["artifact_locators"][0]["ref"] == ref
        return ModelResponse.from_final("execution")

    def answer(request: ModelRequest) -> ModelResponse:
        assert _payload(request)["artifact_locators"][0]["ref"] == ref  # type: ignore[index]
        return ModelResponse.from_final("answer")

    model = ScriptedTranscriptModelClient([first, follow_up, answer])
    _run(
        model,
        history=history,
        request_id=request_id,
        registry=registry,
    )

    assert len(model.requests) == 3
    assert _payload(model.requests[0]) is None
    assert _payload(model.requests[1])["artifact_locators"][0]["ref"] == ref  # type: ignore[index]


def test_primary_answer_request_projects_session_context_and_disables_tools() -> None:
    history, request_id = _history(summary="answer background", locator=True)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(model, history=history, request_id=request_id)

    assert model.requests[1].tools == []
    assert _payload(model.requests[1]) == _payload(model.requests[0])
    assert any(
        isinstance(message, UserMessage) and message.content == "current question"
        for message in model.requests[1].messages
    )


def test_degraded_answer_request_projects_session_context() -> None:
    history, request_id = _history(summary="degraded background", locator=True)
    invalid_answer = ModelResponse.from_assistant(
        AssistantMessage(tool_calls=[ToolCall(id="answer-call", name="lookup", arguments={})])
    )
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), invalid_answer, ModelResponse.from_final("answer")]
    )

    _run(model, history=history, request_id=request_id)

    assert model.requests[1].tools == []
    assert model.requests[2].tools == []
    assert _payload(model.requests[2]) == _payload(model.requests[0])


def test_session_projection_does_not_pollute_history_or_mutate_input_messages() -> None:
    messages = [
        SystemMessage(content="caller-owned system context"),
        UserMessage(content="current question"),
    ]
    original = [message.model_copy(deep=True) for message in messages]
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(model, messages=messages)

    assert messages == original


def test_session_projection_is_included_in_actual_accounting_without_raw_observations() -> None:
    history, request_id = _history(summary="计量摘要", locator=True)
    projected = _project_session_context(history.effective_messages(), history)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()

    _run(model, history=history, request_id=request_id, trace_collector=trace)

    expected = build_context_accounting(
        model.requests[0],
        stable_messages=projected,
        task_context_messages=projected,
    ).to_dict()
    actual = trace.snapshot()["steps"][0]["context_accounting"]
    assert actual == expected
    assert actual["stable_messages"]["serialized_bytes"] == sum(
        _canonical_size(message.model_dump(mode="json")) for message in projected
    )
    assert actual["effective_request"]["serialized_bytes"] == _canonical_size(
        {
            "messages": [message.model_dump(mode="json") for message in model.requests[0].messages],
            "tools": [],
        }
    )
    assert actual["artifact_observations"] == {
        "active_raw": {"count": 0, "serialized_bytes": 0},
        "receipts": {"count": 0, "serialized_bytes": 0},
    }


def test_projection_helper_deep_copies_existing_system_message() -> None:
    messages = [
        SystemMessage(content="caller-owned system context"),
        UserMessage(content="current question"),
    ]
    history, _ = _history(summary="summary", locator=True)
    projected = _project_session_context(messages, history)

    assert projected != messages
    assert messages[0].content == "caller-owned system context"
    assert projected[0].content.startswith("caller-owned system context")


@pytest.mark.parametrize("system_instruction", [None, "base instruction"])
def test_projection_does_not_persist_background_with_or_without_base_system_instruction(
    system_instruction: str | None,
) -> None:
    history, request_id = _history(summary="stable summary", locator=True)
    before_effective = history.effective_messages()
    before_records = history.records
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )

    _run(
        model,
        history=history,
        request_id=request_id,
        system_instruction=system_instruction,
    )

    assert history.effective_messages() == [*before_effective, FinalMessage(content="answer")]
    assert history.records[: len(before_records)] == before_records
    assert history.summary == "stable summary"
    assert all(
        not (
            isinstance(record.message, SystemMessage)
            and "Session context data:" in record.message.content
        )
        for record in history.records
    )
    assert all(len(_context_system_messages(request)) == 1 for request in model.requests)
