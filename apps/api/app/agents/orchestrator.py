from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.api.v1.schemas import (
    ClaimVerificationRequest,
    MetaReportRequest,
    NaturalLanguageQueryRequest,
    PatchImpactRequest,
    PlannedTask,
    TeamReportRequest,
)

ServiceName = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


@dataclass(frozen=True)
class OrchestrationPlan:
    service: ServiceName
    tasks: list[PlannedTask]
    request: MetaReportRequest | PatchImpactRequest | TeamReportRequest | ClaimVerificationRequest


class OrchestratorAgent:
    """Routes a user query and coordinates the deterministic MVP tools/services."""

    def plan(self, request: NaturalLanguageQueryRequest) -> OrchestrationPlan:
        normalized = request.query.lower()

        if "team" in normalized or "spirit" in normalized or "falcons" in normalized:
            return OrchestrationPlan(
                service="team_report",
                tasks=[
                    PlannedTask(agent="orchestrator", action="detect team-analysis intent"),
                    PlannedTask(
                        agent="retriever",
                        action="collect recent pro match and draft signals",
                    ),
                    PlannedTask(agent="analyzer", action="score patch adaptation"),
                    PlannedTask(agent="critic", action="review evidence coverage"),
                    PlannedTask(agent="formatter", action="format team intelligence report"),
                ],
                request=TeamReportRequest(game=request.game, team_name="Team Spirit"),
            )

        if "patch" in normalized or "7." in normalized or "impact" in normalized:
            return OrchestrationPlan(
                service="patch_impact",
                tasks=[
                    PlannedTask(agent="orchestrator", action="detect patch-impact intent"),
                    PlannedTask(agent="retriever", action="load hero, item, and mechanic changes"),
                    PlannedTask(agent="analyzer", action="derive winners, losers, and trends"),
                    PlannedTask(agent="critic", action="review patch evidence coverage"),
                    PlannedTask(agent="formatter", action="format patch impact report"),
                ],
                request=PatchImpactRequest(game=request.game, patch="latest"),
            )

        if "verify" in normalized or "claim" in normalized or "supported" in normalized:
            return OrchestrationPlan(
                service="claim_verification",
                tasks=[
                    PlannedTask(agent="orchestrator", action="detect verification intent"),
                    PlannedTask(agent="retriever", action="collect matching evidence signals"),
                    PlannedTask(agent="analyzer", action="assign provisional verdict"),
                    PlannedTask(agent="critic", action="reject unsupported evidence gaps"),
                    PlannedTask(agent="formatter", action="format verification result"),
                ],
                request=ClaimVerificationRequest(game=request.game, claim=request.query),
            )

        return OrchestrationPlan(
            service="meta_report",
            tasks=[
                PlannedTask(agent="orchestrator", action="detect hero-meta intent"),
                PlannedTask(agent="retriever", action="collect role hero metrics"),
                PlannedTask(agent="analyzer", action="rank hero recommendations"),
                PlannedTask(agent="critic", action="review recommendation evidence"),
                PlannedTask(agent="formatter", action="format ranked recommendations"),
            ],
            request=MetaReportRequest(game=request.game, patch="latest", role="offlane"),
        )

    async def run(
        self,
        request: NaturalLanguageQueryRequest,
        handlers: dict[ServiceName, Callable[[Any], Awaitable[Any]]],
    ) -> tuple[OrchestrationPlan, Any]:
        plan = self.plan(request)
        result = await handlers[plan.service](plan.request)
        return plan, result
