"""Shared helpers and router namespace for Chat Run lifecycle endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.v1.chat_run_schemas import (
    ChatRunCreateRequest,
    ChatRunCreateResponse,
    ChatRunErrorResponse,
    ChatRunResponse,
)
from app.application.chat_run_repository import (
    ChatRunActiveError,
    ChatRunIdempotencyConflictError,
    ChatRunNotFoundError,
    ChatRunRepositoryError,
    ChatRunSummary,
)
from app.application.chat_run_runtime import ChatRunRuntime

router = APIRouter(prefix="/chat", tags=["chat-runs"])

_ERROR_REASONS = {
    "browser_id_required": "X-DotaMind-Browser-Id is required",
    "chat_run_active": "the session already has an active Run",
    "idempotency_conflict": "request_id has already been used with different inputs",
    "run_terminal": "the Run is already in a terminal state",
    "unavailable": "Run storage is temporarily unavailable",
    "browser_id_invalid": "X-DotaMind-Browser-Id must be a UUID v4",
    "dispatch_failed": "Run could not be scheduled",
}


def browser_id_from_request(request: Request) -> str | None:
    value = request.headers.get("x-dotamind-browser-id")
    return value.strip() if value and value.strip() else None


def _runtime(request: Request) -> ChatRunRuntime | None:
    return getattr(request.app.state, "chat_run_runtime", None)


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


@router.post(
    "/sessions/{session_id}/runs",
    response_model=ChatRunCreateResponse,
    status_code=202,
)
async def create_run(
    session_id: UUID,
    body: ChatRunCreateRequest,
    request: Request,
) -> ChatRunCreateResponse | JSONResponse:
    browser_id = browser_id_from_request(request)
    if browser_id is None:
        return run_error_response("browser_id_required", status_code=422)
    try:
        if UUID(browser_id).version != 4:
            return run_error_response("browser_id_invalid", status_code=422)
    except ValueError:
        return run_error_response("browser_id_invalid", status_code=422)
    runtime = _runtime(request)
    if runtime is None:
        return run_error_response("unavailable", status_code=503)
    try:
        result = await runtime.create_run(
            browser_id=browser_id,
            session_id=session_id,
            request_id=body.request_id,
            query=body.query,
            game=body.game,
        )
    except ChatRunIdempotencyConflictError:
        return run_error_response("idempotency_conflict", status_code=409)
    except ChatRunActiveError:
        return run_error_response("chat_run_active", status_code=409)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)
    payload = ChatRunCreateResponse(run=run_response(result.run))
    if result.action == "replayed":
        return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))
    return payload


__all__ = ["browser_id_from_request", "router", "run_error_response", "run_response"]
