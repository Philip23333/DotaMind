from typing import Any

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan, ToolResult, ToolSource
from app.agentic.registry import ToolRegistry


class EvidenceItem(BaseModel):
    id: str
    kind: str
    subject: str
    value: dict[str, Any]
    source: ToolSource | None = None
    tool_call_id: str
    tool: str


class EvidenceDataQuality(BaseModel):
    mock_used: bool = False
    min_sample_size: int | None = None
    completeness: float = Field(ge=0, le=1)


class EvidenceGraph(BaseModel):
    intent: str
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    data_quality: EvidenceDataQuality


def build_evidence_graph(
    plan: ExecutionPlan,
    tool_results: list[ToolResult],
    registry: ToolRegistry,
) -> EvidenceGraph:
    evidence: list[EvidenceItem] = []
    missing: list[str] = []

    for result in tool_results:
        if result.status != "ok":
            missing.append(f"{result.tool_call_id}: tool_failed")
            continue
        try:
            definition = registry.get(result.tool)
        except KeyError:
            missing.append(f"{result.tool_call_id}: unknown_tool")
            continue
        if definition.evidence_extractor is None:
            continue
        try:
            evidence.extend(definition.evidence_extractor(result))
        except Exception as exc:
            missing.append(
                f"{result.tool_call_id}: evidence_extractor_failed: "
                f"{type(exc).__name__}: {exc}"
            )

    evidence_kinds = {item.kind for item in evidence}
    for required in plan.required_evidence:
        if required not in evidence_kinds:
            missing.append(required)

    return EvidenceGraph(
        intent=plan.intent,
        tool_results=tool_results,
        evidence=evidence,
        missing=dedupe_preserve_order(missing),
        data_quality=EvidenceDataQuality(
            mock_used=any(
                result.source is not None and result.source.status == "mocked"
                for result in tool_results
            ),
            min_sample_size=_min_sample_size(evidence),
            completeness=_completeness(plan.required_evidence, evidence_kinds),
        ),
    )


def _min_sample_size(evidence: list[EvidenceItem]) -> int | None:
    samples = [
        int(item.value["sample_size"])
        for item in evidence
        if item.kind == "sample_size" and item.value.get("sample_size") is not None
    ]
    if not samples:
        return None
    return min(samples)


def _completeness(required_evidence: list[str], evidence_kinds: set[str]) -> float:
    if not required_evidence:
        return 1.0
    covered = sum(1 for kind in required_evidence if kind in evidence_kinds)
    return round(covered / len(required_evidence), 4)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
