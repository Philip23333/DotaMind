from fastapi import APIRouter

from app.agents.planner import PlannerAgent
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    ClaimVerificationResponse,
    MetaReportRequest,
    MetaReportResponse,
    NaturalLanguageQueryRequest,
    NaturalLanguageQueryResponse,
    PatchImpactRequest,
    PatchImpactResponse,
    ServiceCatalogResponse,
    TeamReportRequest,
    TeamReportResponse,
)
from app.services.claim_verification_service import ClaimVerificationService
from app.services.meta_report_service import MetaReportService
from app.services.patch_impact_service import PatchImpactService
from app.services.pricing import service_catalog
from app.services.team_report_service import TeamReportService

router = APIRouter(tags=["reports"])

meta_report_service = MetaReportService()
patch_impact_service = PatchImpactService()
team_report_service = TeamReportService()
claim_verification_service = ClaimVerificationService()
planner_agent = PlannerAgent()


@router.get("/services", response_model=ServiceCatalogResponse)
def get_services() -> ServiceCatalogResponse:
    return service_catalog()


@router.post("/meta-report", response_model=MetaReportResponse)
async def get_meta_report(request: MetaReportRequest) -> MetaReportResponse:
    return await meta_report_service.get_report(request)


@router.post("/patch-impact", response_model=PatchImpactResponse)
def get_patch_impact(request: PatchImpactRequest) -> PatchImpactResponse:
    return patch_impact_service.get_report(request)


@router.post("/team-report", response_model=TeamReportResponse)
async def get_team_report(request: TeamReportRequest) -> TeamReportResponse:
    return await team_report_service.get_report(request)


@router.post("/verify-claim", response_model=ClaimVerificationResponse)
def verify_meta_claim(request: ClaimVerificationRequest) -> ClaimVerificationResponse:
    return claim_verification_service.verify(request)


@router.post("/query", response_model=NaturalLanguageQueryResponse)
async def query(request: NaturalLanguageQueryRequest) -> NaturalLanguageQueryResponse:
    routed_service, tasks = planner_agent.plan(request.query)

    if routed_service == "patch_impact":
        result = patch_impact_service.get_report(
            PatchImpactRequest(game=request.game, patch="latest")
        )
    elif routed_service == "team_report":
        result = await team_report_service.get_report(
            TeamReportRequest(game=request.game, team_name="Team Spirit")
        )
    elif routed_service == "claim_verification":
        result = claim_verification_service.verify(
            ClaimVerificationRequest(game=request.game, claim=request.query)
        )
    else:
        result = await meta_report_service.get_report(
            MetaReportRequest(game=request.game, patch="latest", role="offlane")
        )

    return NaturalLanguageQueryResponse(
        query=request.query,
        routed_service=routed_service,
        tasks=tasks,
        result=result,
    )
