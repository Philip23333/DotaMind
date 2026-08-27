"""Stable browser chat endpoint backed by the vNext AgentRuntime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1.vnext_chat_schemas import ChatMessageRequest
from app.application.chat_repository import (
    ChatIdempotencyConflictError,
    ChatNotFoundError,
    ChatRepositoryError,
)
from app.vnext.product.chat import VNextChatService

router = APIRouter(prefix="/chat/sessions", tags=["chat"])


def _service(request: Request) -> VNextChatService | None:
    return getattr(request.app.state, "vnext_chat_service", None)


def _error(code: str, reason: str, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"status": "error", "error_code": code, "reason": reason},
    )


def _repository_error(exc: ChatRepositoryError) -> JSONResponse:
    if isinstance(exc, ChatNotFoundError):
        return _error("chat_not_found", "chat session was not found", 404)
    if exc.code == "invalid_browser_id":
        return _error("invalid_browser_id", "browser identity must be a UUID v4", 422)
    return _error("chat_store_error", "chat storage is temporarily unavailable", 503)


@router.post("/{session_id}/messages", response_model=None)
async def post_message(
    session_id: UUID,
    body: ChatMessageRequest,
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> StreamingResponse | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    service = _service(request)
    if service is None:
        return _error("unavailable", "vNext chat is temporarily unavailable", 503)
    try:
        prepared = await service.prepare_turn(
            browser_id=x_dotamind_browser_id,
            session_id=session_id,
            request_id=body.request_id,
            query=body.query,
        )
    except ChatIdempotencyConflictError:
        return _error(
            "idempotency_conflict",
            "request_id has already been used with a different query",
            409,
        )
    except ChatRepositoryError as exc:
        return _repository_error(exc)

    async def stream() -> AsyncIterator[bytes]:
        async for event in service.stream_turn(prepared):
            yield (event.model_dump_json() + "\n").encode("utf-8")

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
