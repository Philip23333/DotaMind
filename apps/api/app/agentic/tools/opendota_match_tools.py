"""Agentic OpenDota tools for one Valve match."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.core.config import Settings, get_policy
from app.integrations.opendota.matches import (
    OpenDotaMatches,
    normalize_match_draft,
    normalize_match_summary,
)
from app.integrations.opendota.transport import OpenDotaTransport


class OpenDotaMatchSummaryInput(BaseModel):
    valve_match_id: int = Field(gt=0)


class OpenDotaMatchDraftInput(BaseModel):
    valve_match_id: int = Field(gt=0)


def register_opendota_match_tools(registry: ToolRegistry, settings: Settings) -> None:
    source = ToolSource(
        name="OpenDota",
        kind="public_api",
        url=settings.opendota_base_url,
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="opendota.match_summary",
            description=(
                "Return the OpenDota result and ten-player scoreboard for a Valve match id."
            ),
            input_model=OpenDotaMatchSummaryInput,
            handler=_summary_handler(settings),
            source=source,
            evidence_extractor=match_summary_evidence,
            evidence_kinds=("match_result", "player_scoreboard", "match_parse_status"),
            mandatory_evidence=("match_result", "player_scoreboard"),
            arg_contracts={
                "valve_match_id": ArgContract(
                    description="Valve match id, literal or PandaScore resolver output.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_match_game",
                            path="data.game.valve_match_id",
                            type="int",
                        ),
                        AcceptedRef(
                            from_tool="dota.resolve_valve_match",
                            path="data.match.valve_match_id",
                            type="int",
                        ),
                    ),
                )
            },
            output_paths={
                "valve_match_id": OutputPathContract(
                    path="data.match.valve_match_id", type="int", description="Valve match id."
                ),
                "match_id": OutputPathContract(
                    path="data.match.match_id",
                    type="int",
                    description="Valve match id compatibility alias.",
                ),
            },
            metadata={"game": "dota2", "domain": "match_summary"},
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.match_draft",
            description="Return OpenDota picks and bans for a Valve match id.",
            input_model=OpenDotaMatchDraftInput,
            handler=_draft_handler(settings),
            source=source,
            evidence_extractor=match_draft_evidence,
            evidence_kinds=("match_draft",),
            mandatory_evidence=("match_draft",),
            arg_contracts={
                "valve_match_id": ArgContract(
                    description="Valve match id from a PandaScore resolver or OpenDota summary.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_match_game",
                            path="data.game.valve_match_id",
                            type="int",
                        ),
                        AcceptedRef(
                            from_tool="dota.resolve_valve_match",
                            path="data.match.valve_match_id",
                            type="int",
                        ),
                        AcceptedRef(
                            from_tool="opendota.match_summary",
                            path="data.match.valve_match_id",
                            type="int",
                        ),
                        AcceptedRef(
                            from_tool="opendota.match_summary",
                            path="data.match.match_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                )
            },
            output_paths={
                "valve_match_id": OutputPathContract(
                    path="data.match.valve_match_id", type="int", description="Valve match id."
                ),
                "match_id": OutputPathContract(
                    path="data.match.match_id",
                    type="int",
                    description="Valve match id compatibility alias.",
                ),
            },
            metadata={"game": "dota2", "domain": "match_draft"},
        )
    )


def _transport(settings: Settings) -> OpenDotaTransport:
    policy = get_policy().opendota
    return OpenDotaTransport(
        settings.opendota_base_url,
        settings.opendota_api_key,
        request_timeout_seconds=policy.request_timeout_seconds,
        default_cache_ttl_seconds=policy.default_cache_ttl_seconds,
    )


def _summary_handler(settings: Settings):
    async def handle(args: OpenDotaMatchSummaryInput, context: QueryContext) -> dict[str, Any]:
        transport = _transport(settings)
        try:
            raw = await OpenDotaMatches(transport).get_match(args.valve_match_id)
            return normalize_match_summary(raw, args.valve_match_id)
        finally:
            await transport.aclose()

    return handle


def _draft_handler(settings: Settings):
    async def handle(args: OpenDotaMatchDraftInput, context: QueryContext) -> dict[str, Any]:
        transport = _transport(settings)
        try:
            raw = await OpenDotaMatches(transport).get_match(args.valve_match_id)
            return normalize_match_draft(raw, args.valve_match_id)
        finally:
            await transport.aclose()

    return handle


def match_summary_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    match_id = data.get("valve_match_id")
    if not isinstance(match_id, int) or match_id <= 0:
        return []
    items: list[EvidenceItem] = []
    if data.get("radiant_win") is not None and data.get("duration") is not None:
        items.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:match_result",
                kind="match_result",
                subject=f"Valve match {match_id}",
                value={
                    key: data.get(key)
                    for key in (
                        "valve_match_id",
                        "start_time",
                        "duration",
                        "radiant_win",
                        "radiant_score",
                        "dire_score",
                        "teams",
                    )
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    players = data.get("players")
    if (
        isinstance(players, list)
        and len(players) == 10
        and all(isinstance(row, dict) for row in players)
    ):
        items.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:player_scoreboard",
                kind="player_scoreboard",
                subject=f"Valve match {match_id} player scoreboard",
                value={"players": players},
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    coverage = data.get("parse_coverage")
    if isinstance(coverage, dict):
        items.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:match_parse_status",
                kind="match_parse_status",
                subject=f"Valve match {match_id} parse coverage",
                value=coverage,
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return items


def match_draft_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    draft = data.get("draft")
    match = data.get("match")
    if not isinstance(draft, list) or not draft or not isinstance(match, dict):
        return []
    rows = [
        row
        for row in draft
        if isinstance(row, dict)
        and row.get("action") in {"pick", "ban"}
        and row.get("team") in {"radiant", "dire"}
        and isinstance(row.get("hero_id"), int)
    ]
    if not rows:
        return []
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:match_draft",
            kind="match_draft",
            subject=f"Valve match {match.get('valve_match_id')} draft",
            value={
                "match": match,
                "draft": rows,
                "draft_timings": data.get("draft_timings", []),
                "coverage": data.get("coverage", {}),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]
