from app.domain.evidence import Source
from app.domain.reports import MetaReport, ReportResult
from app.domain.tasks import ReportRequest


class FormatterTool:
    """Final deterministic response shaping."""

    def format_meta(
        self, request: ReportRequest, heroes, source_names: list[str], analysis_steps: list[str]
    ) -> MetaReport:
        confidence = (
            round(sum(hero.confidence for hero in heroes) / len(heroes), 2) if heroes else 0.0
        )
        role = request.role or "offlane"
        summary = (
            f"{role} report ranks {len(heroes)} heroes by evidence-backed meta signals."
        )
        return MetaReport(
            report_type="meta_report",
            game=request.game,
            patch=request.patch,
            role=role,
            summary=summary,
            top_heroes=heroes,
            sources=self.sources(source_names),
            analysis_steps=analysis_steps,
            confidence=confidence,
        )

    def attach_sources(self, report: ReportResult, source_names: list[str]) -> ReportResult:
        sources = self.sources(source_names)
        if report.report_type == "patch_impact":
            return report.__class__(**{**report.__dict__, "sources": sources})
        if report.report_type == "team_report":
            return report.__class__(**{**report.__dict__, "sources": sources})
        return report

    @staticmethod
    def sources(source_names: list[str]) -> list[Source]:
        result = []
        if "opendota" in source_names:
            result.append(Source("OpenDota", "public_api", "https://docs.opendota.com/", "live"))
        if "patch_json" in source_names:
            result.append(
                Source(
                    "Dota2 Patch Notes",
                    "local_patch_json",
                    "https://www.dota2.com/patches/",
                    "loaded",
                )
            )
        if "mock" in source_names:
            result.append(Source("MetaMind Fixtures", "fixture", None, "mocked"))
        if "rules" in source_names:
            result.append(Source("MetaMind Rules", "deterministic_rules", None, "local"))
        return result or [Source("MetaMind", "internal", None, "local")]
