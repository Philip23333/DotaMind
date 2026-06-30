from fastapi import APIRouter

from app.api.v1 import mappers
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    ClaimVerificationResponse,
    MetaReportRequest,
    MetaReportResponse,
    NaturalLanguageQueryRequest,
    NaturalLanguageQueryResponse,
    PatchImpactRequest,
    PatchImpactResponse,
    PlanRequest,
    PlanResponse,
    ServiceCatalogResponse,
    TeamReportRequest,
    TeamReportResponse,
)
from app.application.catalog import service_catalog
from app.application.plan_service import PlanService
from app.application.query_service import QueryService
from app.application.report_service import ReportService

router = APIRouter(tags=["reports"])

report_service = ReportService()
query_service = QueryService()
plan_service = PlanService()


@router.get("/services", response_model=ServiceCatalogResponse)
def get_services() -> ServiceCatalogResponse:
    return mappers.service_catalog_response(service_catalog())


@router.post("/meta-report", response_model=MetaReportResponse)
async def get_meta_report(request: MetaReportRequest) -> MetaReportResponse:
    report = await report_service.run(mappers.meta_request(request))
    return mappers.report_response(report)


@router.post("/patch-impact", response_model=PatchImpactResponse)
async def get_patch_impact(request: PatchImpactRequest) -> PatchImpactResponse:
    report = await report_service.run(mappers.patch_request(request))
    return mappers.report_response(report)


@router.post("/team-report", response_model=TeamReportResponse)
async def get_team_report(request: TeamReportRequest) -> TeamReportResponse:
    report = await report_service.run(mappers.team_request(request))
    return mappers.report_response(report)


@router.post("/verify-claim", response_model=ClaimVerificationResponse)
async def verify_meta_claim(request: ClaimVerificationRequest) -> ClaimVerificationResponse:
    report = await report_service.run(mappers.claim_request(request))
    return mappers.report_response(report)


@router.post("/query", response_model=NaturalLanguageQueryResponse)
async def query(request: NaturalLanguageQueryRequest) -> NaturalLanguageQueryResponse:
    return mappers.query_response(
        await query_service.run(
            request.query,
            request.game,
            mappers.team_selection(request.team_selection),
        )
    )


@router.post("/plan", response_model=PlanResponse)
async def plan(request: PlanRequest) -> PlanResponse:
    return mappers.plan_response(await plan_service.run(request.query, request.game))
