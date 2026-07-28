from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1 import mappers
from app.api.v1.schemas import (
    IdempotencyConflictResponse,
    PlanRequest,
    PlanResponse,
)
from app.application.idempotency import IdempotencyConflictError
from app.application.plan_service import PlanService

router = APIRouter(tags=["agentic"])

plan_service = PlanService()


@router.post(
    "/plan",
    response_model=PlanResponse,
    responses={409: {"model": IdempotencyConflictResponse}},
)
async def plan(request: PlanRequest) -> PlanResponse:
    try:
        result = await plan_service.run(
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
    return mappers.plan_response(result.public_response)
