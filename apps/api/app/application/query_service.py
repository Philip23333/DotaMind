from dataclasses import dataclass

from app.domain.reports import ReportResult
from app.domain.tasks import PlannedTask
from app.pipeline.orchestrator import OrchestratorAgent
from app.pipeline.runner import ReportPipeline


@dataclass(frozen=True)
class QueryResult:
    query: str
    routed_service: str
    tasks: list[PlannedTask]
    result: ReportResult


class QueryService:
    """Natural-language query use case."""

    def __init__(self) -> None:
        self.orchestrator = OrchestratorAgent()
        self.pipeline = ReportPipeline()

    async def run(self, query: str, game: str = "dota2") -> QueryResult:
        request = await self.orchestrator.plan_query(query, game)
        tasks, report = await self.pipeline.run(request)
        return QueryResult(
            query=query,
            routed_service=request.task_type,
            tasks=tasks,
            result=report,
        )

    async def aclose(self) -> None:
        await self.pipeline.aclose()
