"""End-to-end acceptance tests for the explicit session compaction loop."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import AgentRuntimeError
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry
from app.vnext.tools.artifacts import register_artifact_tools
from tests.vnext.fakes import ScriptedTranscriptModelClient


class _FixtureInput(BaseModel):
    edition: str


class _FixtureOutput(BaseModel):
    edition: str
    champion: str
    matches: list[dict[str, str]]
    evidence: dict[str, str]
    revisit_detail: str


class _LookupInput(BaseModel):
    key: str


class _LookupOutput(BaseModel):
    value: str


def _fixture_documents() -> dict[str, dict[str, Any]]:
    def document(edition: str, champion: str, detail: str) -> dict[str, Any]:
        return {
            "edition": edition,
            "champion": champion,
            "matches": [
                {"round": "final", "winner": champion},
                {"round": "semifinal", "winner": f"{edition}-runner-up"},
            ],
            "evidence": {
                f"record-{index}": f"{edition}-synthetic-evidence-{index}-" + "x" * 420
                for index in range(90)
            },
            "revisit_detail": detail,
        }

    return {
        "first": document(
            "first synthetic edition",
            "FIRST_EDITION_TEST_MARKER",
            "FIRST_EDITION_REVISIT_DETAIL",
        ),
        "second": document(
            "second synthetic edition",
            "SECOND_EDITION_TEST_MARKER",
            "SECOND_EDITION_REVISIT_DETAIL",
        ),
        "third": document(
            "third synthetic edition",
            "THIRD_EDITION_TEST_MARKER",
            "THIRD_EDITION_REVISIT_DETAIL",
        ),
    }


def _artifact_registry(
    store: SessionArtifactStore,
    documents: dict[str, dict[str, Any]],
    executed_editions: list[str] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    async def lookup(args: _FixtureInput) -> _FixtureOutput:
        if executed_editions is not None:
            executed_editions.append(args.edition)
        return _FixtureOutput.model_validate(documents[args.edition])

    registry.register(
        ToolDefinition(
            name="fixture.lookup",
            description="Read one synthetic tournament fixture.",
            input_model=_FixtureInput,
            output_model=_FixtureOutput,
            handler=lookup,
            externalize_result=True,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _lookup_call(call_id: str, edition: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="fixture.lookup",
        arguments={"edition": edition},
    )


def _session_payload(request: ModelRequest) -> dict[str, Any]:
    marker = "Session context data:\n"
    for message in request.messages:
        if isinstance(message, SystemMessage) and marker in message.content:
            payload, _ = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])
            return payload
    raise AssertionError("session projection missing")


def _request_json(request: ModelRequest) -> str:
    return json.dumps(request.model_dump(mode="json"), ensure_ascii=False)


def _user_count(request: ModelRequest, content: str) -> int:
    return sum(message == UserMessage(content=content) for message in request.messages)


def _limits() -> AgentLimits:
    return AgentLimits(
        application_max_output_tokens=4096,
        deadline_seconds=5,
        answer_timeout_seconds=5,
        compaction_keep_recent_tokens=1,
        compaction_reserve_tokens=160,
    )


def test_explicit_compaction_preserves_artifacts_and_supports_two_rereads() -> None:
    documents = _fixture_documents()
    original_documents = copy.deepcopy(documents)
    store = SessionArtifactStore()
    executed_editions: list[str] = []
    registry = _artifact_registry(store, documents, executed_editions)
    lookup_calls = {
        "first": _lookup_call("lookup-first", "first"),
        "second": _lookup_call("lookup-second", "second"),
        "third": _lookup_call("lookup-third", "third"),
    }

    def first_lookup(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        assert request.tools
        assert _user_count(request, "compare the three synthetic editions") == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[lookup_calls["first"]]))

    def second_lookup(request: ModelRequest) -> ModelResponse:
        assert request.step == 2
        assert _user_count(request, "compare the three synthetic editions") == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[lookup_calls["second"]]))

    def first_summary(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.metadata["purpose"] == "context_compaction"
        payload = json.loads(request.messages[-1].content)  # type: ignore[union-attr]
        encoded = json.dumps(payload, ensure_ascii=False)
        assert "FIRST_EDITION_TEST_MARKER" in encoded
        assert "SECOND_EDITION_TEST_MARKER" not in encoded
        return ModelResponse.from_final(
            "summary one intentionally omits all artifact references",
            finish_reason="stop",
            usage={"prompt_tokens": 101, "completion_tokens": 11},
        )

    def third_lookup(request: ModelRequest) -> ModelResponse:
        assert request.step == 3
        assert _session_payload(request)["summary"] == (
            "**Turn Context (split turn):**\n\n"
            "summary one intentionally omits all artifact references"
        )
        assert _user_count(request, "compare the three synthetic editions") == 1
        assert "FIRST_EDITION_TEST_MARKER" not in _request_json(request)
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[lookup_calls["third"]]))

    def second_summary(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.metadata["purpose"] == "context_compaction"
        assert request.metadata["compaction_kind"] == "turn_prefix"
        payload = json.loads(request.messages[-1].content)  # type: ignore[union-attr]
        encoded = json.dumps(payload, ensure_ascii=False)
        assert "turn_prefix" in payload
        assert "SECOND_EDITION_TEST_MARKER" in encoded
        assert "FIRST_EDITION_TEST_MARKER" not in encoded
        return ModelResponse.from_final(
            "summary two intentionally omits all artifact references",
            finish_reason="stop",
            usage={"prompt_tokens": 202, "completion_tokens": 22},
        )

    def reread_first(request: ModelRequest) -> ModelResponse:
        assert request.step == 4
        payload = _session_payload(request)
        assert "summary one intentionally omits all artifact references" in payload["summary"]
        assert "summary two intentionally omits all artifact references" in payload["summary"]
        first_ref = payload["artifact_locators"][0]["ref"]
        assert len(payload["artifact_locators"]) == 3
        return ModelResponse.from_assistant(
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="read-first-detail",
                        name="artifact.read",
                        arguments={
                            "ref": first_ref,
                            "mode": "read",
                            "path": "revisit_detail",
                        },
                    )
                ]
            )
        )

    def execution_final(request: ModelRequest) -> ModelResponse:
        assert request.step == 5
        assert request.tools
        assert "FIRST_EDITION_REVISIT_DETAIL" in _request_json(request)
        assert "FIRST_EDITION_TEST_MARKER" not in _request_json(request)
        return ModelResponse.from_final("execution complete")

    def answer(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert "summary two intentionally omits all artifact references" in _request_json(request)
        assert "FIRST_EDITION_REVISIT_DETAIL" in _request_json(request)
        assert "FIRST_EDITION_TEST_MARKER" not in _request_json(request)
        return ModelResponse.from_final("final comparison")

    model = ScriptedTranscriptModelClient(
        [
            first_lookup,
            second_lookup,
            first_summary,
            third_lookup,
            second_summary,
            reread_first,
            execution_final,
            answer,
        ]
    )

    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "compare the three synthetic editions",
        initial_messages=[UserMessage(content="compare the three synthetic editions")],
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(model, registry, limits=_limits())

    result = asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(3, 4),
            trace_collector=trace,
        )
    )

    assert result.content == "final comparison"
    assert executed_editions == ["first", "second", "third"]
    assert (
        len(
            [
                request
                for request in model.requests
                if request.metadata.get("purpose") == "context_compaction"
            ]
        )
        == 2
    )
    assert all(
        _user_count(request, "compare the three synthetic editions") == 1
        for request in model.requests
        if request.metadata.get("purpose") != "context_compaction"
    )
    assert all(
        request.tools == []
        for request in model.requests
        if request.metadata.get("purpose") == "context_compaction"
    )

    tool_calls = [
        call.id
        for record in history.records
        if record.kind == "assistant_tool_call"
        for call in record.message.tool_calls  # type: ignore[union-attr]
    ]
    tool_results = [
        record.message.tool_call_id for record in history.records if record.kind == "tool_result"
    ]
    assert (
        tool_calls
        == tool_results
        == [
            "lookup-first",
            "lookup-second",
            "lookup-third",
            "read-first-detail",
        ]
    )
    assert len(history.compaction_records) == 2
    assert history.summary == (
        "**Turn Context (split turn):**\n\n"
        "summary one intentionally omits all artifact references\n\n---\n\n"
        "**Turn Context (split turn):**\n\n"
        "summary two intentionally omits all artifact references"
    )
    assert len(history.artifact_locators) == 3
    assert [record.cut_index for record in history.compaction_records] == [3, 3]

    snapshot = trace.snapshot()
    assert [call["usage"] for call in snapshot["compaction_calls"]] == [
        {"prompt_tokens": 101, "completion_tokens": 11},
        {"prompt_tokens": 202, "completion_tokens": 22},
    ]
    assert [commit["step"] for commit in snapshot["compaction_commits"]] == [3, 4]
    assert all(
        commit["new_revision"] > commit["base_revision"]
        for commit in snapshot["compaction_commits"]
    )

    for locator, edition in zip(
        history.artifact_locators,
        ("first", "second", "third"),
        strict=True,
    ):
        assert asyncio.run(store.get(locator.ref)) == original_documents[edition]

    effective_json = json.dumps(
        [message.model_dump(mode="json") for message in history.effective_messages()],
        ensure_ascii=False,
    )
    assert "FIRST_EDITION_TEST_MARKER" not in effective_json
    assert "FIRST_EDITION_REVISIT_DETAIL" in effective_json
    assert not any(
        isinstance(message, SystemMessage) and "Runtime" in message.content
        for message in history.effective_messages()
    )


def test_failed_compaction_keeps_old_effective_history_for_the_next_request() -> None:
    registry = ToolRegistry()
    executions = 0

    async def lookup(_: _LookupInput) -> _LookupOutput:
        nonlocal executions
        executions += 1
        return _LookupOutput(value="raw lookup result")

    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return one bounded synthetic result.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    first_call = ToolCall(id="first-lookup", name="lookup", arguments={"key": "first"})

    def first_model_call(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[first_call]))

    def failed_summary(request: ModelRequest) -> ModelResponse:
        assert request.metadata.get("purpose") == "context_compaction"
        return ModelResponse.from_final(
            "failed candidate must not be committed",
            finish_reason="length",
        )

    def second_request(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        assert request.tools
        assert request.messages[-1] == UserMessage(content="second question")
        assert _user_count(request, "first question") == 1
        assert "failed candidate must not be committed" not in _request_json(request)
        return ModelResponse.from_final("second execution")

    model = ScriptedTranscriptModelClient(
        [
            first_model_call,
            failed_summary,
            second_request,
            lambda _: ModelResponse.from_final("second answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        registry,
        limits=_limits(),
    )
    history = SessionExecutionHistory()
    first_request_id = uuid4()
    history.begin_request(
        first_request_id,
        "first question",
        initial_messages=[UserMessage(content="first question")],
    )

    with pytest.raises(AgentRuntimeError):
        asyncio.run(
            runtime.run(
                history.effective_messages(),
                execution_history=history,
                request_id=first_request_id,
                compact_before_steps=(2,),
            )
        )

    assert history.compaction_records == ()
    assert history.summary is None
    assert executions == 1
    first_results = [record for record in history.records if record.kind == "tool_result"]
    assert len(first_results) == 1

    second_request_id = uuid4()
    history.begin_request(second_request_id, "second question")
    result = asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=second_request_id,
        )
    )
    assert result.content == "second answer"
    assert executions == 1
    assert history.compaction_records == ()
    assert history.summary is None
    assert "failed candidate must not be committed" not in json.dumps(
        [message.model_dump(mode="json") for message in history.effective_messages()],
        ensure_ascii=False,
    )
