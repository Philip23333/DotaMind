"""Shared helpers and router namespace for Chat Run lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.v1.chat_run_schemas import ChatRunErrorResponse, ChatRunResponse
from app.application.chat_run_repository import ChatRunSummary

router = APIRouter(prefix="/chat", tags=["chat-runs"])

_ERROR_REASONS = {
    "browser_id_required": "X-DotaMind-Browser-Id is required",
    "chat_run_active": "the session already has an active Run",
    "idempotency_conflict": "request_id has already been used with different inputs",
    "run_terminal": "the Run is already in a terminal state",
    "unavailable": "Run storage is temporarily unavailable",
}


def browser_id_from_request(request: Request) -> str | None:
    value = request.headers.get("x-dotamind-browser-id")
    return value.strip() if value and value.strip() else None


def run_response(summary: ChatRunSummary) -> ChatRunResponse:
    return ChatRunResponse(
        run_id=summary.run_id,
        session_id=summary.session_id,
        request_id=summary.request_id,
        status=summary.status,
        user_query=summary.user_query,
        last_event_sequence=summary.last_event_sequence,
        result_turn_id=summary.result_turn_id,
        error_code=summary.error_code,
        created_at=summary.created_at,
        started_at=summary.started_at,
        heartbeat_at=summary.heartbeat_at,
        cancel_requested_at=summary.cancel_requested_at,
        completed_at=summary.completed_at,
    )


def run_error_response(error_code: str, *, status_code: int) -> JSONResponse:
    payload = ChatRunErrorResponse(
        error_code=error_code,
        reason=_ERROR_REASONS.get(error_code, "Run request failed"),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


__all__ = ["browser_id_from_request", "router", "run_error_response", "run_response"]
