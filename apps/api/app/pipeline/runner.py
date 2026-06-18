from app.domain.reports import ReportResult
from app.domain.tasks import PlannedTask, ReportRequest
from app.pipeline.analyzer import AnalyzerAgent
from app.pipeline.critic import CriticAgent
from app.pipeline.formatter import FormatterTool
from app.pipeline.retriever import RetrieverTool


class ReportPipeline:
    """Canonical Orchestrator -> Retriever -> Analyzer -> Critic -> Formatter runner."""

    def __init__(self) -> None:
        self.retriever = RetrieverTool()
        self.analyzer = AnalyzerAgent()
        self.critic = CriticAgent()
        self.formatter = FormatterTool()

    async def run(self, request: ReportRequest) -> tuple[list[PlannedTask], ReportResult]:
        trace = list(request.trace)

        if request.task_type == "meta_report":
            role = request.role or "offlane"
            trace.append(PlannedTask("retriever", f"retrieve {role} hero evidence"))
            bundle = await self.retriever.retrieve_meta(role, request.patch)
            trace.append(PlannedTask("analyzer", "rank hero recommendations"))
            heroes = await self.analyzer.analyze_meta(bundle, role)
            report = self.formatter.format_meta(
                request,
                heroes,
                bundle.sources,
                [task.action for task in trace],
            )
        elif request.task_type == "patch_impact":
            trace.append(PlannedTask("retriever", f"retrieve patch evidence for {request.patch}"))
            bundle = await self.retriever.retrieve_patch(request.patch)
            patch = str(bundle.query.get("patch", request.patch))
            trace.append(PlannedTask("analyzer", "derive patch winners and losers"))
            report = self.analyzer.analyze_patch(bundle, request.game, patch)
            report = self.formatter.attach_sources(report, bundle.sources)
        elif request.task_type == "team_report":
            team_name = request.team_name or "Team Spirit"
            trace.append(PlannedTask("retriever", f"retrieve team evidence for {team_name}"))
            bundle = await self.retriever.retrieve_team(team_name, request.time_range)
            trace.append(PlannedTask("analyzer", "derive team intelligence report"))
            report = self.analyzer.analyze_team(bundle, request.game, team_name, request.time_range)
            report = self.formatter.attach_sources(report, bundle.sources)
        else:
            claim = request.claim or request.query or ""
            trace.append(PlannedTask("retriever", "retrieve claim evidence"))
            bundle = await self.retriever.retrieve_claim(claim, request.game)
            trace.append(PlannedTask("analyzer", "assign claim verdict"))
            report = self.analyzer.analyze_claim(bundle, request.game, claim)

        review = self.critic.review_report(report)
        trace.append(
            PlannedTask(
                "critic",
                "approve report"
                if review.passed
                else f"reject report: {', '.join(review.reasons)}",
                "completed" if review.passed else "warning",
            )
        )
        trace.append(PlannedTask("formatter", "format public response"))
        return trace, report
