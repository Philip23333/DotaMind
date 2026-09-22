from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _LookupInput(BaseModel):
    query: str


class _LookupOutput(BaseModel):
    externalized: bool
    artifact_ref: str
    value: dict[str, str]


def _call(number: int) -> ToolCall:
    return ToolCall(
        id=f"lookup-{number}",
        name="lookup",
        arguments={"query": f"event-{number}"},
    )


def _lookup_result(number: int) -> _LookupOutput:
    return _LookupOutput(
        externalized=True,
        artifact_ref="artifact:tool:" + (str(number) * 32),
        value={"body": f"event {number} raw body"},
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def lookup(args: _LookupInput) -> _LookupOutput:
        number = int(args.query.split("-")[-1])
        return _lookup_result(number)

    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return one materialized lookup result.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _history() -> tuple[SessionExecutionHistory, object]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="old question"),
            UserMessage(content="current question"),
        ],
    )
    return history, request_id


def _runtime(
    model: object,
    *,
    recent_bytes: int,
    system_instruction: str | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        _registry(),
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_recent_history_bytes=recent_bytes,
            compaction_max_input_bytes=100_000,
            compaction_max_output_tokens=128,
            compaction_max_summary_bytes=10_000,
        ),
        system_instruction=system_instruction,
    )


def _message_bytes(message: object) -> int:
    return len(
        json.dumps(
            message.model_dump(mode="json"),  # type: ignore[union-attr]
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _tool_group_bytes(number: int) -> int:
    assistant = AssistantMessage(tool_calls=[_call(number)])
    result = _lookup_result(number)
    from app.vnext.llm.protocol import ToolResultMessage

    tool_result = ToolResultMessage(
        tool_call_id=f"lookup-{number}",
        content=result.model_dump(mode="json"),
    )
    return _message_bytes(assistant) + _message_bytes(tool_result)


def _session_payload(request: ModelRequest) -> dict[str, object]:
    marker = "Session context data:\n"
    for message in request.messages:
        if isinstance(message, SystemMessage) and marker in message.content:
            payload, _ = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])
            return payload
    raise AssertionError("session projection missing")


def _run(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: object,
    *,
    compact_before_steps: tuple[int, ...],
    trace: AgentTraceCollector,
) -> FinalMessage:
    return asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=compact_before_steps,
            trace_collector=trace,
        )
    )


@pytest.mark.parametrize(
    ("system_instruction", "request_start_before", "request_start_after"),
    [(None, 2, 1), ("base instruction", 3, 2)],
)
def test_compaction_loop_rebuilds_messages_scope_and_budget_before_next_model_call(
    system_instruction: str | None,
    request_start_before: int,
    request_start_after: int,
) -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call(1)])
            ),
            ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call(2)])
            ),
            ModelResponse.from_final("summary one", finish_reason="stop", usage={"n": 1}),
            ModelResponse.from_final("execution final"),
            ModelResponse.from_final("answer final"),
        ]
    )
    trace = AgentTraceCollector()
    runtime = _runtime(
        model,
        recent_bytes=_tool_group_bytes(2),
        system_instruction=system_instruction,
    )

    result = _run(
        runtime,
        history,
        request_id,
        compact_before_steps=(3,),
        trace=trace,
    )

    assert result.content == "answer final"
    assert len(model.requests) == 5
    assert model.requests[2].tools == []
    assert model.requests[3].tools
    assert "event 1 raw body" not in json.dumps(
        [message.model_dump(mode="json") for message in model.requests[3].messages]
    )
    assert "event 2 raw body" in json.dumps(
        [message.model_dump(mode="json") for message in model.requests[3].messages]
    )
    assert _session_payload(model.requests[3])["summary"] == "summary one"
    assert sum(
        message == UserMessage(content="current question")
        for message in model.requests[3].messages
    ) == 1
    assert history.effective_messages() == [
        UserMessage(content="current question"),
        model.requests[1].messages[-1],
    ] or history.effective_messages()[-1].role == "final"
    assert len(trace.snapshot()["compaction_calls"]) == 1
    assert len(trace.snapshot()["compaction_commits"]) == 1
    commit = trace.snapshot()["compaction_commits"][0]
    assert commit["step"] == 3
    assert commit["request_start_before"] == request_start_before
    assert commit["request_start_after"] == request_start_after
    assert commit["materialized_bytes_after"] < commit["materialized_bytes_before"]


def test_compaction_loop_supports_two_explicit_compactions_without_replaying_tools() -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(1)])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(2)])),
            ModelResponse.from_final("summary one", finish_reason="stop", usage={"n": 1}),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(3)])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(4)])),
            ModelResponse.from_final("summary two", finish_reason="stop", usage={"n": 2}),
            ModelResponse.from_final("execution final"),
            ModelResponse.from_final("answer final"),
        ]
    )
    trace = AgentTraceCollector()
    runtime = _runtime(model, recent_bytes=_tool_group_bytes(2))

    _run(
        runtime,
        history,
        request_id,
        compact_before_steps=(3, 5),
        trace=trace,
    )

    assert [call.id for call in [_call(1), _call(2), _call(3), _call(4)]] == [
        "lookup-1",
        "lookup-2",
        "lookup-3",
        "lookup-4",
    ]
    assert [request.tools != [] for request in model.requests] == [
        True,
        True,
        False,
        True,
        True,
        False,
        True,
        False,
    ]
    assert [_session_payload(model.requests[index])["summary"] for index in (3, 6)] == [
        "summary one",
        "summary two",
    ]
    assert len(trace.snapshot()["compaction_calls"]) == 2
    assert len(trace.snapshot()["compaction_commits"]) == 2
    assert [item["step"] for item in trace.snapshot()["compaction_commits"]] == [3, 5]


def test_empty_compaction_trigger_is_a_single_noop_and_normal_execution_continues() -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()

    _run(
        _runtime(model, recent_bytes=1_000_000),
        history,
        request_id,
        compact_before_steps=(1,),
        trace=trace,
    )

    assert len(model.requests) == 2
    assert "compaction_calls" not in trace.snapshot()
    assert "compaction_commits" not in trace.snapshot()
