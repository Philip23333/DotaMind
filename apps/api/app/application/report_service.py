from app.domain.reports import ReportResult
from app.domain.tasks import ReportRequest
from app.pipeline.runner import ReportPipeline


class ReportService:
    """Structured report use case used by HTTP, CAP, A2A, and future jobs."""

    def __init__(self) -> None:
        self.pipeline = ReportPipeline()

    async def run(self, request: ReportRequest) -> ReportResult:
        _, report = await self.pipeline.run(request)
        return report

    async def aclose(self) -> None:
        await self.pipeline.aclose()
