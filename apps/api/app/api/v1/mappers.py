from app.agentic.state import AgentRunState
from app.api.v1 import schemas


def plan_response(result: AgentRunState) -> schemas.PlanResponse:
    return schemas.PlanResponse.model_validate(result.response or {})
