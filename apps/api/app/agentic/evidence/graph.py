from typing import Any

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan, ToolResult, ToolSource
from app.agentic.planning.contracts import get_contract
from app.agentic.tools import ToolRegistry


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
    planner_required_evidence: list[str] = Field(default_factory=list)
    global_required_evidence: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    mandatory_evidence_by_call: dict[str, list[str]] = Field(default_factory=dict)
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    data_quality: EvidenceDataQuality


def build_evidence_graph(
    plan: ExecutionPlan,
    tool_results: list[ToolResult],
    registry: ToolRegistry,
    *,
    required_evidence: list[str] | None = None,
    global_required_evidence: list[str] | None = None,
    mandatory_evidence_by_call: dict[str, list[str]] | None = None,
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
    global_required = _global_required_evidence(plan, global_required_evidence)
    mandatory_by_call = _mandatory_evidence_by_call(
        plan,
        registry,
        mandatory_evidence_by_call,
    )
    effective_required = (
        sorted(
            set(global_required).union(
                kind
                for kinds in mandatory_by_call.values()
                for kind in kinds
            )
        )
        if required_evidence is None
        else list(required_evidence)
    )
    for required in global_required:
        if required not in evidence_kinds:
            missing.append(required)

    successful_results = {
        result.tool_call_id: result
        for result in tool_results
        if result.status == "ok"
    }
    evidence_by_call: dict[str, set[str]] = {}
    for item in evidence:
        evidence_by_call.setdefault(item.tool_call_id, set()).add(item.kind)
    for call_id, mandatory_kinds in mandatory_by_call.items():
        if call_id not in successful_results:
            continue
        call_kinds = evidence_by_call.get(call_id, set())
        for required in mandatory_kinds:
            if required not in call_kinds:
                missing.append(f"{call_id}:{required}")

    return EvidenceGraph(
        intent=plan.intent,
        planner_required_evidence=sorted(set(plan.required_evidence)),
        global_required_evidence=global_required,
        required_evidence=effective_required,
        mandatory_evidence_by_call=mandatory_by_call,
        tool_results=tool_results,
        evidence=evidence,
        missing=dedupe_preserve_order(missing),
        data_quality=EvidenceDataQuality(
            mock_used=any(
                result.source is not None and result.source.status == "mocked"
                for result in tool_results
            ),
            min_sample_size=_min_sample_size(evidence),
            completeness=_completeness(
                global_required,
                mandatory_by_call,
                successful_results,
                evidence_kinds,
                evidence_by_call,
            ),
        ),
    )


def _global_required_evidence(
    plan: ExecutionPlan,
    supplied: list[str] | None,
) -> list[str]:
    if supplied is not None:
        return list(supplied)
    required = set(plan.required_evidence)
    contract = get_contract(plan.output_contract)
    if contract is not None:
        required.update(contract.required_evidence)
    return sorted(required)


def _mandatory_evidence_by_call(
    plan: ExecutionPlan,
    registry: ToolRegistry,
    supplied: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    if supplied is not None:
        return {
            call_id: sorted(set(kinds))
            for call_id, kinds in sorted(supplied.items())
        }
    registered = {definition.name for definition in registry.list()}
    result: dict[str, list[str]] = {}
    for call in plan.tool_calls:
        if call.tool not in registered:
            continue
        mandatory = sorted(set(registry.get(call.tool).mandatory_evidence))
        if mandatory:
            result[call.id] = mandatory
    return result


def _min_sample_size(evidence: list[EvidenceItem]) -> int | None:
    samples = [
        int(item.value["sample_size"])
        for item in evidence
        if item.kind == "sample_size" and item.value.get("sample_size") is not None
    ]
    if not samples:
        return None
    return min(samples)


def _completeness(
    global_required: list[str],
    mandatory_by_call: dict[str, list[str]],
    successful_results: dict[str, ToolResult],
    evidence_kinds: set[str],
    evidence_by_call: dict[str, set[str]],
) -> float:
    obligation_count = len(global_required)
    covered = sum(1 for kind in global_required if kind in evidence_kinds)
    for call_id, mandatory_kinds in mandatory_by_call.items():
        if call_id not in successful_results:
            continue
        obligation_count += len(mandatory_kinds)
        call_kinds = evidence_by_call.get(call_id, set())
        covered += sum(1 for kind in mandatory_kinds if kind in call_kinds)
    if obligation_count == 0:
        return 1.0
    return round(covered / obligation_count, 4)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
