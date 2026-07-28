from app.api.v1 import schemas


def plan_response(public_response: dict) -> schemas.PlanResponse:
    return schemas.PlanResponse.model_validate(public_response)
