from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan

AgenticCriticSeverity = Literal["pass", "warning", "failed"]


class AgenticCriticReview(BaseModel):
    passed: bool
    severity: AgenticCriticSeverity
    reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgenticCritic:
    """Rule-first quality gate for plan/evidence/answer outputs."""

    hard_min_confidence = 0.35
    min_confidence = 0.5

    def review(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
        answer: AnswerSynthesisResult,
    ) -> AgenticCriticReview:
        issues = []
        issues.extend(self._missing_evidence_issues(graph))
        issues.extend(self._mock_issues(plan, graph))
        issues.extend(self._tool_failure_issues(graph))
        issues.extend(self._answer_status_issues(answer))
        issues.extend(self._confidence_issues(answer))

        failed = [issue for issue in issues if issue["severity"] == "failed"]
        warnings = [issue for issue in issues if issue["severity"] == "warning"]
        metadata = {
            "intent": plan.intent,
            "output_contract": plan.output_contract,
            "answer_status": answer.status,
            "answer_confidence": answer.confidence,
            "missing": graph.missing,
            "mock_used": graph.data_quality.mock_used,
            "tool_result_count": len(graph.tool_results),
            "issue_count": len(issues),
        }
        if failed:
            return AgenticCriticReview(
                passed=False,
                severity="failed",
                reasons=[issue["reason"] for issue in failed],
                metadata=metadata,
            )
        if warnings:
            return AgenticCriticReview(
                passed=True,
                severity="warning",
                reasons=[issue["reason"] for issue in warnings],
                metadata=metadata,
            )
        return AgenticCriticReview(passed=True, severity="pass", metadata=metadata)

    @staticmethod
    def _missing_evidence_issues(graph: EvidenceGraph) -> list[dict[str, str]]:
        if not graph.missing:
            return []
        return [
            {
                "severity": "failed",
                "reason": "Missing required evidence: " + ", ".join(graph.missing),
            }
        ]

    @staticmethod
    def _mock_issues(
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> list[dict[str, str]]:
        if not graph.data_quality.mock_used or plan.constraints.allow_mock:
            return []
        return [
            {
                "severity": "failed",
                "reason": "Mock source used while constraints.allow_mock=false.",
            }
        ]

    @staticmethod
    def _tool_failure_issues(graph: EvidenceGraph) -> list[dict[str, str]]:
        failures = [
            f"{result.tool_call_id}: {result.error or 'tool execution failed'}"
            for result in graph.tool_results
            if result.status == "error"
        ]
        if not failures:
            return []
        return [
            {
                "severity": "failed",
                "reason": "Tool failure was recorded: " + "; ".join(failures),
            }
        ]

    @staticmethod
    def _answer_status_issues(
        answer: AnswerSynthesisResult,
    ) -> list[dict[str, str]]:
        if answer.status == "ok":
            return []
        return [
            {
                "severity": "failed",
                "reason": f"Answer synthesis did not produce an ok answer: {answer.status}.",
            }
        ]

    def _confidence_issues(
        self,
        answer: AnswerSynthesisResult,
    ) -> list[dict[str, str]]:
        if answer.confidence < self.hard_min_confidence:
            return [
                {
                    "severity": "failed",
                    "reason": (
                        f"Answer confidence {answer.confidence:.2f} is below hard "
                        f"minimum {self.hard_min_confidence:.2f}."
                    ),
                }
            ]
        if answer.confidence < self.min_confidence:
            return [
                {
                    "severity": "warning",
                    "reason": (
                        f"Answer confidence {answer.confidence:.2f} is below minimum "
                        f"{self.min_confidence:.2f}."
                    ),
                }
            ]
        return []
