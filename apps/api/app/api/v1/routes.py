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
from app.api.v1.schemas import (
    ExecutionErrorResponse,
    PlanRequest,
    PlanResponse,
)
from app.observability import emit_event

router = APIRouter(tags=["agentic"])
logger = logging.getLogger(__name__)

def _plan_service(request: Request):
    return request.app.state.plan_service


@router.post(
    "/plan",
    response_model=PlanResponse,
    responses={
        500: {"model": ExecutionErrorResponse},
    },
)
async def plan(request: PlanRequest, http_request: Request) -> PlanResponse:
    try:
        result = await _run_plan_service(http_request, request)
        return mappers.plan_response(result.public_response)
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
) -> None:
    """Write exactly one terminal event, then close the stream queue."""

    try:
        result = await service.run(request.query, request.game)
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
    return await _plan_service(request).run(payload.query, payload.game)
