from dataclasses import dataclass

from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.planner import AgenticPlanner
from app.agentic.registry import ToolExecutor
from app.agentic.runner import PlanRunner
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import get_settings


@dataclass(frozen=True)
class PlanQueryResult:
    query: str
    game: str
    status: str
    reason: str
    plan: ExecutionPlan | None
    tool_results: list[ToolResult]
    evidence_graph: EvidenceGraph | None
    errors: list[str]


class PlanService:
    """Experimental v2.5 LLM planner use case. No fallback to legacy pipeline."""

    def __init__(self, planner: AgenticPlanner | None = None) -> None:
        self.registry = build_default_tool_registry(get_settings())
        self.planner = planner or AgenticPlanner(self.registry)

    async def run(self, query: str, game: str = "dota2") -> PlanQueryResult:
        planning = await self.planner.plan(query, game)
        if planning.status != "planned" or planning.plan is None:
            return PlanQueryResult(
                query=query,
                game=game,
                status=planning.status,
                reason=planning.reason,
                plan=planning.plan,
                tool_results=[],
                evidence_graph=None,
                errors=planning.errors,
            )

        run_result = await PlanRunner(ToolExecutor(self.registry)).run(planning.plan)
        return PlanQueryResult(
            query=query,
            game=game,
            status="ok" if run_result.status == "ok" else "error",
            reason=planning.reason,
            plan=run_result.plan,
            tool_results=run_result.tool_results,
            evidence_graph=run_result.evidence_graph,
            errors=run_result.errors,
        )

