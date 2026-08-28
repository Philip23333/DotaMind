"""Request-bound browser chat bridge for the session-neutral vNext runtime."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import AsyncIterator
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
from app.vnext.artifacts import ArtifactNotFoundError, ArtifactRef, ArtifactStore
from app.vnext.llm.protocol import FinalMessage, Message

from .context import ConversationContextBuilder
from .presentation import DotaVisualEntityEnricher, ProductVisualEntity
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
        artifact_store: ArtifactStore | None = None,
        trace_ttl_seconds: int = 72 * 60 * 60,
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._context_builder = context_builder
        self._visual_entity_enricher = visual_entity_enricher
        self._trace_store = trace_store
        self._artifact_store = artifact_store
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
        dialogue, _ = await self._repository.get_all_dialogue_turns(browser_id, session_id)
        return PreparedVNextChatTurn(
            browser_id=browser_id,
            session_id=session_id,
            request_id=request_id,
            query=query,
            history=self._context_builder.build(dialogue, query),
        )

    async def stream_turn(
        self,
        prepared: PreparedVNextChatTurn,
    ) -> AsyncIterator[ProductChatDelta | ProductChatCompleted | ProductChatError]:
        if prepared.replay is not None:
            yield ProductChatCompleted(
                content=prepared.replay.assistant_message,
                turn_index=prepared.replay.turn_index,
                catalog_visual_entities=[
                    ProductVisualEntity.model_validate(entity)
                    for entity in prepared.replay.catalog_visual_entities
                ],
            )
            return

        final: FinalMessage | None = None
        trace_collector = AgentTraceCollector() if self._trace_store is not None else None
        try:
            stream = (
                self._runtime.run_stream(prepared.history, trace_collector=trace_collector)
                if trace_collector is not None
                else self._runtime.run_stream(prepared.history)
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
            error_code = getattr(exc, "code", "agent_runtime_error")
            yield ProductChatError(error_code=error_code, reason=str(exc))
            return

        if final is None:
            yield ProductChatError(
                error_code="agent_runtime_error",
                reason="agent stream ended without a final message",
            )
            return
        visual_entities = self._visual_entity_enricher.match(final.content)
        try:
            committed = await self._repository.append_dialogue_turn(
                browser_id=prepared.browser_id,
                session_id=prepared.session_id,
                request_id=prepared.request_id,
                user_query=prepared.query,
                assistant_message=final.content,
                catalog_visual_entities=[entity.model_dump() for entity in visual_entities],
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

    async def download_trace_bundle(self, *, browser_id: str, trace_id: str) -> bytes:
        if self._trace_store is None:
            raise TraceNotFoundError(trace_id)
        trace = await self._trace_store.get(trace_id)
        if trace.browser_id_hash != _browser_hash(browser_id):
            raise PermissionError("trace does not belong to this browser")
        manifest: dict[str, list[dict[str, str]]] = {"included": [], "missing": []}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("trace.json", trace.model_dump_json(indent=2))
            for ref in _artifact_refs(trace.trace):
                try:
                    artifact = await self._artifact(ref)
                except ArtifactNotFoundError:
                    manifest["missing"].append(ref.model_dump())
                    continue
                artifact_id = ref.id.rsplit(":", 1)[-1]
                filename = f"artifacts/{ref.artifact_type}_{ref.schema_version}_{artifact_id}.json"
                archive.writestr(filename, artifact.model_dump_json(indent=2))
                manifest["included"].append({"ref": ref.model_dump(), "path": filename})
            archive.writestr("artifact-manifest.json", json.dumps(manifest, indent=2))
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

    async def _artifact(self, ref):
        if self._artifact_store is None:
            raise ArtifactNotFoundError(ref.id)
        return await self._artifact_store.get(ref)


def _browser_hash(browser_id: str) -> str:
    return hashlib.sha256(browser_id.encode("utf-8")).hexdigest()


def _artifact_refs(trace: object) -> list[ArtifactRef]:
    """Extract references from executed tool calls and results only.

    Trace tool schemas and model requests can contain illustrative ArtifactRef
    JSON Schema examples. Those examples are not evidence that this run used an
    artifact and must never affect a downloaded bundle.
    """
    found: dict[str, ArtifactRef] = {}

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if {"id", "artifact_type", "schema_version"} <= item.keys():
                try:
                    ref = ArtifactRef.model_validate(item)
                    found[ref.id] = ref
                except ValueError:
                    pass
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    if not isinstance(trace, dict):
        return []
    steps = trace.get("steps")
    if not isinstance(steps, list):
        return []
    for step in steps:
        if not isinstance(step, dict):
            continue
        response = step.get("model_response")
        message = response.get("message") if isinstance(response, dict) else None
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if isinstance(call, dict):
                    visit(call.get("arguments"))
        results = step.get("tool_results")
        if isinstance(results, list):
            for item in results:
                result = item.get("result") if isinstance(item, dict) else None
                if isinstance(result, dict):
                    visit(result.get("content"))
    return list(found.values())


__all__ = [
    "PreparedVNextChatTurn",
    "ProductChatCompleted",
    "ProductChatDelta",
    "ProductChatError",
    "VNextChatService",
]
