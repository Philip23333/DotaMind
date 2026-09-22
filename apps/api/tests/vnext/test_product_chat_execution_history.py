from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.chat import ProductChatCompleted, VNextChatService
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import DotaVisualEntityEnricher
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedTranscriptModelClient


class _LookupInput(BaseModel):
    key: str


class _LookupOutput(BaseModel):
    externalized: bool
    artifact_ref: str
    value: dict[str, str]


LOCATOR_REF = "artifact:tool:" + "d" * 32


class _Repository:
    def __init__(self) -> None:
        self.dialogue = [
            DialogueTurn(
                turn_index=1,
                user_message="earlier question",
                assistant_message="earlier answer",
            )
        ]
        self.get_calls = 0
        self.appended: list[dict[str, object]] = []

    async def lookup_dialogue_request(
        self,
        _browser_id: str,
        _session_id: UUID,
        _request_id: UUID,
        _query: str,
    ) -> None:
        return None

    async def get_all_dialogue_turns(self, _browser_id: str, _session_id: UUID):
        self.get_calls += 1
        return self.dialogue, len(self.dialogue) + 1

    async def append_dialogue_turn(self, **kwargs):
        self.appended.append(kwargs)
        self.dialogue.append(kwargs)
        return ChatDialogueTurnResult(
            status="executed",
            turn_index=len(self.dialogue),
            assistant_message=str(kwargs["assistant_message"]),
        )


class _FirstQuestionCompactingRuntime(AgentRuntime):
    async def run_stream(
        self,
        messages,
        *,
        cancellation_token=None,
        event_sink=None,
        trace_collector=None,
        execution_history=None,
        request_id=None,
        compact_before_steps=(),
    ):
        current_user = next(
            message
            for message in reversed(messages)
            if isinstance(message, UserMessage)
        )
        triggers = (2,) if current_user.content == "first" else ()
        async for event in super().run_stream(
            messages,
            cancellation_token=cancellation_token,
            event_sink=event_sink,
            trace_collector=trace_collector,
            execution_history=execution_history,
            request_id=request_id,
            compact_before_steps=triggers,
        ):
            yield event


def _tool_call() -> ToolCall:
    return ToolCall(id="provider-reused", name="lookup", arguments={"key": "same"})


def _lookup_registry() -> ToolRegistry:
    async def lookup(_args: _LookupInput) -> _LookupOutput:
        return _LookupOutput(
            externalized=True,
            artifact_ref=LOCATOR_REF,
            value={"text": "same"},
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return a stable lookup result.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _runtime_model() -> ScriptedTranscriptModelClient:
    calls = [_tool_call(), _tool_call()]

    def first_execution(request: ModelRequest) -> ModelResponse:
        assert request.messages[-1] == UserMessage(content="first")
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[calls[0]]))

    def first_follow_up(request: ModelRequest) -> ModelResponse:
        assert _tool_results(request) == [
            {
                "externalized": True,
                "artifact_ref": LOCATOR_REF,
                "value": {"text": "same"},
            }
        ]
        return ModelResponse.from_final("execution one")

    def first_answer(request: ModelRequest) -> ModelResponse:
        assert not request.tools
        assert len(_tool_messages(request)) == 1
        return ModelResponse.from_final("answer one")

    def second_execution(request: ModelRequest) -> ModelResponse:
        assert request.messages[-1] == UserMessage(content="second")
        assert len(_tool_messages(request)) == 1
        assert sum(
            message == UserMessage(content="second") for message in request.messages
        ) == 1
        assert any(
            isinstance(message, FinalMessage) and message.content == "answer one"
            for message in request.messages
        )
        context = _session_context(request)
        assert context["summary"] == "first request summary"
        assert context["artifact_locators"] == [
            {
                "ref": LOCATOR_REF,
                "source_tool": "lookup",
                "query_hint": '{"key":"same"}',
            }
        ]
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[calls[1]]))

    def second_follow_up(request: ModelRequest) -> ModelResponse:
        assert _tool_results(request) == [
            {
                "externalized": True,
                "artifact_ref": LOCATOR_REF,
                "value": {"text": "same"},
            },
            {
                "externalized": True,
                "artifact_ref": LOCATOR_REF,
                "value": {"text": "same"},
            },
        ]
        return ModelResponse.from_final("execution two")

    def second_answer(request: ModelRequest) -> ModelResponse:
        assert not request.tools
        assert len(_tool_messages(request)) == 2
        return ModelResponse.from_final("answer two")

    return ScriptedTranscriptModelClient(
        [
            first_execution,
            first_follow_up,
            first_answer,
            second_execution,
            second_follow_up,
            second_answer,
        ]
    )


def _tool_results(request: ModelRequest) -> list[object]:
    return [
        message.content
        for message in request.messages
        if isinstance(message, ToolResultMessage)
    ]


def _tool_messages(request: ModelRequest) -> list[ToolResultMessage]:
    return [message for message in request.messages if isinstance(message, ToolResultMessage)]


def _session_context(request: ModelRequest) -> dict[str, object]:
    marker = "Session context data:\n"
    for message in request.messages:
        if isinstance(message, SystemMessage) and marker in message.content:
            payload, _ = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])
            return payload
    raise AssertionError("request did not contain session context")


def test_follow_up_model_request_reuses_effective_history_and_reused_provider_id() -> None:
    async def lookup(_args: _LookupInput) -> _LookupOutput:
        return _LookupOutput(
            externalized=True,
            artifact_ref=LOCATOR_REF,
            value={"text": "same"},
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return a stable lookup result.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    model = _runtime_model()
    runtime = AgentRuntime(model, registry, limits=AgentLimits(deadline_seconds=2))
    repository = _Repository()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
    )
    session_id = uuid4()

    async def exercise():
        first = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="first",
        )
        first_events = [event async for event in service.stream_turn(first)]
        state = service._sessions[session_id]
        state.history.commit_compaction(
            request_id=first.request_id,
            base_revision=state.history.revision,
            summary="first request summary",
            cut_index=2,
        )
        second = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="second",
        )
        second_events = [event async for event in service.stream_turn(second)]
        return first_events, second_events

    first_events, second_events = asyncio.run(exercise())

    assert first_events[-1] == ProductChatCompleted(content="answer one", turn_index=2)
    assert second_events[-1] == ProductChatCompleted(content="answer two", turn_index=3)
    assert repository.get_calls == 2
    state = service._sessions[session_id]
    assert len(state.history.records) == 10
    assert [record.kind for record in state.history.records].count("tool_result") == 2
    assert [record.kind for record in state.history.records].count("delivery_answer") == 2
    assert state.history.summary == "first request summary"
    assert [locator.ref for locator in state.history.artifact_locators] == [LOCATOR_REF]


def test_product_follow_up_uses_runtime_compaction_without_manual_commit() -> None:
    calls = [_tool_call()]

    def first_execution(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        assert sum(message == UserMessage(content="first") for message in request.messages) == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[calls[0]]))

    def compaction(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.metadata["purpose"] == "context_compaction"
        return ModelResponse.from_final("auto first summary", finish_reason="stop")

    def first_execution_final(request: ModelRequest) -> ModelResponse:
        assert request.step == 2
        assert _session_context(request)["summary"] == "auto first summary"
        assert sum(message == UserMessage(content="first") for message in request.messages) == 1
        return ModelResponse.from_final("execution one")

    def first_answer(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert "auto first summary" in json.dumps(request.model_dump(mode="json"))
        return ModelResponse.from_final("answer one")

    def second_execution(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        assert request.tools
        assert _session_context(request)["summary"] == "auto first summary"
        assert sum(message == UserMessage(content="second") for message in request.messages) == 1
        assert any(
            isinstance(message, FinalMessage) and message.content == "answer one"
            for message in request.messages
        )
        return ModelResponse.from_final("execution two")

    def second_answer(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        return ModelResponse.from_final("answer two")

    model = ScriptedTranscriptModelClient(
        [
            first_execution,
            compaction,
            first_execution_final,
            first_answer,
            second_execution,
            second_answer,
        ]
    )
    runtime = _FirstQuestionCompactingRuntime(
        model,
        _lookup_registry(),
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_recent_history_bytes=1,
            compaction_max_input_bytes=100_000,
            compaction_max_output_tokens=128,
            compaction_max_summary_bytes=1_000,
        ),
    )
    repository = _Repository()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
    )
    session_id = uuid4()

    async def exercise():
        first = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="first",
        )
        first_events = [event async for event in service.stream_turn(first)]
        second = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="second",
        )
        second_events = [event async for event in service.stream_turn(second)]
        return first_events, second_events

    first_events, second_events = asyncio.run(exercise())

    assert first_events[-1] == ProductChatCompleted(content="answer one", turn_index=2)
    assert second_events[-1] == ProductChatCompleted(content="answer two", turn_index=3)
    assert (
        len(
            [
                request
                for request in model.requests
                if request.metadata.get("purpose") == "context_compaction"
            ]
        )
        == 1
    )
    state = service._sessions[session_id]
    assert state.history.summary == "auto first summary"
    assert sum(
        message == UserMessage(content="second")
        for message in state.history.effective_messages()
    ) == 1
    assert not any(
        isinstance(message, SystemMessage) for message in state.history.effective_messages()
    )
    assert [record.kind for record in state.history.records].count("delivery_answer") == 2
