"""Anonymous browser-owned chat CRUD endpoints."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.v1.chat_schemas import (
    ChatErrorResponse,
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionSummaryResponse,
    ChatSessionUpdateRequest,
    ChatTranscriptTurnResponse,
)
from app.application.chat_repository import ChatNotFoundError, ChatRepositoryError
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.session_store import SessionStoreError

router = APIRouter(prefix="/chat/sessions", tags=["chat"])
logger = logging.getLogger(__name__)


def _repository(request: Request) -> PostgresChatRepository:
    return request.app.state.chat_repository


def _error(code: str, reason: str, http_status: int) -> JSONResponse:
    payload = ChatErrorResponse(error_code=code, reason=reason)
    return JSONResponse(status_code=http_status, content=payload.model_dump(mode="json"))


@router.post("", response_model=ChatSessionSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: ChatSessionCreateRequest,
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> ChatSessionSummaryResponse | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    try:
        summary = await _repository(request).create_session(x_dotamind_browser_id, body.game)
    except ChatRepositoryError as exc:
        return _map_error(exc)
    return _summary_response(summary)


@router.get("", response_model=ChatSessionListResponse)
async def list_sessions(
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> ChatSessionListResponse | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    try:
        sessions = await _repository(request).list_sessions(x_dotamind_browser_id)
    except ChatRepositoryError as exc:
        return _map_error(exc)
    return ChatSessionListResponse(sessions=[_summary_response(item) for item in sessions])


@router.get("/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: UUID,
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> ChatSessionResponse | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    try:
        snapshot = await _repository(request).get_session(x_dotamind_browser_id, session_id)
    except ChatRepositoryError as exc:
        return _map_error(exc)
    return ChatSessionResponse(
        session=_summary_response(snapshot.summary),
        turns=[
            ChatTranscriptTurnResponse(
                turn_index=turn.turn_index,
                request_id=turn.request_id,
                user_query=turn.user_query,
                public_response=turn.public_response,
                created_at=turn.created_at,
            )
            for turn in snapshot.turns
        ],
    )


@router.patch("/{session_id}", response_model=ChatSessionSummaryResponse)
async def rename_session(
    session_id: UUID,
    body: ChatSessionUpdateRequest,
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> ChatSessionSummaryResponse | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    try:
        summary = await _repository(request).update_session(
            x_dotamind_browser_id,
            session_id,
            title=body.title,
            is_pinned=body.is_pinned,
        )
    except ChatRepositoryError as exc:
        return _map_error(exc)
    return _summary_response(summary)


@router.delete("/{session_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    request: Request,
    x_dotamind_browser_id: str | None = Header(default=None),
) -> Response | JSONResponse:
    if not x_dotamind_browser_id:
        return _error("browser_id_required", "browser identity is required", 422)
    try:
        store = request.app.state.plan_service.session_store
        async with store.transaction(str(session_id)):
            # Validate that this task still owns the coordination lease before
            # touching PostgreSQL. The lock is released by normal context exit.
            store.current_fencing_token(str(session_id))
            await _repository(request).delete_session(x_dotamind_browser_id, session_id)
            try:
                await store.clear_session_data(str(session_id))
            except SessionStoreError as exc:
                # PostgreSQL is authoritative. Stale Redis metadata is safe to
                # leave for TTL/cleanup and must not turn a completed delete
                # into a misleading 503.
                logger.warning(
                    "chat coordinator cleanup failed after durable delete: session=%s code=%s",
                    session_id,
                    exc.code,
                )
    except SessionStoreError as exc:
        if exc.code in {"lock_timeout", "lock_lost"}:
            return _error("chat_busy", "chat session is currently in use", 409)
        return _error("chat_store_error", "chat storage is temporarily unavailable", 503)
    except ChatRepositoryError as exc:
        return _map_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _summary_response(summary) -> ChatSessionSummaryResponse:
    return ChatSessionSummaryResponse(
        session_id=summary.session_id,
        game=summary.game,
        title=summary.title,
        title_is_custom=summary.title_is_custom,
        is_pinned=summary.is_pinned,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _map_error(exc: ChatRepositoryError) -> JSONResponse:
    if isinstance(exc, ChatNotFoundError):
        return _error("chat_not_found", "chat session was not found", 404)
    if exc.code == "invalid_browser_id":
        return _error("invalid_browser_id", "browser identity must be a UUID v4", 422)
    if exc.code in {"invalid_title", "invalid_update"}:
        return _error(exc.code, "chat update is invalid", 422)
    return _error("chat_store_error", "chat storage is temporarily unavailable", 503)
