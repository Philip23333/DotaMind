from typing import Literal

from app.api.v1.schemas import EvidenceItem, Verdict

TaskType = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


class AnalyzerAgent:
    """Single analysis boundary for future LLM-backed claim generation."""

    def confidence_bucket(self, confidence: float) -> Literal["high", "medium", "low", "none"]:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.5:
            return "medium"
        if confidence > 0:
            return "low"
        return "none"

    def weakest_verdict(self, evidence: list[EvidenceItem]) -> Verdict:
        order: dict[Verdict, int] = {
            "unsupported": 0,
            "weakly_supported": 1,
            "partially_supported": 2,
            "supported": 3,
        }
        if not evidence:
            return "unsupported"
        return min((item.verdict for item in evidence), key=lambda verdict: order[verdict])
