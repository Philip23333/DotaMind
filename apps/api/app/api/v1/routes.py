from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.v1 import mappers
from app.api.v1.schemas import (
    IdempotencyConflictResponse,
    PlanRequest,
    PlanResponse,
    SessionStoreErrorResponse,
)
from app.application.idempotency import IdempotencyConflictError
from app.application.session_store import SessionStoreError

router = APIRouter(tags=["agentic"])

def _plan_service(request: Request):
    return request.app.state.plan_service


@router.post(
    "/plan",
    response_model=PlanResponse,
    responses={
        409: {"model": IdempotencyConflictResponse},
        503: {"model": SessionStoreErrorResponse},
    },
)
async def plan(request: PlanRequest, http_request: Request) -> PlanResponse:
    try:
        result = await _plan_service(http_request).run(
            request.query,
            request.game,
            request.session_id,
            request.request_id,
        )
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
    return mappers.plan_response(result.public_response)
