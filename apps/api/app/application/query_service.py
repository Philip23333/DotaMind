from dataclasses import dataclass

from app.domain.reports import ReportResult
from app.domain.tasks import PlannedTask
from app.domain.teams import TeamSelection
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

    async def run(
        self,
        query: str,
        game: str = "dota2",
        team_selection: TeamSelection | None = None,
    ) -> QueryResult:
        if team_selection is None:
            request = await self.orchestrator.plan_query(query, game)
        else:
            request = self.orchestrator.plan_structured(
                "team_report",
                game=game,
                team_name=team_selection.team_name,
                team_id=team_selection.team_id,
                time_range=team_selection.time_range,
            )
        tasks, report = await self.pipeline.run(request)
        return QueryResult(
            query=query,
            routed_service=request.task_type,
            tasks=tasks,
            result=report,
        )

    async def aclose(self) -> None:
        await self.pipeline.aclose()
