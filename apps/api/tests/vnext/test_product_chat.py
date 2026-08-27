from __future__ import annotations

import asyncio
from uuid import uuid4

from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.events import AgentCompleted, AgentFailed, TextDelta
from app.vnext.llm.protocol import FinalMessage, UserMessage
from app.vnext.product.chat import (
    ProductChatCompleted,
    ProductChatDelta,
    ProductChatError,
    VNextChatService,
)
from app.vnext.product.context import ConversationContextBuilder


class _Repository:
    def __init__(self, *, replay: ChatDialogueTurnResult | None = None) -> None:
        self.replay = replay
        self.appended: list[dict[str, object]] = []
        self.dialogue = [
            DialogueTurn(
                turn_index=1,
                user_message="Ame 在哪里？",
                assistant_message="Xtreme Gaming。",
            )
        ]

    async def lookup_dialogue_request(self, *_args):
        return self.replay

    async def get_all_dialogue_turns(self, *_args):
        return self.dialogue, len(self.dialogue) + 1

    async def append_dialogue_turn(self, **kwargs):
        self.appended.append(kwargs)
        return ChatDialogueTurnResult(
            status="executed",
            turn_index=2,
            assistant_message=str(kwargs["assistant_message"]),
        )


class _Runtime:
    def __init__(self, events) -> None:
        self.events = events
        self.messages = None

    async def run_stream(self, messages):
        self.messages = messages
        for event in self.events:
            yield event


class _ContextBuilder:
    def __init__(self) -> None:
        self.received: tuple[object, str] | None = None

    def build(self, turns, query: str):
        self.received = (turns, query)
        return [UserMessage(content="context-sentinel")]


def _collect(service: VNextChatService, **kwargs):
    async def run():
        prepared = await service.prepare_turn(**kwargs)
        return [event async for event in service.stream_turn(prepared)]

    return asyncio.run(run())


def test_product_chat_replays_full_dialogue_then_persists_before_completed() -> None:
    repository = _Repository()
    runtime = _Runtime(
        [
            TextDelta(text="Ame "),
            TextDelta(text="最近一场表现很好。"),
            AgentCompleted(duration=0.1, final=FinalMessage(content="Ame 最近一场表现很好。")),
        ]
    )
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        ConversationContextBuilder(),
    )

    events = _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="他最近一场表现如何？",
    )

    assert [type(event) for event in events] == [
        ProductChatDelta,
        ProductChatDelta,
        ProductChatCompleted,
    ]
    assert [message.role for message in runtime.messages] == ["user", "final", "user"]
    assert runtime.messages[-1].content == "他最近一场表现如何？"
    assert len(repository.appended) == 1
    assert repository.appended[0]["user_query"] == "他最近一场表现如何？"
    assert repository.appended[0]["assistant_message"] == "Ame 最近一场表现很好。"
    assert events[-1].turn_index == 2


def test_product_chat_failure_does_not_create_a_dialogue_turn() -> None:
    repository = _Repository()
    runtime = _Runtime(
        [AgentFailed(duration=0.1, error_code="max_steps_exceeded", error_message="too many steps")]
    )
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        ConversationContextBuilder(),
    )

    events = _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="query",
    )

    assert events == [ProductChatError(error_code="max_steps_exceeded", reason="too many steps")]
    assert repository.appended == []


def test_product_chat_replays_without_running_the_agent() -> None:
    replay = ChatDialogueTurnResult(
        status="replay",
        turn_index=4,
        assistant_message="stored answer",
    )
    repository = _Repository(replay=replay)
    runtime = _Runtime([])
    context_builder = _ContextBuilder()
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        context_builder,
    )

    events = _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="same query",
    )

    assert events == [ProductChatCompleted(content="stored answer", turn_index=4)]
    assert runtime.messages is None
    assert repository.appended == []
    assert context_builder.received is None


def test_product_chat_uses_the_injected_context_builder() -> None:
    repository = _Repository()
    runtime = _Runtime(
        [AgentCompleted(duration=0.1, final=FinalMessage(content="answer"))]
    )
    context_builder = _ContextBuilder()
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        context_builder,
    )

    _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="query",
    )

    assert context_builder.received == (repository.dialogue, "query")
    assert runtime.messages == [UserMessage(content="context-sentinel")]
