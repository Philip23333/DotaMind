from dataclasses import dataclass

from app.core.config import get_policy
from app.domain.evidence import EvidenceItem
from app.domain.reports import ReportResult


@dataclass(frozen=True)
class CriticReview:
    passed: bool
    reasons: list[str]


class CriticAgent:
    """Rule-first critic. This is the single review boundary before formatting."""

    def __init__(self) -> None:
        self.policy = get_policy().critic

    def review_report(self, report: ReportResult) -> CriticReview:
        evidence = self._extract_evidence(report)
        if evidence is None:
            return CriticReview(passed=True, reasons=[])
        return self.review_evidence(evidence)

    def review_evidence(self, evidence: list[EvidenceItem]) -> CriticReview:
        if self.policy.require_evidence and not evidence:
            return CriticReview(False, ["No evidence items were attached."])
        if self.policy.require_evidence and len(evidence) < self.policy.min_evidence_items:
            return CriticReview(
                False,
                [
                    "Insufficient evidence items: "
                    f"expected {self.policy.min_evidence_items}, got {len(evidence)}."
                ],
            )
        if self.policy.reject_unsupported_signals:
            unsupported = [item.signal for item in evidence if item.verdict == "unsupported"]
            if unsupported:
                return CriticReview(
                    False,
                    [f"Unsupported evidence signals: {', '.join(unsupported)}."],
                )
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
