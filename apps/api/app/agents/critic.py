from dataclasses import dataclass

from app.api.v1.schemas import EvidenceItem


@dataclass(frozen=True)
class CriticReview:
    passed: bool
    reasons: list[str]


class CriticAgent:
    """Rule-first critic boundary for v2.1 evidence review."""

    def review_evidence(self, evidence: list[EvidenceItem]) -> CriticReview:
        if not evidence:
            return CriticReview(passed=False, reasons=["No evidence items were attached."])

        unsupported = [item.signal for item in evidence if item.verdict == "unsupported"]
        if unsupported:
            return CriticReview(
                passed=False,
                reasons=[f"Unsupported evidence signals: {', '.join(unsupported)}."],
            )

        return CriticReview(passed=True, reasons=[])
