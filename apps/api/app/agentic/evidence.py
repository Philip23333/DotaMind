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
    if result.tool == "stratz.lane_outcome":
        return _lane_outcome_evidence(result)
    if result.tool == "opendota.resolve_team":
        return _team_identity_evidence(result)
    if result.tool == "opendota.team_recent_matches":
        return _team_recent_matches_evidence(result)
    if result.tool == "opendota.team_players":
        return _team_players_evidence(result)
    if result.tool == "opendota.team_heroes":
        return _team_heroes_evidence(result)
    if result.tool == "opendota.hero_stats_by_role":
        return _hero_stats_by_role_evidence(result)
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


def _lane_outcome_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    target_hero_id = data.get("hero_id")
    evidence = []
    records = data.get("records", [])
    if not isinstance(records, list):
        return []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            continue
        match_count = row.get("match_count")
        evidence.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:lane_outcome:{row.get('hero_id')}:{index}",
                kind="lane_outcome",
                subject=f"{row.get('hero_id')} with/against {target_hero_id}",
                value={
                    "hero_id": row.get("hero_id"),
                    "target_hero_id": row.get("target_hero_id", target_hero_id),
                    "position": row.get("position"),
                    "match_count": match_count,
                    "match_win_rate": row.get("match_win_rate"),
                    "is_with": data.get("is_with"),
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
        if match_count is not None:
            evidence.append(
                EvidenceItem(
                    id=f"{result.tool_call_id}:sample_size:lane:{row.get('hero_id')}:{index}",
                    kind="sample_size",
                    subject=f"lane sample for {row.get('hero_id')}",
                    value={
                        "sample_size": match_count,
                        "hero_id": row.get("hero_id"),
                        "target_hero_id": row.get("target_hero_id", target_hero_id),
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
    return evidence


def _team_identity_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved" or not isinstance(data.get("team"), dict):
        return []
    team = data["team"]
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:team_identity:{team.get('team_id')}",
            kind="team_identity",
            subject=str(team.get("name") or team.get("team_id")),
            value={
                "team_id": team.get("team_id"),
                "name": team.get("name"),
                "tag": team.get("tag"),
                "rating": team.get("rating"),
                "query": data.get("query"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def _team_recent_matches_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:recent_matches:{data.get('team_id')}",
            kind="recent_matches",
            subject=f"team_id={data.get('team_id')}",
            value={
                "team_id": data.get("team_id"),
                "days": data.get("days"),
                "matches_in_window": data.get("matches_in_window"),
                "wins": data.get("wins"),
                "losses": data.get("losses"),
                "recent_record": data.get("recent_record"),
                "latest_match_time": data.get("latest_match_time"),
                "latest_match_at": data.get("latest_match_at"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:sample_size:matches:{data.get('team_id')}",
            kind="sample_size",
            subject=f"team match window for {data.get('team_id')}",
            value={"sample_size": data.get("matches_in_window")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
    ]


def _team_players_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:current_players:{data.get('team_id')}",
            kind="current_players",
            subject=f"team_id={data.get('team_id')}",
            value={
                "team_id": data.get("team_id"),
                "current_only": data.get("current_only"),
                "player_count": data.get("player_count"),
                "players": data.get("players", []),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def _team_heroes_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:team_hero_usage",
            kind="team_hero_usage",
            subject="team hero usage",
            value={"heroes": data.get("heroes", [])},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:match_detail_sample",
            kind="match_detail_sample",
            subject="team match detail sample",
            value={"match_details_analyzed": data.get("match_details_analyzed")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:sample_size:match_details",
            kind="sample_size",
            subject="team match detail sample size",
            value={"sample_size": data.get("match_details_analyzed")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
    ]


def _hero_stats_by_role_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_stats:{data.get('role')}",
            kind="hero_stats",
            subject=f"role={data.get('role')}",
            value={
                "role": data.get("role"),
                "min_pub_pick": data.get("min_pub_pick"),
                "hero_count": data.get("hero_count"),
                "heroes": data.get("heroes", []),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:role_fit:{data.get('role')}",
            kind="role_fit",
            subject=f"role={data.get('role')}",
            value={"role": data.get("role"), "hero_count": data.get("hero_count")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
    ]


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
