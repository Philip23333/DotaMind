from typing import Any

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan, ToolResult, ToolSource


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
) -> EvidenceGraph:
    evidence: list[EvidenceItem] = []
    missing: list[str] = []

    for result in tool_results:
        if result.status != "ok":
            missing.append(f"{result.tool_call_id}: tool_failed")
            continue
        evidence.extend(_evidence_from_tool_result(result))

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


def _evidence_from_tool_result(result: ToolResult) -> list[EvidenceItem]:
    if result.tool == "resolve_hero":
        return _hero_identity_evidence(result)
    if result.tool == "stratz.hero_vs_hero_matchup":
        return _hero_matchup_evidence(result)
    return []


def _hero_identity_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved" or not isinstance(data.get("hero"), dict):
        return []

    hero = data["hero"]
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_identity:{hero.get('hero_id')}",
            kind="hero_identity",
            subject=str(hero.get("localized_name") or hero.get("hero_id")),
            value={
                "hero_id": hero.get("hero_id"),
                "name": hero.get("name"),
                "localized_name": hero.get("localized_name"),
                "aliases": hero.get("aliases", []),
                "method": data.get("method"),
                "query": data.get("query"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def _hero_matchup_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    target_hero_id = data.get("hero_id")
    evidence = []
    for side in ("advantage", "disadvantage"):
        rows = data.get(side, [])
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            match_count = row.get("match_count")
            evidence.append(
                EvidenceItem(
                    id=(
                        f"{result.tool_call_id}:matchup_win_rate:"
                        f"{side}:{row.get('hero_id')}:{index}"
                    ),
                    kind="matchup_win_rate",
                    subject=f"{row.get('hero_id')} vs {target_hero_id}",
                    value={
                        "side": side,
                        "hero_id": row.get("hero_id"),
                        "target_hero_id": row.get("target_hero_id", target_hero_id),
                        "win_rate": row.get("win_rate"),
                        "match_count": match_count,
                        "synergy": row.get("synergy"),
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
            if match_count is not None:
                evidence.append(
                    EvidenceItem(
                        id=(
                            f"{result.tool_call_id}:sample_size:"
                            f"{side}:{row.get('hero_id')}:{index}"
                        ),
                        kind="sample_size",
                        subject=f"{row.get('hero_id')} vs {target_hero_id}",
                        value={
                            "sample_size": match_count,
                            "hero_id": row.get("hero_id"),
                            "target_hero_id": row.get(
                                "target_hero_id",
                                target_hero_id,
                            ),
                        },
                        source=result.source,
                        tool_call_id=result.tool_call_id,
                        tool=result.tool,
                    )
                )
    return evidence


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

