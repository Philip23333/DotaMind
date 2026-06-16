"""
Experimental v2.1 service using new architecture:
Orchestrator → Retriever → Analyzer → Critic → Formatter

This service demonstrates the new data flow without LLM (Milestone 1).
"""

import logging
import time
from typing import Any

from app.agents.analyzer import AnalyzerAgent
from app.agents.critic import CriticAgent
from app.agents.orchestrator import OrchestratorAgent
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    MetaReportRequest,
    NaturalLanguageQueryRequest,
    PatchImpactRequest,
    TeamReportRequest,
)
from app.services.claim_verification_service import ClaimVerificationService
from app.services.patch_impact_service import PatchImpactService
from app.services.team_report_service import TeamReportService
from app.tools.formatter import FormatterTool
from app.tools.retriever import RetrieverTool

logger = logging.getLogger(__name__)


class ExperimentalService:
    """
    v2.1 architecture service (Milestone 1 - rule-based, no LLM).
    
    Flow:
    1. Orchestrator.plan() → identify intent
    2. RetrieverTool.retrieve_*() → fetch data
    3. AnalyzerAgent.analyze_*() → compute scores + evidence
    4. CriticAgent.review_evidence() → validate
    5. FormatterTool.format_*() → build response
    """

    def __init__(self) -> None:
        self.orchestrator = OrchestratorAgent()
        self.retriever = RetrieverTool()
        self.analyzer = AnalyzerAgent()
        self.critic = CriticAgent()
        self.formatter = FormatterTool()
        self.patch_impact_service = PatchImpactService()
        self.team_report_service = TeamReportService()
        self.claim_verification_service = ClaimVerificationService()

    async def handle_query(
        self, request: NaturalLanguageQueryRequest
    ) -> tuple[str, list[str], Any]:
        """
        Handle natural language query using v2.1 architecture.
        
        Returns:
            (routed_service, analysis_steps, response)
        """
        started_at = time.perf_counter()
        logger.info(
            "Experimental query start game=%s query_chars=%s",
            request.game,
            len(request.query),
        )
        # Step 1: Plan
        plan = self.orchestrator.plan(request)
        logger.info(
            "Experimental orchestrator planned service=%s tasks=%s request_type=%s",
            plan.service,
            len(plan.tasks),
            type(plan.request).__name__,
        )
        
        analysis_steps = [f"Orchestrator identified intent: {plan.service}"]
        
        # Step 2-5: Execute based on service type
        if plan.service == "meta_report":
            response = await self._handle_meta_report(
                plan.request, analysis_steps  # type: ignore
            )
        elif plan.service == "patch_impact":
            response = await self._handle_patch_impact(
                plan.request, analysis_steps  # type: ignore
            )
        elif plan.service == "team_report":
            response = await self._handle_team_report(
                plan.request, analysis_steps  # type: ignore
            )
        elif plan.service == "claim_verification":
            response = await self._handle_claim_verification(
                plan.request, analysis_steps  # type: ignore
            )
        else:
            raise ValueError(f"Unknown service: {plan.service}")
        
        logger.info(
            "Experimental query complete service=%s elapsed_ms=%s steps=%s result_type=%s",
            plan.service,
            round((time.perf_counter() - started_at) * 1000),
            len(analysis_steps),
            type(response).__name__,
        )
        return plan.service, analysis_steps, response

    async def _handle_meta_report(
        self, request: MetaReportRequest, analysis_steps: list[str]
    ) -> Any:
        """Handle meta report using v2.1 flow."""
        # Step 2: Retrieve
        logger.info(
            "Experimental retriever start task=meta_report role=%s patch=%s",
            request.role,
            request.patch,
        )
        bundle = await self.retriever.retrieve_meta(request.role, request.patch)
        logger.info(
            "Experimental retriever complete task=meta_report records=%s sources=%s data_source=%s",
            len(bundle.records),
            bundle.sources,
            bundle.data_source,
        )
        analysis_steps.append(
            f"Retriever fetched {len(bundle.records)} heroes from {bundle.data_source}"
        )
        
        if not bundle.records:
            logger.warning("No hero data retrieved")
            analysis_steps.append("No data available - cannot generate report")
            # Return minimal response
            return self.formatter.format_meta_report(
                game=request.game,
                patch=request.patch,
                role=request.role,
                heroes=[],
                sources=bundle.sources,
                analysis_steps=analysis_steps,
            )
        
        # Step 3: Analyze
        logger.info(
            "Experimental analyzer start task=meta_report records=%s role=%s",
            len(bundle.records),
            request.role,
        )
        heroes = await self.analyzer.analyze_meta_report(bundle.records, request.role)
        logger.info(
            "Experimental analyzer complete task=meta_report heroes=%s",
            len(heroes),
        )
        analysis_steps.append(
            f"Analyzer scored {len(heroes)} heroes using weighted formula + LLM insights"
        )
        
        # Step 4: Critic review
        # Collect all evidence from all heroes
        all_evidence = []
        for hero in heroes:
            all_evidence.extend(hero.evidence)
        
        review = self.critic.review_evidence(all_evidence)
        logger.info(
            "Experimental critic reviewed task=meta_report passed=%s evidence_items=%s reasons=%s",
            review.passed,
            len(all_evidence),
            review.reasons,
        )
        if review.passed:
            analysis_steps.append("Critic approved: evidence validation passed")
        else:
            analysis_steps.append(f"Critic warning: {', '.join(review.reasons)}")
            logger.warning(f"Critic review failed: {review.reasons}")
        
        # Step 5: Format
        response = self.formatter.format_meta_report(
            game=request.game,
            patch=request.patch,
            role=request.role,
            heroes=heroes,
            sources=bundle.sources,
            analysis_steps=analysis_steps,
        )
        logger.info(
            "Experimental formatter complete task=meta_report heroes=%s confidence=%.3f",
            len(response.top_heroes),
            response.confidence,
        )
        
        return response

    async def _handle_patch_impact(
        self, request: PatchImpactRequest, analysis_steps: list[str]
    ) -> Any:
        """Handle patch impact via stable service until the v2.1 path is migrated."""
        logger.info(
            "Experimental fallback start task=patch_impact patch=%s role=%s "
            "service=PatchImpactService",
            request.patch,
            request.role,
        )
        analysis_steps.append("Retriever delegated patch data to stable PatchImpactService")
        response = self.patch_impact_service.get_report(request)
        analysis_steps.append("Analyzer reused existing patch impact summarizer")
        analysis_steps.append("Critic skipped: patch impact v2.1 evidence review pending")
        logger.info(
            "Experimental fallback complete task=patch_impact winners=%s losers=%s confidence=%.3f",
            len(response.winners),
            len(response.losers),
            response.confidence,
        )
        return response

    async def _handle_team_report(
        self, request: TeamReportRequest, analysis_steps: list[str]
    ) -> Any:
        """Handle team report via stable service until the v2.1 path is migrated."""
        logger.info(
            "Experimental fallback start task=team_report team=%s service=TeamReportService",
            request.team_name,
        )
        analysis_steps.append("Retriever delegated team data to stable TeamReportService")
        response = await self.team_report_service.get_report(request)
        analysis_steps.append("Analyzer reused existing team intelligence summarizer")
        analysis_steps.append("Critic skipped: team report v2.1 evidence review pending")
        logger.info(
            "Experimental fallback complete task=team_report team=%s confidence=%.3f",
            response.team_name,
            response.confidence,
        )
        return response

    async def _handle_claim_verification(
        self, request: ClaimVerificationRequest, analysis_steps: list[str]
    ) -> Any:
        """Handle claim verification via stable service until the v2.1 path is migrated."""
        logger.info(
            "Experimental fallback start task=claim_verification claim_chars=%s "
            "service=ClaimVerificationService",
            len(request.claim),
        )
        analysis_steps.append(
            "Retriever delegated claim evidence to stable ClaimVerificationService"
        )
        response = self.claim_verification_service.verify(request)
        review = self.critic.review_evidence(response.evidence)
        logger.info(
            "Experimental critic reviewed task=claim_verification passed=%s "
            "evidence_items=%s reasons=%s",
            review.passed,
            len(response.evidence),
            review.reasons,
        )
        if review.passed:
            analysis_steps.append("Critic approved: claim evidence contains no unsupported signals")
        else:
            analysis_steps.append(f"Critic warning: {', '.join(review.reasons)}")
        logger.info(
            "Experimental fallback complete task=claim_verification verdict=%s confidence=%.3f",
            response.verdict,
            response.confidence,
        )
        return response
