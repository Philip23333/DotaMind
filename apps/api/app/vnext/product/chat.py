"""Request-bound browser chat bridge for the session-neutral vNext runtime."""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import zipfile
from asyncio import Lock
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.application.chat_repository import ChatDialogueTurnResult
from app.application.postgres_chat_repository import PostgresChatRepository
from app.vnext.agent.events import AgentCancelled, AgentCompleted, AgentFailed, TextDelta
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import FinalMessage, Message, UserMessage

from .context import ConversationContextBuilder
from .presentation import DotaVisualEntityEnricher, ProductVisualEntity
from .session_history import SessionExecutionHistory
from .trace_store import FailedRunTrace, TraceNotFoundError, TraceStore


class ProductChatEvent(BaseModel):
    type: str


class ProductChatDelta(ProductChatEvent):
    type: Literal["delta"] = "delta"
    text: str


class ProductChatCompleted(ProductChatEvent):
    type: Literal["completed"] = "completed"
    content: str
    turn_index: int
    catalog_visual_entities: list[ProductVisualEntity] = Field(default_factory=list)


class ProductChatError(ProductChatEvent):
    type: Literal["error"] = "error"
    error_code: str
    reason: str
    trace: ProductTraceRef | None = None


class ProductTraceRef(BaseModel):
    trace_id: str
    expires_at: datetime


@dataclass(frozen=True)
class PreparedVNextChatTurn:
    browser_id: str
    session_id: UUID
    request_id: UUID
    query: str
    history: list[Message]
    replay: ChatDialogueTurnResult | None = None


@dataclass(frozen=True, slots=True)
class _CompletedRequest:
    query: str
    final: FinalMessage
    visual_entities: tuple[ProductVisualEntity, ...]


@dataclass(slots=True)
class _SessionState:
    runtime: AgentRuntime
    history: SessionExecutionHistory
    lock: Lock
    completed: dict[UUID, _CompletedRequest]


class VNextChatService:
    """Compose durable dialogue with one request-bound AgentRuntime execution."""

    def __init__(
        self,
        repository: PostgresChatRepository,
        runtime: AgentRuntime,
        context_builder: ConversationContextBuilder,
        visual_entity_enricher: DotaVisualEntityEnricher,
        *,
        trace_store: TraceStore | None = None,
        runtime_factory: Callable[[], AgentRuntime] | None = None,
        trace_ttl_seconds: int = 72 * 60 * 60,
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._context_builder = context_builder
        self._visual_entity_enricher = visual_entity_enricher
        self._trace_store = trace_store
        self._runtime_factory = runtime_factory
        self._session_runtimes: dict[UUID, AgentRuntime] = {}
        self._sessions: dict[UUID, _SessionState] = {}
        self._trace_ttl_seconds = trace_ttl_seconds

    async def prepare_turn(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        query: str,
    ) -> PreparedVNextChatTurn:
        replay = await self._repository.lookup_dialogue_request(
            browser_id,
            session_id,
            request_id,
            query,
        )
        if replay is not None:
            return PreparedVNextChatTurn(
                browser_id=browser_id,
                session_id=session_id,
                request_id=request_id,
                query=query,
                history=[],
                replay=replay,
        )
        state = self._session_for(session_id)
        if state.history.initialized:
            history = state.history.effective_messages()
            history.append(UserMessage(content=query))
        else:
            dialogue, _ = await self._repository.get_all_dialogue_turns(browser_id, session_id)
            history = self._context_builder.build(dialogue, query)
        return PreparedVNextChatTurn(
            browser_id=browser_id,
            session_id=session_id,
            request_id=request_id,
            query=query,
            history=history,
        )

    async def stream_turn(
        self,
        prepared: PreparedVNextChatTurn,
    ) -> AsyncIterator[ProductChatDelta | ProductChatCompleted | ProductChatError]:
        state = self._session_for(prepared.session_id)
        async with state.lock:
            try:
                replay = await self._repository.lookup_dialogue_request(
                    prepared.browser_id,
                    prepared.session_id,
                    prepared.request_id,
                    prepared.query,
                )
            except Exception as exc:
                yield ProductChatError(
                    error_code=getattr(exc, "code", "chat_store_error"), reason=str(exc)
                )
                return
            if replay is not None:
                yield self._completed_event(replay)
                return

            cached = state.completed.get(prepared.request_id)
            if cached is not None:
                if cached.query != prepared.query:
                    yield ProductChatError(
                        error_code="idempotency_conflict",
                        reason="request_id has already been used with different inputs",
                    )
                    return
                async for event in self._commit_cached(prepared, cached):
                    yield event
                return

            try:
                initial: list[Message] | None = None
                if not state.history.initialized:
                    dialogue, _ = await self._repository.get_all_dialogue_turns(
                        prepared.browser_id, prepared.session_id
                    )
                    initial = self._context_builder.build(dialogue, prepared.query)
                messages = state.history.begin_request(
                    prepared.request_id,
                    prepared.query,
                    initial_messages=initial,
                )
                reset = getattr(state.runtime, "reset_request_state", None)
                if callable(reset):
                    reset()
                trace_collector = (
                    AgentTraceCollector() if self._trace_store is not None else None
                )
                final: FinalMessage | None = None
                stream = self._runtime_stream(
                    state.runtime,
                    messages,
                    prepared.request_id,
                    state.history,
                    trace_collector,
                )
                async for event in stream:
                    if isinstance(event, TextDelta):
                        yield ProductChatDelta(text=event.text)
                    elif isinstance(event, AgentCompleted):
                        final = event.final
                    elif isinstance(event, (AgentCancelled, AgentFailed)):
                        trace_ref = None
                        if isinstance(event, AgentFailed) and trace_collector is not None:
                            trace_ref = await self._save_failed_trace(prepared, trace_collector)
                        yield ProductChatError(
                            error_code=event.error_code,
                            reason=event.error_message,
                            trace=trace_ref,
                        )
                        return
            except Exception as exc:
                yield ProductChatError(
                    error_code=getattr(exc, "code", "agent_runtime_error"), reason=str(exc)
                )
                return

            if final is None:
                yield ProductChatError(
                    error_code="agent_runtime_error",
                    reason="agent stream ended without a final message",
                )
                return

            visual_entities = tuple(self._visual_entity_enricher.match(final.content))
            state.completed[prepared.request_id] = _CompletedRequest(
                query=prepared.query,
                final=final,
                visual_entities=visual_entities,
            )
            if not any(
                record.request_id == prepared.request_id
                and record.kind == "delivery_answer"
                for record in state.history.records
            ):
                state.history.record_delivery(prepared.request_id, final)
            effective = state.history.effective_messages()
            if not effective or effective[-1] != final:
                state.history.set_effective([*effective, final])

            async for event in self._commit_cached(prepared, state.completed[prepared.request_id]):
                yield event

    async def download_trace_bundle(self, *, browser_id: str, trace_id: str) -> bytes:
        if self._trace_store is None:
            raise TraceNotFoundError(trace_id)
        trace = await self._trace_store.get(trace_id)
        if trace.browser_id_hash != _browser_hash(browser_id):
            raise PermissionError("trace does not belong to this browser")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("trace.json", trace.model_dump_json(indent=2))
            archive.writestr(
                "artifact-manifest.json",
                json.dumps(
                    {
                        "included": [],
                        "note": (
                            "Temporary session tool responses are not persisted in trace bundles."
                        ),
                    },
                    indent=2,
                ),
            )
        return stream.getvalue()

    async def _save_failed_trace(
        self, prepared: PreparedVNextChatTurn, collector: AgentTraceCollector
    ) -> ProductTraceRef | None:
        assert self._trace_store is not None
        created_at = datetime.now(UTC)
        trace_id = str(uuid4())
        expires_at = created_at + timedelta(seconds=self._trace_ttl_seconds)
        try:
            await self._trace_store.put(
                FailedRunTrace(
                    trace_id=trace_id,
                    browser_id_hash=_browser_hash(prepared.browser_id),
                    session_id=str(prepared.session_id),
                    request_id=str(prepared.request_id),
                    created_at=created_at,
                    expires_at=expires_at,
                    trace=collector.snapshot(),
                )
            )
        except Exception:
            return None
        return ProductTraceRef(trace_id=trace_id, expires_at=expires_at)

    def _runtime_for(self, session_id: UUID) -> AgentRuntime:
        if self._runtime_factory is None:
            return self._runtime
        runtime = self._session_runtimes.get(session_id)
        if runtime is None:
            runtime = self._runtime_factory()
            self._session_runtimes[session_id] = runtime
        return runtime

    def _session_for(self, session_id: UUID) -> _SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = _SessionState(
                runtime=self._runtime_for(session_id),
                history=SessionExecutionHistory(),
                lock=Lock(),
                completed={},
            )
            self._sessions[session_id] = state
        return state

    @staticmethod
    def _completed_event(replay: ChatDialogueTurnResult) -> ProductChatCompleted:
        return ProductChatCompleted(
            content=replay.assistant_message,
            turn_index=replay.turn_index,
            catalog_visual_entities=[
                ProductVisualEntity.model_validate(entity)
                for entity in replay.catalog_visual_entities
            ],
        )

    async def _commit_cached(
        self,
        prepared: PreparedVNextChatTurn,
        cached: _CompletedRequest,
    ) -> AsyncIterator[ProductChatCompleted | ProductChatError]:
        try:
            committed = await self._repository.append_dialogue_turn(
                browser_id=prepared.browser_id,
                session_id=prepared.session_id,
                request_id=prepared.request_id,
                user_query=cached.query,
                assistant_message=cached.final.content,
                catalog_visual_entities=[entity.model_dump() for entity in cached.visual_entities],
            )
        except Exception as exc:
            yield ProductChatError(error_code="chat_store_error", reason=str(exc))
            return
        yield ProductChatCompleted(
            content=committed.assistant_message,
            turn_index=committed.turn_index,
            catalog_visual_entities=[
                ProductVisualEntity.model_validate(entity)
                for entity in committed.catalog_visual_entities
            ],
        )

    @staticmethod
    def _runtime_stream(
        runtime: AgentRuntime,
        messages: list[Message],
        request_id: UUID,
        history: SessionExecutionHistory,
        trace_collector: AgentTraceCollector | None,
    ) -> AsyncIterator[object]:
        kwargs: dict[str, object] = {}
        try:
            parameters = inspect.signature(runtime.run_stream).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "execution_history" in parameters:
            kwargs["execution_history"] = history
        if "request_id" in parameters:
            kwargs["request_id"] = request_id
        if trace_collector is not None and "trace_collector" in parameters:
            kwargs["trace_collector"] = trace_collector
        return runtime.run_stream(messages, **kwargs)  # type: ignore[return-value, arg-type]

    def discard_session(self, session_id: UUID) -> None:
        """Drop temporary tool responses when the durable chat session is deleted."""

        self._session_runtimes.pop(session_id, None)
        self._sessions.pop(session_id, None)


def _browser_hash(browser_id: str) -> str:
    return hashlib.sha256(browser_id.encode("utf-8")).hexdigest()


__all__ = [
    "PreparedVNextChatTurn",
    "ProductChatCompleted",
    "ProductChatDelta",
    "ProductChatError",
    "VNextChatService",
]
