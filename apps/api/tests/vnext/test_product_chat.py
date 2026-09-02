from __future__ import annotations

import asyncio
from uuid import uuid4

from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.events import AgentCancelled, AgentCompleted, AgentFailed, TextDelta
from app.vnext.llm.protocol import FinalMessage, UserMessage
from app.vnext.product.chat import (
    ProductChatCompleted,
    ProductChatDelta,
    ProductChatError,
    VNextChatService,
)
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import ProductVisualEntity


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
            catalog_visual_entities=list(kwargs.get("catalog_visual_entities", [])),
        )


class _Runtime:
    def __init__(self, events) -> None:
        self.events = events
        self.messages = None

    async def run_stream(self, messages, *, trace_collector=None):
        self.messages = messages
        for event in self.events:
            yield event


class _ContextBuilder:
    def __init__(self) -> None:
        self.received: tuple[object, str] | None = None

    def build(self, turns, query: str):
        self.received = (turns, query)
        return [UserMessage(content="context-sentinel")]


class _VisualEntityEnricher:
    def __init__(self, entities: list[ProductVisualEntity] | None = None) -> None:
        self.entities = entities or []
        self.received: list[str] = []

    def match(self, text: str) -> list[ProductVisualEntity]:
        self.received.append(text)
        return self.entities


class _TraceStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved = []

    async def put(self, trace) -> None:
        if self.fail:
            raise OSError("unavailable")
        self.saved.append(trace)


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
        _VisualEntityEnricher(),
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
        _VisualEntityEnricher(),
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


def test_product_chat_persists_only_failed_runs_and_preserves_original_error_on_store_failure() -> (
    None
):
    browser_id = str(uuid4())
    trace_store = _TraceStore()
    service = VNextChatService(  # type: ignore[arg-type]
        _Repository(),
        _Runtime(
            [AgentFailed(duration=0.1, error_code="max_steps_exceeded", error_message="failed")]
        ),
        ConversationContextBuilder(),
        _VisualEntityEnricher(),
        trace_store=trace_store,
    )

    events = _collect(
        service,
        browser_id=browser_id,
        session_id=uuid4(),
        request_id=uuid4(),
        query="query",
    )

    assert events[0].trace is not None
    assert len(trace_store.saved) == 1
    assert trace_store.saved[0].browser_id_hash

    unavailable = VNextChatService(  # type: ignore[arg-type]
        _Repository(),
        _Runtime(
            [AgentFailed(duration=0.1, error_code="max_steps_exceeded", error_message="failed")]
        ),
        ConversationContextBuilder(),
        _VisualEntityEnricher(),
        trace_store=_TraceStore(fail=True),
    )
    unavailable_events = _collect(
        unavailable,
        browser_id=browser_id,
        session_id=uuid4(),
        request_id=uuid4(),
        query="query",
    )
    assert unavailable_events == [
        ProductChatError(error_code="max_steps_exceeded", reason="failed")
    ]


def test_product_chat_does_not_save_success_or_cancellation_traces() -> None:
    for event in (
        AgentCompleted(duration=0.1, final=FinalMessage(content="done")),
        AgentCancelled(error_code="agent_cancelled", error_message="cancelled"),
    ):
        trace_store = _TraceStore()
        service = VNextChatService(  # type: ignore[arg-type]
            _Repository(),
            _Runtime([event]),
            ConversationContextBuilder(),
            _VisualEntityEnricher(),
            trace_store=trace_store,
        )
        _collect(
            service,
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="query",
        )
        assert trace_store.saved == []


def test_product_chat_replays_without_running_the_agent() -> None:
    replay = ChatDialogueTurnResult(
        status="replay",
        turn_index=4,
        assistant_message="stored answer",
    )
    repository = _Repository(replay=replay)
    runtime = _Runtime([])
    context_builder = _ContextBuilder()
    visual_entity_enricher = _VisualEntityEnricher()
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        context_builder,
        visual_entity_enricher,
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
    assert visual_entity_enricher.received == []


def test_product_chat_uses_the_injected_context_builder() -> None:
    repository = _Repository()
    runtime = _Runtime([AgentCompleted(duration=0.1, final=FinalMessage(content="answer"))])
    context_builder = _ContextBuilder()
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        context_builder,
        _VisualEntityEnricher(),
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


def test_product_chat_bounds_runtime_history_without_mutating_durable_dialogue() -> None:
    repository = _Repository()
    repository.dialogue = [
        DialogueTurn(
            turn_index=index,
            user_message=f"user {index}",
            assistant_message=f"assistant {index}",
        )
        for index in range(1, 21)
    ]
    runtime = _Runtime([AgentCompleted(duration=0.1, final=FinalMessage(content="answer"))])
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        ConversationContextBuilder(max_turns=3),
        _VisualEntityEnricher(),
    )

    _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="current",
    )

    assert [(message.role, message.content) for message in runtime.messages] == [
        ("user", "user 18"),
        ("final", "assistant 18"),
        ("user", "user 19"),
        ("final", "assistant 19"),
        ("user", "user 20"),
        ("final", "assistant 20"),
        ("user", "current"),
    ]
    assert len(repository.dialogue) == 20
    assert repository.dialogue[0].user_message == "user 1"
    assert len(repository.appended) == 1


def test_product_chat_persists_and_returns_visual_metadata_without_changing_final_text() -> None:
    repository = _Repository()
    runtime = _Runtime(
        [AgentCompleted(duration=0.1, final=FinalMessage(content="不朽尸王（Undying）"))]
    )
    entity = ProductVisualEntity(
        kind="hero",
        imagePath="/api/v1/assets/dota/heroes/85.png",
        label="不朽尸王",
        names=["不朽尸王", "尸王", "Undying"],
    )
    visual_entity_enricher = _VisualEntityEnricher([entity])
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        ConversationContextBuilder(),
        visual_entity_enricher,
    )

    events = _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="hero",
    )

    assert visual_entity_enricher.received == ["不朽尸王（Undying）"]
    assert repository.appended[0]["assistant_message"] == "不朽尸王（Undying）"
    assert repository.appended[0]["catalog_visual_entities"] == [entity.model_dump()]
    assert events[-1] == ProductChatCompleted(
        content="不朽尸王（Undying）",
        turn_index=2,
        catalog_visual_entities=[entity],
    )


def test_product_chat_replay_returns_persisted_visual_metadata() -> None:
    entity = {
        "kind": "team",
        "imagePath": "/api/v1/assets/esports/teams/1669.png",
        "label": "Team Spirit",
        "names": ["Team Spirit", "TS"],
    }
    repository = _Repository(
        replay=ChatDialogueTurnResult(
            status="replay",
            turn_index=4,
            assistant_message="Team Spirit",
            catalog_visual_entities=[entity],
        )
    )
    runtime = _Runtime([])
    visual_entity_enricher = _VisualEntityEnricher()
    service = VNextChatService(  # type: ignore[arg-type]
        repository,
        runtime,
        ConversationContextBuilder(),
        visual_entity_enricher,
    )

    events = _collect(
        service,
        browser_id=str(uuid4()),
        session_id=uuid4(),
        request_id=uuid4(),
        query="same query",
    )

    assert events[-1].catalog_visual_entities == [ProductVisualEntity.model_validate(entity)]
    assert visual_entity_enricher.received == []


def test_product_chat_runtime_factory_reuses_one_runtime_per_session() -> None:
    created: list[_Runtime] = []

    def factory() -> _Runtime:
        runtime = _Runtime([AgentCompleted(duration=0.1, final=FinalMessage(content="done"))])
        created.append(runtime)
        return runtime

    service = VNextChatService(  # type: ignore[arg-type]
        _Repository(),
        _Runtime([]),
        ConversationContextBuilder(),
        _VisualEntityEnricher(),
        runtime_factory=factory,
    )
    browser_id = str(uuid4())
    first_session = uuid4()

    for session_id in (first_session, first_session, uuid4()):
        _collect(
            service,
            browser_id=browser_id,
            session_id=session_id,
            request_id=uuid4(),
            query="query",
        )

    assert len(created) == 2
    service.discard_session(first_session)
    _collect(
        service,
        browser_id=browser_id,
        session_id=first_session,
        request_id=uuid4(),
        query="query",
    )
    assert len(created) == 3
