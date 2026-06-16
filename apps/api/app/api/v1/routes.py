from typing import Any

from fastapi import APIRouter

from app.agents.orchestrator import OrchestratorAgent
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
from app.services.experimental_service import ExperimentalService
from app.services.meta_report_service import MetaReportService
from app.services.patch_impact_service import PatchImpactService
from app.services.pricing import service_catalog
from app.services.team_report_service import TeamReportService

router = APIRouter(tags=["reports"])

meta_report_service = MetaReportService()
patch_impact_service = PatchImpactService()
team_report_service = TeamReportService()
claim_verification_service = ClaimVerificationService()
orchestrator_agent = OrchestratorAgent()
experimental_service = ExperimentalService()


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
    async def run_meta_report(service_request: Any) -> Any:
        return await meta_report_service.get_report(service_request)

    async def run_patch_impact(service_request: Any) -> Any:
        return patch_impact_service.get_report(service_request)

    async def run_team_report(service_request: Any) -> Any:
        return await team_report_service.get_report(service_request)

    async def run_claim_verification(service_request: Any) -> Any:
        return claim_verification_service.verify(service_request)

    handlers = {
        "meta_report": run_meta_report,
        "patch_impact": run_patch_impact,
        "team_report": run_team_report,
        "claim_verification": run_claim_verification,
    }
    plan, result = await orchestrator_agent.run(request, handlers)

    return NaturalLanguageQueryResponse(
        query=request.query,
        routed_service=plan.service,
        tasks=plan.tasks,
        result=result,
    )


@router.post("/query/experimental", response_model=NaturalLanguageQueryResponse)
async def query_experimental(
    request: NaturalLanguageQueryRequest,
) -> NaturalLanguageQueryResponse:
    """
    Experimental v2.1 architecture endpoint.
    
    Uses: Orchestrator → Retriever → Analyzer → Critic → Formatter
    
    Currently supports:
    - meta_report (hero recommendations)
    
    Not yet implemented:
    - patch_impact
    - team_report
    - claim_verification
    """
    service, analysis_steps, result = await experimental_service.handle_query(request)
    
    # Convert analysis_steps to PlannedTask format for compatibility
    from app.api.v1.schemas import PlannedTask
    
    tasks = [
        PlannedTask(agent="experimental", action=step, status="completed")
        for step in analysis_steps
    ]
    
    return NaturalLanguageQueryResponse(
        query=request.query,
        routed_service=service,
        tasks=tasks,
        result=result,
    )
