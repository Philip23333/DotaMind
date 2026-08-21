"""Shared helpers and router namespace for Chat Run lifecycle endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1.chat_run_schemas import (
    ChatRunCancelResponse,
    ChatRunCreateRequest,
    ChatRunCreateResponse,
    ChatRunErrorResponse,
    ChatRunEventResponse,
    ChatRunHeartbeatResponse,
    ChatRunResponse,
    ChatRunResumeRequest,
    ChatRunResumeResponse,
    ChatRunStreamErrorResponse,
)
from app.application.chat_run_repository import (
    TERMINAL_RUN_STATUSES,
    ChatRunActiveError,
    ChatRunCheckpointError,
    ChatRunIdempotencyConflictError,
    ChatRunNotFoundError,
    ChatRunRepositoryError,
    ChatRunSummary,
    ChatRunTerminalError,
)
from app.application.chat_run_runtime import ChatRunRuntime
from app.application.run_event_bus import RunEventBusError, StoredRunEvent
from app.observability import (
    CHAT_RUN_SUBSCRIPTIONS,
    record_chat_run_event,
    record_chat_run_event_bus_error,
)

router = APIRouter(prefix="/chat", tags=["chat-runs"])

_ERROR_REASONS = {
    "browser_id_required": "X-DotaMind-Browser-Id is required",
    "chat_run_active": "the session already has an active Run",
    "idempotency_conflict": "request_id has already been used with different inputs",
    "run_terminal": "the Run is already in a terminal state",
    "unavailable": "Run storage is temporarily unavailable",
    "browser_id_invalid": "X-DotaMind-Browser-Id must be a UUID v4",
    "dispatch_failed": "Run could not be scheduled",
    "not_found": "Run was not found",
    "invalid_after": "after must be a non-negative sequence",
    "checkpoint_not_waiting": "Run is not waiting for Checkpoint input",
    "checkpoint_type_mismatch": "Checkpoint type does not match the current Run",
    "checkpoint_option_invalid": "Checkpoint option is invalid",
    "checkpoint_invalid": "Checkpoint selection is invalid",
}


def browser_id_from_request(request: Request) -> str | None:
    value = request.headers.get("x-dotamind-browser-id")
    return value.strip() if value and value.strip() else None


def _runtime(request: Request) -> ChatRunRuntime | None:
    return getattr(request.app.state, "chat_run_runtime", None)


def _run_repository(request: Request):
    return getattr(request.app.state, "chat_run_repository", None)


def _event_bus(request: Request):
    return getattr(request.app.state, "chat_run_event_bus", None)


def _validated_browser_id(request: Request) -> tuple[str | None, JSONResponse | None]:
    browser_id = browser_id_from_request(request)
    if browser_id is None:
        return None, run_error_response("browser_id_required", status_code=422)
    try:
        if UUID(browser_id).version != 4:
            return None, run_error_response("browser_id_invalid", status_code=422)
    except ValueError:
        return None, run_error_response("browser_id_invalid", status_code=422)
    return browser_id, None


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
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    assert browser_id is not None
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


@router.get("/runs/{run_id}", response_model=ChatRunResponse)
async def get_run(run_id: UUID, request: Request) -> ChatRunResponse | JSONResponse:
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    repository = _run_repository(request)
    if repository is None:
        return run_error_response("unavailable", status_code=503)
    try:
        summary = await repository.get_run_for_browser(browser_id, run_id)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)
    return run_response(summary)


@router.get(
    "/sessions/{session_id}/active-run",
    response_model=ChatRunResponse | None,
)
async def get_active_run(
    session_id: UUID,
    request: Request,
) -> ChatRunResponse | None | JSONResponse:
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    repository = _run_repository(request)
    if repository is None:
        return run_error_response("unavailable", status_code=503)
    try:
        summary = await repository.get_active_run(browser_id, session_id)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)
    return run_response(summary) if summary is not None else None


@router.post("/runs/{run_id}/cancel", response_model=ChatRunCancelResponse)
async def cancel_run(run_id: UUID, request: Request) -> ChatRunCancelResponse | JSONResponse:
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    runtime = _runtime(request)
    if runtime is None:
        return run_error_response("unavailable", status_code=503)
    try:
        result = await runtime.cancel_run(browser_id=browser_id, run_id=run_id)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunTerminalError:
        return run_error_response("run_terminal", status_code=409)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)
    return ChatRunCancelResponse(run=run_response(result.run))


@router.post(
    "/runs/{run_id}/resume",
    response_model=ChatRunResumeResponse,
    status_code=202,
)
async def resume_run(
    run_id: UUID,
    body: ChatRunResumeRequest,
    request: Request,
) -> ChatRunResumeResponse | JSONResponse:
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    runtime = _runtime(request)
    if runtime is None:
        return run_error_response("unavailable", status_code=503)
    try:
        result = await runtime.resume_run(
            browser_id=browser_id,
            run_id=run_id,
            checkpoint_type=body.checkpoint_type,
            option_id=body.option_id,
        )
    except ChatRunCheckpointError as exc:
        status_code = 409 if exc.code == "checkpoint_not_waiting" else 422
        return run_error_response(exc.code, status_code=status_code)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)
    return ChatRunResumeResponse(run=run_response(result.run))


@router.get("/runs/{run_id}/events", response_model=None)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    after: int = 0,
) -> StreamingResponse | JSONResponse:
    browser_id, error = _validated_browser_id(request)
    if error is not None:
        return error
    if after < 0:
        return run_error_response("invalid_after", status_code=422)
    repository = _run_repository(request)
    event_bus = _event_bus(request)
    if repository is None or event_bus is None:
        return run_error_response("unavailable", status_code=503)
    try:
        initial_summary = await repository.get_run_for_browser(browser_id, run_id)
    except ChatRunNotFoundError:
        return run_error_response("not_found", status_code=404)
    except ChatRunRepositoryError as exc:
        return run_error_response(exc.code, status_code=503)

    async def stream() -> AsyncIterator[bytes]:
        CHAT_RUN_SUBSCRIPTIONS.inc()
        cursor = after
        session_id = initial_summary.session_id
        try:
            while True:
                try:
                    events = await event_bus.read_after(
                        run_id=run_id,
                        session_id=session_id,
                        after=cursor,
                    )
                    for stored in sorted(events, key=lambda item: item.sequence):
                        if stored.sequence <= cursor:
                            continue
                        cursor = stored.sequence
                        record_chat_run_event("replayed")
                        yield _event_line(stored)
                        if _is_terminal_event(stored):
                            return

                    summary = await repository.get_run_for_browser(browser_id, run_id)
                    if summary.status in TERMINAL_RUN_STATUSES:
                        record_chat_run_event("recovery_terminal")
                        yield _recovery_terminal_line(summary, cursor)
                        return
                    events = await event_bus.wait_after(
                        run_id=run_id,
                        session_id=session_id,
                        after=cursor,
                        timeout_seconds=1,
                    )
                    if events:
                        continue
                    yield _heartbeat_line(summary)
                except asyncio.CancelledError:
                    # Disconnecting an observer must not cancel the detached Run.
                    raise
                except RunEventBusError as exc:
                    record_chat_run_event_bus_error("subscribe")
                    yield _stream_error_line(run_id, session_id, exc.code)
                    return
        finally:
            CHAT_RUN_SUBSCRIPTIONS.dec()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _event_line(stored: StoredRunEvent) -> bytes:
    payload = ChatRunEventResponse(
        run_id=stored.run_id,
        session_id=stored.session_id,
        sequence=stored.sequence,
        event=stored.event.model_dump(mode="json"),
    )
    return (payload.model_dump_json() + "\n").encode("utf-8")


def _heartbeat_line(summary) -> bytes:
    payload = ChatRunHeartbeatResponse(
        run_id=summary.run_id,
        session_id=summary.session_id,
        status=summary.status,
        last_event_sequence=summary.last_event_sequence,
    )
    return (payload.model_dump_json() + "\n").encode("utf-8")


def _recovery_terminal_line(summary, cursor: int) -> bytes:
    payload = ChatRunEventResponse(
        run_id=summary.run_id,
        session_id=summary.session_id,
        sequence=max(cursor + 1, summary.last_event_sequence + 1),
        event={
            "type": "status",
            "status": summary.status,
            "error_code": summary.error_code,
            "transcript_recovery": True,
        },
    )
    return (payload.model_dump_json() + "\n").encode("utf-8")


def _stream_error_line(run_id: UUID, session_id: UUID, error_code: str) -> bytes:
    payload = ChatRunStreamErrorResponse(
        run_id=run_id,
        session_id=session_id,
        error_code=error_code,
    )
    return (payload.model_dump_json() + "\n").encode("utf-8")


def _is_terminal_event(event: StoredRunEvent) -> bool:
    return event.event.type == "status" and (
        event.event.status in TERMINAL_RUN_STATUSES or event.event.status == "waiting_input"
    )


__all__ = ["browser_id_from_request", "router", "run_error_response", "run_response"]
