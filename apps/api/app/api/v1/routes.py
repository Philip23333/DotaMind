import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.agentic.runtime.errors import AgentExecutionError
from app.agentic.runtime.streaming import (
    ErrorStreamEvent,
    PlanStreamEvent,
    ResultStreamEvent,
    bind_stream_event_publisher,
    reset_stream_event_publisher,
)
from app.api.v1 import mappers
from app.api.v1.chat_schemas import ChatErrorResponse
from app.api.v1.schemas import (
    ExecutionErrorResponse,
    IdempotencyConflictResponse,
    PlanRequest,
    PlanResponse,
    SessionStoreErrorResponse,
)
from app.application.chat_repository import ChatRepositoryError
from app.application.idempotency import IdempotencyConflictError
from app.application.session_store import SessionStoreError
from app.observability import emit_event

router = APIRouter(tags=["agentic"])
logger = logging.getLogger(__name__)

def _plan_service(request: Request):
    return request.app.state.plan_service


@router.post(
    "/plan",
    response_model=PlanResponse,
    responses={
        409: {"model": IdempotencyConflictResponse},
        503: {"model": SessionStoreErrorResponse},
        500: {"model": ExecutionErrorResponse},
    },
)
async def plan(request: PlanRequest, http_request: Request) -> PlanResponse:
    try:
        result = await _run_plan_service(http_request, request)
        return mappers.plan_response(result.public_response)
    except IdempotencyConflictError as exc:
        response = IdempotencyConflictResponse(
            query=exc.query,
            game=exc.game,
            session_id=exc.session_id,
            reason="request_id has already been used with different request inputs",
        )
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))
    except SessionStoreError:
        response = SessionStoreErrorResponse()
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    except ChatRepositoryError as exc:
        return _chat_repository_error_response(exc)
    except AgentExecutionError:
        response = ExecutionErrorResponse()
        return JSONResponse(status_code=500, content=response.model_dump(mode="json"))
    except Exception:
        emit_event(
            logger,
            "agent_run_failed",
            status="error",
            failure_stage="execution",
            failure_code="execution_error",
        )
        response = ExecutionErrorResponse()
        return JSONResponse(status_code=500, content=response.model_dump(mode="json"))


@router.post(
    "/plan/stream",
    responses={
        200: {
            "content": {
                "application/x-ndjson": {
                    "schema": {"type": "string", "description": "One JSON event per line."}
                }
            }
        }
    },
)
async def plan_stream(request: PlanRequest, http_request: Request) -> StreamingResponse:
    """Run the canonical plan path and stream only allowlisted runtime events."""

    service = _plan_service(http_request)

    async def stream() -> AsyncIterator[bytes]:
        queue: asyncio.Queue[PlanStreamEvent | None] = asyncio.Queue()

        def publish(event: PlanStreamEvent) -> None:
            queue.put_nowait(event)

        token = bind_stream_event_publisher(publish)
        task = asyncio.create_task(
            _run_stream_request(
                service,
                request,
                queue,
                http_request.headers.get("x-dotamind-browser-id"),
            )
        )
        # The spawned task inherits the request-scoped publisher. The route task
        # must not retain it after the stream finishes.
        reset_stream_event_publisher(token)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield (event.model_dump_json() + "\n").encode("utf-8")
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_stream_request(
    service,
    request: PlanRequest,
    queue: asyncio.Queue[PlanStreamEvent | None],
    browser_id: str | None,
) -> None:
    """Write exactly one terminal event, then close the stream queue."""

    try:
        result = await _run_plan_service_with_browser_id(service, request, browser_id)
        response = mappers.plan_response(result.public_response).model_dump(mode="json")
        session = result.session_summary
        session_payload = (
            {
                "session_id": session.session_id,
                "game": session.game,
                "title": session.title,
                "title_is_custom": session.title_is_custom,
                "is_pinned": session.is_pinned,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
            if session is not None
            else None
        )
        queue.put_nowait(ResultStreamEvent(response=response, session=session_payload))
    except asyncio.CancelledError:
        raise
    except IdempotencyConflictError:
        queue.put_nowait(
            ErrorStreamEvent(
                error_code="idempotency_conflict",
                reason="request_id has already been used with different request inputs",
            )
        )
    except SessionStoreError:
        queue.put_nowait(
            ErrorStreamEvent(
                error_code="session_store_error",
                reason="session storage is temporarily unavailable",
            )
        )
    except ChatRepositoryError as exc:
        queue.put_nowait(
            ErrorStreamEvent(
                error_code=exc.code,
                reason=(
                    "chat storage is temporarily unavailable"
                    if exc.code
                    not in {
                        "browser_id_required",
                        "request_id_required",
                        "invalid_browser_id",
                        "not_found",
                    }
                    else exc.code
                ),
            )
        )
    except AgentExecutionError:
        queue.put_nowait(ErrorStreamEvent(error_code="execution_error", reason="execution failed"))
    except Exception:
        emit_event(
            logger,
            "agent_run_failed",
            status="error",
            failure_stage="execution",
            failure_code="execution_error",
        )
        queue.put_nowait(ErrorStreamEvent(error_code="execution_error", reason="execution failed"))
    finally:
        queue.put_nowait(None)


async def _run_plan_service(request: Request, payload: PlanRequest):
    headers = getattr(request, "headers", {})
    return await _run_plan_service_with_browser_id(
        _plan_service(request),
        payload,
        headers.get("x-dotamind-browser-id"),
    )


async def _run_plan_service_with_browser_id(service, payload: PlanRequest, browser_id: str | None):
    args = (payload.query, payload.game, payload.session_id, payload.request_id)
    if browser_id is None:
        return await service.run(*args)
    return await service.run(*args, browser_id=browser_id)


def _chat_repository_error_response(exc: ChatRepositoryError) -> JSONResponse:
    if exc.code == "not_found":
        status_code = 404
        reason = "chat session was not found"
        error_code = "chat_not_found"
    elif exc.code in {
        "browser_id_required",
        "request_id_required",
        "invalid_browser_id",
        "invalid_title",
    }:
        status_code = 422
        reason = (
            "browser identity must be a UUID v4"
            if exc.code == "invalid_browser_id"
            else exc.code
        )
        error_code = exc.code
    else:
        status_code = 503
        reason = "chat storage is temporarily unavailable"
        error_code = "chat_store_error"
    response = ChatErrorResponse(error_code=error_code, reason=reason)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))
