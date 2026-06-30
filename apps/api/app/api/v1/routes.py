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
    return mappers.plan_response(await plan_service.run(request.query, request.game))
