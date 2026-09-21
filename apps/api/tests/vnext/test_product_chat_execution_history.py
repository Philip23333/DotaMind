from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
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
    value: str


class _Repository:
    def __init__(self) -> None:
        self.dialogue = []
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


def _tool_call() -> ToolCall:
    return ToolCall(id="provider-reused", name="lookup", arguments={"key": "same"})


def _runtime_model() -> ScriptedTranscriptModelClient:
    calls = [_tool_call(), _tool_call()]

    def first_execution(request: ModelRequest) -> ModelResponse:
        assert request.messages[-1] == UserMessage(content="first")
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[calls[0]]))

    def first_follow_up(request: ModelRequest) -> ModelResponse:
        assert _tool_results(request) == [{"value": "same"}]
        return ModelResponse.from_final("execution one")

    def first_answer(request: ModelRequest) -> ModelResponse:
        assert not request.tools
        assert len(_tool_messages(request)) == 1
        return ModelResponse.from_final("answer one")

    def second_execution(request: ModelRequest) -> ModelResponse:
        assert request.messages[-1] == UserMessage(content="second")
        assert len(_tool_messages(request)) == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[calls[1]]))

    def second_follow_up(request: ModelRequest) -> ModelResponse:
        assert _tool_results(request) == [{"value": "same"}, {"value": "same"}]
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


def test_follow_up_model_request_reuses_effective_history_and_reused_provider_id() -> None:
    async def lookup(_args: _LookupInput) -> _LookupOutput:
        return _LookupOutput(value="same")

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
        second = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="second",
        )
        second_events = [event async for event in service.stream_turn(second)]
        return first_events, second_events

    first_events, second_events = asyncio.run(exercise())

    assert first_events[-1] == ProductChatCompleted(content="answer one", turn_index=1)
    assert second_events[-1] == ProductChatCompleted(content="answer two", turn_index=2)
    assert repository.get_calls == 2
    state = service._sessions[session_id]
    assert len(state.history.records) == 10
    assert [record.kind for record in state.history.records].count("tool_result") == 2
    assert [record.kind for record in state.history.records].count("delivery_answer") == 2
