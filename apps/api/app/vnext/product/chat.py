"""Request-bound browser chat bridge for the session-neutral vNext runtime."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import io
import json
import logging
import math
import zipfile
from asyncio import Lock
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import anyio
from pydantic import BaseModel, Field

from app.application.chat_repository import ChatDialogueTurnResult
from app.application.postgres_chat_repository import PostgresChatRepository
from app.vnext.agent.events import AgentCancelled, AgentCompleted, AgentFailed
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import FinalMessage, Message, UserMessage
from app.vnext.product.run_state import AnswerKind, ProductRunState, ProductRunStateProjector
from app.vnext.product.runtime_projection import apply_runtime_event
from app.vnext.session_limits import SessionContextLimits

from .context import ConversationContextBuilder
from .presentation import DotaVisualEntityEnricher, ProductVisualEntity
from .session_history import SessionExecutionHistory
from .trace_store import RunTrace, TraceNotFoundError, TraceStore

logger = logging.getLogger(__name__)


class ProductTraceRef(BaseModel):
    trace_id: str
    expires_at: datetime


class ProductChatState(BaseModel):
    """Internal product envelope around one Run State snapshot."""

    state: ProductRunState
    turn_index: int | None = None
    trace: ProductTraceRef | None = None
    catalog_visual_entities: list[ProductVisualEntity] = Field(default_factory=list)


class ProductTraceSummary(BaseModel):
    trace_id: str
    request_id: str
    status: Literal["completed", "failed", "cancelled"]
    recording_mode: Literal["diagnostic", "test"]
    created_at: datetime
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
    attempt_id: str
    answer_kind: AnswerKind
    visual_entities: tuple[ProductVisualEntity, ...]
    trace_ref: ProductTraceRef | None = None


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
        test_recording_enabled: bool = False,
        persistence_timeout_seconds: float = 15.0,
        session_context_limits: SessionContextLimits | None = None,
    ) -> None:
        if test_recording_enabled and trace_store is None:
            raise ValueError("test recording requires a configured TraceStore")
        if (
            isinstance(persistence_timeout_seconds, bool)
            or not isinstance(persistence_timeout_seconds, (int, float))
            or not math.isfinite(persistence_timeout_seconds)
            or persistence_timeout_seconds <= 0
        ):
            raise ValueError("persistence_timeout_seconds must be a finite positive number")
        self._repository = repository
        self._runtime = runtime
        self._context_builder = context_builder
        self._visual_entity_enricher = visual_entity_enricher
        self._trace_store = trace_store
        self._runtime_factory = runtime_factory
        self._session_runtimes: dict[UUID, AgentRuntime] = {}
        self._sessions: dict[UUID, _SessionState] = {}
        self._trace_ttl_seconds = trace_ttl_seconds
        self._test_recording_enabled = test_recording_enabled
        self._persistence_timeout_seconds = float(persistence_timeout_seconds)
        self._session_context_limits = (
            SessionContextLimits() if session_context_limits is None else session_context_limits
        )

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

    async def stream_turn_states(
        self,
        prepared: PreparedVNextChatTurn,
    ) -> AsyncIterator[ProductChatState]:
        """Run product chat once and yield product-owned lifecycle snapshots."""

        session = self._session_for(prepared.session_id)
        assistant_message_id = f"assistant:{prepared.request_id}"
        async with session.lock:
            projector = ProductRunStateProjector(prepared.request_id, assistant_message_id)
            try:
                replay = await self._repository.lookup_dialogue_request(
                    prepared.browser_id,
                    prepared.session_id,
                    prepared.request_id,
                    prepared.query,
                )
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code == "idempotency_conflict":
                    projector.fail_execution(
                        "idempotency_conflict",
                        "request_id has already been used with different inputs",
                    )
                else:
                    projector.fail_execution("chat_store_error", "聊天服务暂时不可用，请重试。")
                yield ProductChatState(state=projector.snapshot())
                return

            cached = session.completed.get(prepared.request_id)
            if replay is not None:
                trace_ref = (
                    cached.trace_ref
                    if cached is not None and cached.query == prepared.query
                    else None
                )
                projector = ProductRunStateProjector.from_completed_answer(
                    prepared.request_id,
                    assistant_message_id,
                    replay.assistant_message,
                )
                projector.start_persistence()
                projector.persistence_succeeded()
                yield ProductChatState(
                    state=projector.snapshot(),
                    turn_index=replay.turn_index,
                    trace=trace_ref,
                    catalog_visual_entities=[
                        ProductVisualEntity.model_validate(entity)
                        for entity in replay.catalog_visual_entities
                    ],
                )
                return

            if cached is not None:
                if cached.query != prepared.query:
                    projector.fail_execution(
                        "idempotency_conflict",
                        "request_id has already been used with different inputs",
                    )
                    yield ProductChatState(state=projector.snapshot())
                    return
                updates = self._persist_cached_answer(prepared, cached)
                try:
                    async for update in updates:
                        yield update
                finally:
                    await _close_upstream(updates)
                return

            try:
                initial: list[Message] | None = None
                if not session.history.initialized:
                    dialogue, _ = await self._repository.get_all_dialogue_turns(
                        prepared.browser_id, prepared.session_id
                    )
                    initial = self._context_builder.build(dialogue, prepared.query)
                messages = session.history.begin_request(
                    prepared.request_id,
                    prepared.query,
                    initial_messages=initial,
                )
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code == "idempotency_conflict":
                    projector.fail_execution(
                        "idempotency_conflict",
                        "request_id has already been used with different inputs",
                    )
                else:
                    projector.fail_execution("chat_store_error", "聊天服务暂时不可用，请重试。")
                yield ProductChatState(state=projector.snapshot())
                return

            trace_collector: AgentTraceCollector | None = None
            if self._trace_store is not None:
                trace_collector = (
                    AgentTraceCollector(capture_full_calls=True)
                    if self._test_recording_enabled
                    else AgentTraceCollector()
                )
            trace_ref: ProductTraceRef | None = None
            runtime_completed = False
            stream: AsyncIterator[object] | None = None
            try:
                reset = getattr(session.runtime, "reset_request_state", None)
                if callable(reset):
                    reset()
                stream = self._runtime_stream(
                    session.runtime,
                    messages,
                    prepared.request_id,
                    session.history,
                    trace_collector,
                )
            except asyncio.CancelledError:
                if self._test_recording_enabled and trace_collector is not None:
                    await self._save_interrupted_test_trace(
                        prepared,
                        trace_collector,
                        runtime_completed=False,
                    )
                raise
            except Exception:
                projector.fail_execution(
                    "agent_runtime_error",
                    "本次回答未能完成，请重试。",
                )
                if trace_collector is not None:
                    trace_collector.terminal(
                        status="failed",
                        error_code="agent_runtime_error",
                        error_message="agent runtime could not start",
                    )
                    if self._test_recording_enabled:
                        trace_ref = await self._save_run_trace(
                            prepared,
                            trace_collector,
                            status="failed",
                            recording_mode="test",
                        )
                yield ProductChatState(state=projector.snapshot(), trace=trace_ref)
                return

            assert stream is not None
            try:
                yield ProductChatState(state=projector.snapshot())
                while True:
                    try:
                        event = await anext(stream)
                    except StopAsyncIteration:
                        if projector.snapshot().status == "running":
                            projector.fail_execution(
                                "agent_stream_incomplete",
                                "本次回答未能完成，请重试。",
                            )
                            if trace_collector is not None:
                                trace_collector.terminal(
                                    status="failed",
                                    error_code="agent_stream_incomplete",
                                    error_message="agent stream ended without a final message",
                                )
                                if self._test_recording_enabled:
                                    trace_ref = await self._save_run_trace(
                                        prepared,
                                        trace_collector,
                                        status="failed",
                                        recording_mode="test",
                                    )
                            yield ProductChatState(state=projector.snapshot(), trace=trace_ref)
                        return
                    except Exception:
                        projector.fail_execution(
                            "agent_runtime_error",
                            "本次回答未能完成，请重试。",
                        )
                        if trace_collector is not None:
                            trace_collector.terminal(
                                status="failed",
                                error_code="agent_runtime_error",
                                error_message="agent runtime failed",
                            )
                            if self._test_recording_enabled:
                                trace_ref = await self._save_run_trace(
                                    prepared,
                                    trace_collector,
                                    status="failed",
                                    recording_mode="test",
                                )
                        yield ProductChatState(state=projector.snapshot(), trace=trace_ref)
                        return

                    try:
                        changed = apply_runtime_event(projector, event)
                    except Exception:
                        projector.fail_execution(
                            "agent_runtime_error",
                            "本次回答未能完成，请重试。",
                        )
                        if trace_collector is not None:
                            trace_collector.terminal(
                                status="failed",
                                error_code="agent_runtime_error",
                                error_message="invalid Runtime event sequence",
                            )
                            if self._test_recording_enabled:
                                trace_ref = await self._save_run_trace(
                                    prepared,
                                    trace_collector,
                                    status="failed",
                                    recording_mode="test",
                                )
                        await _close_upstream(stream)
                        yield ProductChatState(state=projector.snapshot(), trace=trace_ref)
                        return

                    if isinstance(event, AgentCompleted):
                        if not changed:
                            continue
                        runtime_completed = True
                        if trace_collector is not None:
                            trace_collector.terminal(
                                status="completed",
                                error_code=None,
                                error_message=None,
                            )
                        await _close_upstream(stream)
                        completed_state = projector.snapshot()
                        attempt_id = completed_state.answer.attempt_id
                        answer_kind = completed_state.answer.kind
                        if attempt_id is None or answer_kind is None:
                            # apply_runtime_event validates identity; keep this guard at
                            # the cache boundary so malformed projections cannot persist.
                            projector.fail_execution(
                                "agent_runtime_error",
                                "本次回答未能完成，请重试。",
                            )
                            yield ProductChatState(state=projector.snapshot())
                            return

                        final = event.final
                        try:
                            visual_entities = tuple(
                                self._visual_entity_enricher.match(final.content)
                            )
                        except Exception as exc:
                            logger.warning(
                                "could not enrich vNext answer visuals (%s)",
                                type(exc).__name__,
                            )
                            visual_entities = ()

                        if not any(
                            record.request_id == prepared.request_id
                            and record.kind == "delivery_answer"
                            for record in session.history.records
                        ):
                            session.history.record_delivery(prepared.request_id, final)
                        effective = session.history.effective_messages()
                        if not effective or effective[-1] != final:
                            session.history.set_effective([*effective, final])

                        cached = _CompletedRequest(
                            query=prepared.query,
                            final=final,
                            attempt_id=attempt_id,
                            answer_kind=answer_kind,
                            visual_entities=visual_entities,
                        )
                        session.completed[prepared.request_id] = cached
                        save_task = asyncio.create_task(
                            self._append_dialogue_turn(prepared, cached),
                            name=f"vnext-chat-save-{prepared.request_id}",
                        )
                        if self._test_recording_enabled and trace_collector is not None:
                            try:
                                trace_ref = await self._save_run_trace(
                                    prepared,
                                    trace_collector,
                                    status="completed",
                                    recording_mode="test",
                                )
                            except asyncio.CancelledError:
                                if save_task is not None:
                                    await _finish_owned_save(save_task)
                                raise
                        if trace_ref is not None:
                            cached = _CompletedRequest(
                                query=cached.query,
                                final=cached.final,
                                attempt_id=cached.attempt_id,
                                answer_kind=cached.answer_kind,
                                visual_entities=cached.visual_entities,
                                trace_ref=trace_ref,
                            )
                            session.completed[prepared.request_id] = cached

                        updates = self._persist_cached_answer(
                            prepared,
                            cached,
                            projector=projector,
                            save_task=save_task,
                        )
                        try:
                            async for update in updates:
                                yield update
                        finally:
                            await _close_upstream(updates)
                        return

                    if isinstance(event, (AgentCancelled, AgentFailed)):
                        terminal = projector.snapshot()
                        if trace_collector is not None:
                            trace_collector.terminal(
                                status=(
                                    "cancelled"
                                    if isinstance(event, AgentCancelled)
                                    else "failed"
                                ),
                                error_code=event.error_code,
                                error_message=event.error_message,
                            )
                            if self._test_recording_enabled or isinstance(event, AgentFailed):
                                trace_ref = await self._save_run_trace(
                                    prepared,
                                    trace_collector,
                                    status=(
                                        "cancelled"
                                        if isinstance(event, AgentCancelled)
                                        else "failed"
                                    ),
                                    recording_mode=(
                                        "test"
                                        if self._test_recording_enabled
                                        else "diagnostic"
                                    ),
                                )
                        await _close_upstream(stream)
                        yield ProductChatState(state=terminal, trace=trace_ref)
                        return

                    if changed:
                        yield ProductChatState(state=projector.snapshot())
            except asyncio.CancelledError:
                if (
                    self._test_recording_enabled
                    and trace_collector is not None
                    and trace_ref is None
                ):
                    await self._save_interrupted_test_trace(
                        prepared,
                        trace_collector,
                        runtime_completed=runtime_completed,
                    )
                raise
            finally:
                if stream is not None:
                    await _close_upstream(stream)

    async def _append_dialogue_turn(
        self,
        prepared: PreparedVNextChatTurn,
        cached: _CompletedRequest,
    ) -> ChatDialogueTurnResult:
        async with asyncio.timeout(self._persistence_timeout_seconds):
            return await self._repository.append_dialogue_turn(
                browser_id=prepared.browser_id,
                session_id=prepared.session_id,
                request_id=prepared.request_id,
                user_query=cached.query,
                assistant_message=cached.final.content,
                catalog_visual_entities=[entity.model_dump() for entity in cached.visual_entities],
            )

    async def _persist_cached_answer(
        self,
        prepared: PreparedVNextChatTurn,
        cached: _CompletedRequest,
        *,
        projector: ProductRunStateProjector | None = None,
        save_task: asyncio.Task[ChatDialogueTurnResult] | None = None,
    ) -> AsyncIterator[ProductChatState]:
        assistant_message_id = f"assistant:{prepared.request_id}"
        if projector is None:
            projector = ProductRunStateProjector.from_completed_answer(
                prepared.request_id,
                assistant_message_id,
                cached.final.content,
                attempt_id=cached.attempt_id,
                kind=cached.answer_kind,
            )
        if save_task is None:
            save_task = asyncio.create_task(
                self._append_dialogue_turn(prepared, cached),
                name=f"vnext-chat-save-{prepared.request_id}",
            )

        try:
            yield ProductChatState(
                state=projector.snapshot(),
                trace=cached.trace_ref,
                catalog_visual_entities=list(cached.visual_entities),
            )
            projector.start_persistence()
            yield ProductChatState(
                state=projector.snapshot(),
                trace=cached.trace_ref,
                catalog_visual_entities=list(cached.visual_entities),
            )

            committed: ChatDialogueTurnResult | None = None
            save_error: Exception | None = None
            cancelled_while_saving = False
            if save_task is not None:
                committed, save_error, cancelled_while_saving = await _wait_owned_save(save_task)

            if save_error is None and committed is not None:
                projector.persistence_succeeded()
                terminal = ProductChatState(
                    state=projector.snapshot(),
                    turn_index=committed.turn_index,
                    trace=cached.trace_ref,
                    catalog_visual_entities=[
                        ProductVisualEntity.model_validate(entity)
                        for entity in committed.catalog_visual_entities
                    ],
                )
            else:
                if save_error is not None:
                    logger.warning(
                        "could not persist vNext dialogue turn (%s)",
                        type(save_error).__name__,
                    )
                projector.persistence_failed(
                    "chat_store_error",
                    "回答已生成，但未能确认保存结果，请重试保存。",
                )
                terminal = ProductChatState(
                    state=projector.snapshot(),
                    trace=cached.trace_ref,
                    catalog_visual_entities=list(cached.visual_entities),
                )
            if cancelled_while_saving:
                raise asyncio.CancelledError
            yield terminal
        finally:
            if save_task is not None and not save_task.done():
                _result, error, _cancelled = await _wait_owned_save(save_task)
                if error is not None:
                    logger.warning(
                        "vNext dialogue save did not complete after consumer close (%s)",
                        type(error).__name__,
                    )

    async def download_trace_bundle(self, *, browser_id: str, trace_id: str) -> bytes:
        if self._trace_store is None:
            raise TraceNotFoundError(trace_id)
        trace = await self._trace_store.get(trace_id)
        if trace.browser_id_hash != _browser_hash(browser_id):
            raise PermissionError("trace does not belong to this browser")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "recording_version": 1,
                        "recording_mode": trace.recording_mode,
                        "status": trace.status,
                        "trace_id": trace.trace_id,
                        "session_id": trace.session_id,
                        "request_id": trace.request_id,
                        "created_at": trace.created_at.isoformat(),
                        "expires_at": trace.expires_at.isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr(
                "trace.json",
                json.dumps(trace.trace, ensure_ascii=False, indent=2),
            )
            model_calls = trace.trace.get("model_calls", [])
            archive.writestr(
                "model-calls.jsonl",
                "".join(
                    json.dumps(call, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for call in model_calls
                ),
            )
            archive.writestr(
                "artifact-manifest.json",
                json.dumps(
                    {
                        "included_tool_observations": True,
                        "includes_complete_artifact_store": False,
                        "note": (
                            "trace.json contains tool observations recorded by the Runtime; "
                            "the complete temporary Artifact store is not included."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return stream.getvalue()

    async def list_session_traces(
        self,
        *,
        browser_id: str,
        session_id: UUID,
    ) -> list[ProductTraceSummary]:
        await self._repository.get_session(browser_id, session_id)
        if self._trace_store is None:
            return []
        traces = await self._trace_store.list_session(str(session_id), limit=100)
        expected_browser_hash = _browser_hash(browser_id)
        now = datetime.now(UTC)
        return [
            ProductTraceSummary(
                trace_id=trace.trace_id,
                request_id=trace.request_id,
                status=trace.status,
                recording_mode=trace.recording_mode,
                created_at=trace.created_at,
                expires_at=trace.expires_at,
            )
            for trace in traces
            if trace.browser_id_hash == expected_browser_hash and trace.expires_at > now
        ]

    async def _save_interrupted_test_trace(
        self,
        prepared: PreparedVNextChatTurn,
        collector: AgentTraceCollector,
        *,
        runtime_completed: bool,
    ) -> None:
        status: Literal["completed", "cancelled"] = (
            "completed" if runtime_completed else "cancelled"
        )
        if not runtime_completed:
            collector.terminal(
                status="cancelled",
                error_code="agent_cancelled",
                error_message=None,
            )
        try:
            with anyio.move_on_after(2.0, shield=True) as scope:
                await self._save_run_trace(
                    prepared,
                    collector,
                    status=status,
                    recording_mode="test",
                )
            if scope.cancel_called:
                logger.warning("timed out saving interrupted vNext test recording")
        except asyncio.CancelledError:
            logger.warning("interrupted while saving vNext test recording")
        except Exception as exc:
            logger.warning(
                "could not save interrupted vNext test recording (%s)",
                type(exc).__name__,
            )

    async def _save_run_trace(
        self,
        prepared: PreparedVNextChatTurn,
        collector: AgentTraceCollector,
        *,
        status: Literal["completed", "failed", "cancelled"],
        recording_mode: Literal["diagnostic", "test"],
    ) -> ProductTraceRef | None:
        assert self._trace_store is not None
        created_at = datetime.now(UTC)
        trace_id = str(uuid4())
        expires_at = created_at + timedelta(seconds=self._trace_ttl_seconds)
        try:
            await self._trace_store.put(
                RunTrace(
                    trace_id=trace_id,
                    browser_id_hash=_browser_hash(prepared.browser_id),
                    session_id=str(prepared.session_id),
                    request_id=str(prepared.request_id),
                    created_at=created_at,
                    expires_at=expires_at,
                    status=status,
                    recording_mode=recording_mode,
                    trace=collector.snapshot(),
                )
            )
        except Exception as exc:
            logger.warning(
                "could not save vNext run trace (status=%s, error_type=%s)",
                status,
                type(exc).__name__,
            )
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
                history=SessionExecutionHistory(
                    artifact_locator_capacity=(
                        self._session_context_limits.artifact_locator_capacity
                    ),
                    artifact_locator_hint_chars=(
                        self._session_context_limits.artifact_locator_hint_chars
                    ),
                ),
                lock=Lock(),
                completed={},
            )
            self._sessions[session_id] = state
        return state

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


async def _wait_owned_save(
    task: asyncio.Task[ChatDialogueTurnResult],
) -> tuple[ChatDialogueTurnResult | None, Exception | None, bool]:
    """Wait for a request-owned write without passing caller cancellation into it."""

    caller_cancelled = False
    while True:
        try:
            return await asyncio.shield(task), None, caller_cancelled
        except asyncio.CancelledError:
            if task.cancelled():
                return None, RuntimeError("repository write was cancelled"), caller_cancelled
            caller_cancelled = True
        except Exception as exc:
            return None, exc, caller_cancelled


async def _finish_owned_save(task: asyncio.Task[ChatDialogueTurnResult]) -> None:
    _result, error, _cancelled = await _wait_owned_save(task)
    if error is not None:
        logger.warning(
            "vNext dialogue save did not complete after cancellation (%s)",
            type(error).__name__,
        )


async def _close_upstream(events: AsyncIterator[object]) -> None:
    close = getattr(events, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception as exc:
        logger.warning("could not close vNext Runtime stream (%s)", type(exc).__name__)


__all__ = [
    "PreparedVNextChatTurn",
    "ProductChatState",
    "ProductTraceRef",
    "ProductTraceSummary",
    "VNextChatService",
]
