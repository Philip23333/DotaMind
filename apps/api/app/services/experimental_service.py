"""
Experimental v2.1 service using new architecture:
Orchestrator → Retriever → Analyzer → Critic → Formatter

This service demonstrates the new data flow without LLM (Milestone 1).
"""

import logging
from typing import Any

from app.agents.analyzer import AnalyzerAgent
from app.agents.critic import CriticAgent
from app.agents.orchestrator import OrchestratorAgent, ServiceName
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    MetaReportRequest,
    NaturalLanguageQueryRequest,
    PatchImpactRequest,
    TeamReportRequest,
)
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

    async def handle_query(
        self, request: NaturalLanguageQueryRequest
    ) -> tuple[str, list[str], Any]:
        """
        Handle natural language query using v2.1 architecture.
        
        Returns:
            (routed_service, analysis_steps, response)
        """
        # Step 1: Plan
        plan = self.orchestrator.plan(request)
        logger.info(f"Orchestrator planned service: {plan.service}")
        
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
        
        return plan.service, analysis_steps, response

    async def _handle_meta_report(
        self, request: MetaReportRequest, analysis_steps: list[str]
    ) -> Any:
        """Handle meta report using v2.1 flow."""
        # Step 2: Retrieve
        bundle = await self.retriever.retrieve_meta(request.role, request.patch)
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
        heroes = self.analyzer.analyze_meta_report(bundle.records, request.role)
        analysis_steps.append(f"Analyzer scored {len(heroes)} heroes using weighted formula")
        
        # Step 4: Critic review
        # Collect all evidence from all heroes
        all_evidence = []
        for hero in heroes:
            all_evidence.extend(hero.evidence)
        
        review = self.critic.review_evidence(all_evidence)
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
        
        return response

    async def _handle_patch_impact(
        self, request: PatchImpactRequest, analysis_steps: list[str]
    ) -> Any:
        """Placeholder for patch impact - not implemented in Milestone 1."""
        analysis_steps.append("Patch impact not yet implemented in v2.1")
        raise NotImplementedError("Patch impact not implemented in Milestone 1")

    async def _handle_team_report(
        self, request: TeamReportRequest, analysis_steps: list[str]
    ) -> Any:
        """Placeholder for team report - not implemented in Milestone 1."""
        analysis_steps.append("Team report not yet implemented in v2.1")
        raise NotImplementedError("Team report not implemented in Milestone 1")

    async def _handle_claim_verification(
        self, request: ClaimVerificationRequest, analysis_steps: list[str]
    ) -> Any:
        """Placeholder for claim verification - not implemented in Milestone 1."""
        analysis_steps.append("Claim verification not yet implemented in v2.1")
        raise NotImplementedError("Claim verification not implemented in Milestone 1")
