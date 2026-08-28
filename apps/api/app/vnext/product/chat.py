"""Request-bound browser chat bridge for the session-neutral vNext runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.chat_repository import ChatDialogueTurnResult
from app.application.postgres_chat_repository import PostgresChatRepository
from app.vnext.agent.events import AgentCancelled, AgentCompleted, AgentFailed, TextDelta
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.protocol import FinalMessage, Message

from .context import ConversationContextBuilder
from .presentation import DotaVisualEntityEnricher, ProductVisualEntity


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
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._context_builder = context_builder
        self._visual_entity_enricher = visual_entity_enricher

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
        try:
            async for event in self._runtime.run_stream(prepared.history):
                if isinstance(event, TextDelta):
                    yield ProductChatDelta(text=event.text)
                elif isinstance(event, AgentCompleted):
                    final = event.final
                elif isinstance(event, (AgentCancelled, AgentFailed)):
                    yield ProductChatError(
                        error_code=event.error_code,
                        reason=event.error_message,
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


__all__ = [
    "PreparedVNextChatTurn",
    "ProductChatCompleted",
    "ProductChatDelta",
    "ProductChatError",
    "VNextChatService",
]
