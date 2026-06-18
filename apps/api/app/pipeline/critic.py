from dataclasses import dataclass

from app.domain.evidence import EvidenceItem
from app.domain.reports import ReportResult


@dataclass(frozen=True)
class CriticReview:
    passed: bool
    reasons: list[str]


class CriticAgent:
    """Rule-first critic. This is the single review boundary before formatting."""

    def review_report(self, report: ReportResult) -> CriticReview:
        evidence = self._extract_evidence(report)
        if evidence is None:
            return CriticReview(passed=True, reasons=[])
        return self.review_evidence(evidence)

    def review_evidence(self, evidence: list[EvidenceItem]) -> CriticReview:
        if not evidence:
            return CriticReview(False, ["No evidence items were attached."])
        unsupported = [item.signal for item in evidence if item.verdict == "unsupported"]
        if unsupported:
            return CriticReview(False, [f"Unsupported evidence signals: {', '.join(unsupported)}."])
        return CriticReview(True, [])

    @staticmethod
    def _extract_evidence(report: ReportResult) -> list[EvidenceItem] | None:
        if report.report_type == "meta_report":
            evidence = []
            for hero in report.top_heroes:
                evidence.extend(hero.evidence)
            return evidence
        if report.report_type == "claim_verification":
            return report.evidence
        return None
