from dataclasses import asdict, is_dataclass
from typing import Any

from app.api.v1 import schemas
from app.application.query_service import QueryResult
from app.domain.reports import ReportResult, ServiceCatalog
from app.domain.tasks import ReportRequest
from app.domain.teams import TeamSelection
from app.pipeline.orchestrator import OrchestratorAgent

_orchestrator = OrchestratorAgent()


def meta_request(request: schemas.MetaReportRequest) -> ReportRequest:
    return _orchestrator.plan_structured(
        "meta_report",
        game=request.game,
        patch=request.patch,
        role=request.role,
    )


def patch_request(request: schemas.PatchImpactRequest) -> ReportRequest:
    return _orchestrator.plan_structured(
        "patch_impact",
        game=request.game,
        patch=request.patch,
        role=request.role,
    )


def team_request(request: schemas.TeamReportRequest) -> ReportRequest:
    return _orchestrator.plan_structured(
        "team_report",
        game=request.game,
        team_name=request.team_name,
        team_id=request.team_id,
        time_range=request.time_range,
    )


def claim_request(request: schemas.ClaimVerificationRequest) -> ReportRequest:
    return _orchestrator.plan_structured(
        "claim_verification",
        game=request.game,
        claim=request.claim,
    )


def team_selection(selection: schemas.TeamSelection | None) -> TeamSelection | None:
    if selection is None:
        return None
    return TeamSelection(
        team_id=selection.team_id,
        team_name=selection.team_name,
        time_range=selection.time_range,
    )


def report_response(report: ReportResult) -> Any:
    model = {
        "meta_report": schemas.MetaReportResponse,
        "patch_impact": schemas.PatchImpactResponse,
        "team_report": schemas.TeamReportResponse,
        "claim_verification": schemas.ClaimVerificationResponse,
    }[report.report_type]
    return model.model_validate(_to_dict(report))


def query_response(result: QueryResult) -> schemas.NaturalLanguageQueryResponse:
    return schemas.NaturalLanguageQueryResponse.model_validate(_to_dict(result))


def service_catalog_response(catalog: ServiceCatalog) -> schemas.ServiceCatalogResponse:
    return schemas.ServiceCatalogResponse.model_validate(_to_dict(catalog))


def _to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    return value
