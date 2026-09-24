from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.errors import ModelContextWindowExceeded
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.llm.errors import ModelContextWindowError
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
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool
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


def _tool_call() -> ToolCall:
    return ToolCall(id="provider-reused", name="lookup", arguments={"key": "same"})


def _lookup_registry(*, output_text: str = "same") -> ToolRegistry:
    async def lookup(_args: _LookupInput) -> _LookupOutput:
        return _LookupOutput(
            externalized=True,
            artifact_ref=LOCATOR_REF,
            value={"text": output_text},
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


def _call(call_id: str, name: str, arguments: dict[str, object]) -> ModelResponse:
    return ModelResponse.from_assistant(
        AssistantMessage(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])
    )


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
        assert sum(message == UserMessage(content="second") for message in request.messages) == 1
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
        message.content for message in request.messages if isinstance(message, ToolResultMessage)
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

    assert isinstance(first_events[-1], ProductChatCompleted), first_events
    assert first_events[-1].content == "answer one"
    assert first_events[-1].turn_index == 2
    assert second_events[-1] == ProductChatCompleted(content="answer two", turn_index=3)
    assert repository.get_calls == 2
    state = service._sessions[session_id]
    assert len(state.history.records) == 10
    assert [record.kind for record in state.history.records].count("tool_result") == 2
    assert [record.kind for record in state.history.records].count("delivery_answer") == 2
    assert state.history.summary == "first request summary"
    assert [locator.ref for locator in state.history.artifact_locators] == [LOCATOR_REF]


def test_product_follow_up_uses_automatic_compaction_and_fresh_task_state(
    monkeypatch,
) -> None:
    import app.vnext.product.chat as product_chat

    collectors: list[AgentTraceCollector] = []

    class _CapturedTrace(AgentTraceCollector):
        def __init__(self) -> None:
            super().__init__()
            collectors.append(self)

    monkeypatch.setattr(product_chat, "AgentTraceCollector", _CapturedTrace)
    first_query = "first synthetic task"
    second_query = "second synthetic follow-up"

    class _StrictModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.phase = 0

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request.model_copy(deep=True))
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final(
                    "first synthetic summary omitting the locator", finish_reason="stop"
                )
            turn_number, action = divmod(self.phase, 8)
            query = second_query if turn_number else first_query
            assert sum(message == UserMessage(content=query) for message in request.messages) == 1
            assert request.step == action + 1
            plan_keys = (
                ("first-item", "first-pending")
                if turn_number == 0
                else ("second-item", "second-pending")
            )
            if action == 0:
                if turn_number:
                    payload = _session_context(request)
                    assert payload["summary"]
                    assert payload["artifact_locators"]
                    assert any(
                        isinstance(message, FinalMessage) and message.content == "answer one"
                        for message in request.messages
                    )
                    assert not any(
                        "Task plan:\nCURRENT: first-item" in message.content
                        for message in request.messages
                        if isinstance(message, SystemMessage)
                    )
                self.phase += 1
                return _call(
                    f"plan-{turn_number}",
                    "task.plan",
                    {
                        "items": [
                            {"key": plan_keys[0], "objective": "first synthetic unit"},
                            {"key": plan_keys[1], "objective": "second synthetic unit"},
                        ]
                    },
                )
            if action in {1, 4}:
                index = 0 if action == 1 else 1
                self.phase += 1
                return _call(
                    f"lookup-{turn_number}-{index}",
                    "lookup",
                    {"key": f"{query} {index}"},
                )
            if action in {2, 5}:
                index = 0 if action == 2 else 1
                lookup_result = next(
                    message
                    for message in reversed(request.messages)
                    if isinstance(message, ToolResultMessage)
                    and message.tool_call_id == f"lookup-{turn_number}-{index}"
                )
                assert isinstance(lookup_result.content, dict)
                self.phase += 1
                return _call(
                    f"read-{turn_number}-{index}",
                    "artifact.read",
                    {
                        "ref": lookup_result.content["artifact_ref"],
                        "mode": "read",
                        "path": "facts",
                        "limit": 1,
                    },
                )
            if action in {3, 6}:
                index = 0 if action == 3 else 1
                self.phase += 1
                return _call(
                    f"checkpoint-{turn_number}-{index}",
                    "task.checkpoint",
                    {
                        "key": plan_keys[index],
                        "value": {"finding": f"verified synthetic unit {index}"},
                        "source_tool_call_ids": [f"read-{turn_number}-{index}"],
                    },
                )
            if action == 7:
                assert request.tools == []
                if turn_number == 0:
                    assert _session_context(request)["summary"]
                self.phase += 1
                answer = "answer one" if turn_number == 0 else "answer two"
                return ModelResponse.from_final(answer)
            raise AssertionError("strict model script received an unexpected extra call")

    model = _StrictModel()
    coordinator = TaskStateCoordinator()
    store = SessionArtifactStore()
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    class _ArtifactOutput(BaseModel):
        edition: str
        facts: list[dict[str, str]]

    async def lookup(args: _LookupInput) -> _ArtifactOutput:
        return _ArtifactOutput(
            edition=args.key,
            facts=[{"detail": args.key + "-synthetic-fact-" + "x" * 220} for _ in range(60)],
        )

    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return a complete synthetic esports evidence document.",
            input_model=_LookupInput,
            output_model=_ArtifactOutput,
            handler=lookup,
            externalize_result=True,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    register_task_plan_tool(registry, coordinator)
    register_task_checkpoint_tool(registry, coordinator)
    limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        context_window_tokens=24_000,
        context_output_reserve_tokens=256,
        context_safety_margin_tokens=128,
        context_estimate_bytes_per_token=1,
        context_compaction_test_trigger_percent=75,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
        compaction_reserve_tokens=160,
        max_materialized_context_bytes=100_000,
    )
    runtime = AgentRuntime(model, registry, limits=limits, task_state_coordinator=coordinator)
    repository = _Repository()
    repository.dialogue[0] = repository.dialogue[0].model_copy(
        update={
            "user_message": "old synthetic conversation " * 300,
            "assistant_message": "old synthetic answer " * 300,
        }
    )
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(max_history_chars=20_000),
        DotaVisualEntityEnricher(),
        trace_store=object(),  # enables per-request in-memory trace capture
    )
    session_id = uuid4()

    async def exercise():
        first = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query=first_query,
        )
        first_events = [event async for event in service.stream_turn(first)]
        second = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query=second_query,
        )
        second_events = [event async for event in service.stream_turn(second)]
        return first_events, second_events

    first_events, second_events = asyncio.run(exercise())

    assert isinstance(first_events[-1], ProductChatCompleted), first_events
    assert first_events[-1].content == "answer one"
    assert first_events[-1].turn_index == 2
    assert isinstance(second_events[-1], ProductChatCompleted), second_events
    assert second_events[-1].content == "answer two"
    assert second_events[-1].turn_index == 3
    assert model.phase == 16
    assert [record.kind for record in service._sessions[session_id].history.records].count(
        "delivery_answer"
    ) == 2
    assert len(service._sessions[session_id].history.compaction_records) >= 1
    assert len(collectors) == 2
    first_trace, second_trace = (collector.snapshot() for collector in collectors)
    assert any(commit["trigger"] == "watermark" for commit in first_trace["compaction_commits"])
    assert [item["step"] for item in second_trace["steps"] if "model_request" in item][0] == 1
    assert coordinator.plan is not None
    assert coordinator.plan.current_key is None


def test_product_overflow_recovery_budget_resets_for_each_user_request(monkeypatch) -> None:
    import app.vnext.product.chat as product_chat

    collectors: list[AgentTraceCollector] = []

    class _CapturedTrace(AgentTraceCollector):
        def __init__(self) -> None:
            super().__init__()
            collectors.append(self)

    monkeypatch.setattr(product_chat, "AgentTraceCollector", _CapturedTrace)
    queries = ("first overflow question", "second overflow question")

    class _StrictModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.overflowed: set[str] = set()
            self.turn_index = 0

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request.model_copy(deep=True))
            query = queries[self.turn_index]
            current_user = [
                message for message in request.messages if isinstance(message, UserMessage)
            ]
            if request.tools:
                assert current_user.count(UserMessage(content=query)) == 1
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final(f"summary for {query}", finish_reason="stop")
            if request.tools:
                assert request.step == 1
                if query not in self.overflowed:
                    self.overflowed.add(query)
                    cause = ModelContextWindowError(
                        provider_code="context_length_exceeded", status_code=400
                    )
                    raise ModelContextWindowExceeded(
                        cause=cause,
                        provider_code="context_length_exceeded",
                        status_code=400,
                    )
                assert any(
                    isinstance(message, SystemMessage) and f"summary for {query}" in message.content
                    for message in request.messages
                )
                return ModelResponse.from_final(f"execution for {query}", finish_reason="stop")
            answer = ModelResponse.from_final(f"answer for {query}", finish_reason="stop")
            self.turn_index += 1
            return answer

    model = _StrictModel()
    runtime = AgentRuntime(
        model,
        _lookup_registry(),
        limits=AgentLimits(
            deadline_seconds=5,
            answer_timeout_seconds=5,
            context_window_tokens=100_000,
            context_output_reserve_tokens=128,
            context_safety_margin_tokens=32,
            context_estimate_bytes_per_token=1,
            compaction_keep_recent_tokens=1,
            compaction_max_input_bytes=100_000,
            compaction_reserve_tokens=160,
        ),
    )
    repository = _Repository()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
        trace_store=object(),
    )
    session_id = uuid4()

    async def exercise():
        results = []
        for query in queries:
            prepared = await service.prepare_turn(
                browser_id="browser", session_id=session_id, request_id=uuid4(), query=query
            )
            results.append([event async for event in service.stream_turn(prepared)])
        return results

    results = asyncio.run(exercise())
    assert all(isinstance(events[-1], ProductChatCompleted) for events in results), results
    assert [events[-1].content for events in results] == [
        f"answer for {query}" for query in queries
    ]
    assert len(model.requests) == 8
    assert len(collectors) == 2
    for collector in collectors:
        snapshot = collector.snapshot()
        recoveries = snapshot["overflow_recoveries"]
        assert len(recoveries) == 1
        assert recoveries[0]["status"] == "retry_succeeded"
        assert recoveries[0]["step"] == 1
        assert [commit["trigger"] for commit in snapshot["compaction_commits"]] == ["overflow"]


def test_product_follow_up_succeeds_after_summary_validation_failure(monkeypatch) -> None:
    import app.vnext.product.chat as product_chat

    collectors: list[AgentTraceCollector] = []

    class _CapturedTrace(AgentTraceCollector):
        def __init__(self) -> None:
            super().__init__()
            collectors.append(self)

    monkeypatch.setattr(product_chat, "AgentTraceCollector", _CapturedTrace)
    failed_query = "synthetic lookup then invalid summary"
    follow_up_query = "follow up using saved synthetic evidence"

    class _ArtifactOutput(BaseModel):
        report: str

    store = SessionArtifactStore()
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    async def lookup(_args: _LookupInput) -> _ArtifactOutput:
        return _ArtifactOutput(report="SYNTHETIC-REPORT-" + "evidence " * 4000)

    registry.register(
        ToolDefinition(
            name="lookup",
            description="Fetch synthetic report evidence.",
            input_model=_LookupInput,
            output_model=_ArtifactOutput,
            handler=lookup,
            externalize_result=True,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )

    class _StrictModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.failed_query_calls = 0

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request.model_copy(deep=True))
            if request.metadata.get("purpose") == "context_compaction":
                assert not request.tools
                return ModelResponse.from_final("uncommitted candidate", finish_reason="length")
            query = (
                follow_up_query
                if any(
                    message == UserMessage(content=follow_up_query) for message in request.messages
                )
                else failed_query
            )
            assert sum(message == UserMessage(content=query) for message in request.messages) == 1
            if query == failed_query:
                self.failed_query_calls += 1
                if self.failed_query_calls == 1:
                    return _call("saved-report-call", "lookup", {"key": "synthetic report"})
                if self.failed_query_calls == 2:
                    cause = ModelContextWindowError(
                        provider_code="context_length_exceeded", status_code=400
                    )
                    raise ModelContextWindowExceeded(
                        cause=cause,
                        provider_code="context_length_exceeded",
                        status_code=400,
                    )
                raise AssertionError("failed request unexpectedly retried")
            if request.tools:
                old_result = next(
                    message
                    for message in request.messages
                    if isinstance(message, ToolResultMessage)
                    and message.tool_call_id == "saved-report-call"
                )
                assert isinstance(old_result.content, dict)
                ref = old_result.content["artifact_ref"]
                assert any(
                    locator["ref"] == ref
                    for locator in _session_context(request)["artifact_locators"]
                )
                if any(
                    isinstance(message, ToolResultMessage)
                    and message.tool_call_id == "followup-read"
                    for message in request.messages
                ):
                    return ModelResponse.from_final("follow-up execution", finish_reason="stop")
                return _call(
                    "followup-read",
                    "artifact.read",
                    {"ref": ref, "mode": "read", "path": "report", "limit": 1},
                )
            assert any(
                isinstance(message, ToolResultMessage) and message.tool_call_id == "followup-read"
                for message in request.messages
            )
            return ModelResponse.from_final("follow-up delivered", finish_reason="stop")

    model = _StrictModel()
    runtime = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(
            deadline_seconds=5,
            answer_timeout_seconds=5,
            context_window_tokens=100_000,
            context_output_reserve_tokens=128,
            context_safety_margin_tokens=32,
            context_estimate_bytes_per_token=1,
            compaction_keep_recent_tokens=1,
            compaction_max_input_bytes=100_000,
            compaction_reserve_tokens=160,
        ),
    )
    repository = _Repository()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
        trace_store=object(),
    )
    session_id = uuid4()

    async def exercise():
        first = await service.prepare_turn(
            browser_id="browser", session_id=session_id, request_id=uuid4(), query=failed_query
        )
        first_events = [event async for event in service.stream_turn(first)]
        state = service._sessions[session_id]
        artifact_ref = state.history.artifact_locators[0].ref
        artifact_before = await store.get(artifact_ref)
        history_before = state.history.effective_messages()
        summary_before = state.history.summary
        commits_before = len(state.history.compaction_records)
        second = await service.prepare_turn(
            browser_id="browser", session_id=session_id, request_id=uuid4(), query=follow_up_query
        )
        second_events = [event async for event in service.stream_turn(second)]
        return (
            first_events,
            second_events,
            state,
            artifact_ref,
            artifact_before,
            history_before,
            summary_before,
            commits_before,
        )

    (
        first_events,
        second_events,
        state,
        artifact_ref,
        artifact_before,
        history_before,
        summary_before,
        commits_before,
    ) = asyncio.run(exercise())
    assert first_events[-1].__class__.__name__ == "ProductChatError"
    assert second_events[-1] == ProductChatCompleted(content="follow-up delivered", turn_index=2), (
        second_events
    )
    assert state.history.summary == summary_before
    assert len(state.history.compaction_records) == commits_before
    assert state.history.effective_messages() != history_before  # only the new request was appended
    assert not any(
        isinstance(message, SystemMessage) and "uncommitted candidate" in message.content
        for message in state.history.effective_messages()
    )
    assert asyncio.run(store.get(artifact_ref)) == artifact_before
    assert len(collectors) == 2
    failed_trace, followup_trace = (collector.snapshot() for collector in collectors)
    assert failed_trace.get("compaction_commits", []) == []
    assert failed_trace["compaction_calls"][0]["status"] == "failed"
    assert failed_trace["overflow_recoveries"][0]["status"] == "compaction_failed"
    assert followup_trace["terminal"]["status"] == "completed"
    assert model.failed_query_calls == 2
