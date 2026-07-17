from fastapi import APIRouter

from app.api.v1 import mappers
from app.api.v1.schemas import (
    PlanRequest,
    PlanResponse,
)
from app.application.plan_service import PlanService

router = APIRouter(tags=["agentic"])

plan_service = PlanService()


@router.post("/plan", response_model=PlanResponse)
async def plan(request: PlanRequest) -> PlanResponse:
    result = await plan_service.run(request.query, request.game, request.session_id)
    response = mappers.plan_response(result)
    # Echo session_id so clients can continue the conversation.
    response.session_id = str(request.session_id) if request.session_id is not None else None
    return response
