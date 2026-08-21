"""Agentic OpenDota tools for Valve match details."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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


class OpenDotaMatchDetailsInput(BaseModel):
    valve_match_ids: list[int] = Field(min_length=1, max_length=5)

    @field_validator("valve_match_ids")
    @classmethod
    def validate_positive_ids(cls, value: list[int]) -> list[int]:
        if any(match_id <= 0 for match_id in value):
            raise ValueError("valve_match_ids must contain positive Valve Match IDs")
        return value


def register_opendota_match_tools(registry: ToolRegistry, settings: Settings) -> None:
    source = ToolSource(
        name="OpenDota",
        kind="public_api",
        url=settings.opendota_base_url,
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="opendota.match_details",
            description=(
                "Return result, ten-player scoreboard, parse coverage, and picks/bans "
                "for up to five Valve match ids. For parsed matches it also returns each "
                "player's complete purchase timeline, inventory/backpack/neutral history, "
                "ability upgrade sequence, and mechanically identified talent selections. "
                "Inputs must be Valve match ids, not PandaScore series, match, or game ids."
            ),
            input_model=OpenDotaMatchDetailsInput,
            handler=_details_handler(settings),
            source=source,
            evidence_extractor=match_details_evidence,
            evidence_kinds=(
                "match_result",
                "player_scoreboard",
                "match_parse_status",
                "match_draft",
                "player_purchase_timeline",
                "player_skill_build",
                "player_talent_selection",
            ),
            mandatory_evidence=("match_result", "player_scoreboard"),
            arg_contracts={
                "valve_match_ids": ArgContract(
                    description="Valve Match IDs only; use the cross-source resolver output.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="dota.resolve_valve_matches",
                            path="data.valve_match_ids",
                            type="list[int]",
                        ),
                    ),
                )
            },
            output_paths={
                "matches": OutputPathContract(
                    path="data.matches",
                    type="list[dict]",
                    description="OpenDota details in Valve match id order.",
                ),
                "valve_match_ids": OutputPathContract(
                    path="data.valve_match_ids",
                    type="list[int]",
                    description="Valve match ids returned by the detail lookup.",
                ),
            },
            metadata={"game": "dota2", "domain": "match_details"},
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


def _details_handler(settings: Settings):
    async def handle(args: OpenDotaMatchDetailsInput, context: QueryContext) -> dict[str, Any]:
        transport = _transport(settings)
        try:
            client = OpenDotaMatches(transport)
            matches = []
            for valve_match_id in args.valve_match_ids:
                raw = await client.get_match(valve_match_id)
                matches.append(
                    {
                        "valve_match_id": valve_match_id,
                        "summary": normalize_match_summary(raw, valve_match_id),
                        "draft": normalize_match_draft(raw, valve_match_id),
                    }
                )
            return {"valve_match_ids": args.valve_match_ids, "matches": matches}
        finally:
            await transport.aclose()

    return handle


_PLAYER_IDENTITY_FIELDS = (
    "name",
    "personaname",
    "player_slot",
    "hero_id",
    "hero_name_en",
    "hero_name_zh",
    "hero_image_path",
    "hero_catalog_status",
)

_PLAYER_SCOREBOARD_FIELDS = (
    *_PLAYER_IDENTITY_FIELDS,
    "level",
    "kills",
    "deaths",
    "assists",
    "last_hits",
    "denies",
    "gpm",
    "xpm",
    "net_worth",
    "hero_damage",
    "tower_damage",
    "hero_healing",
    "final_items",
    "final_item_details",
    "backpack",
    "backpack_item_details",
    "neutral_item",
    "neutral_item_detail",
    "inventory",
)


def _project_fields(
    player: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    return {field: player.get(field) for field in fields}


def _project_scoreboard_player(player: dict[str, Any]) -> dict[str, Any]:
    projected = _project_fields(player, _PLAYER_SCOREBOARD_FIELDS)
    projected["purchase_event_count"] = len(player.get("purchase_timeline") or [])
    projected["ability_upgrade_count"] = len(player.get("ability_upgrade_sequence") or [])
    projected["talent_selection_count"] = len(player.get("talent_selections") or [])
    return projected


def _project_player_progress(
    player: dict[str, Any],
    field: Literal[
        "purchase_timeline",
        "ability_upgrade_sequence",
        "talent_selections",
    ],
) -> dict[str, Any]:
    projected = _project_fields(player, _PLAYER_IDENTITY_FIELDS)
    projected[field] = player.get(field) or []
    return projected


def match_details_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    matches = data.get("matches")
    if not isinstance(matches, list) or not matches:
        return []
    items: list[EvidenceItem] = []
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        match_id = entry.get("valve_match_id")
        summary = entry.get("summary")
        draft_data = entry.get("draft")
        if not isinstance(match_id, int) or not isinstance(summary, dict):
            continue
        if summary.get("radiant_win") is not None and summary.get("duration") is not None:
            items.append(
                EvidenceItem(
                    id=f"{result.tool_call_id}:match_result:{match_id}",
                    kind="match_result",
                    subject=f"Valve match {match_id}",
                    value={
                        key: summary.get(key)
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
        players = summary.get("players")
        if isinstance(players, list) and len(players) == 10 and all(
            isinstance(row, dict) for row in players
        ):
            items.append(
                EvidenceItem(
                    id=f"{result.tool_call_id}:player_scoreboard:{match_id}",
                    kind="player_scoreboard",
                    subject=f"Valve match {match_id} player scoreboard",
                    value={
                        "players": [_project_scoreboard_player(player) for player in players],
                        "catalog_snapshot": summary.get("catalog_snapshot"),
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
        coverage = summary.get("parse_coverage")
        if isinstance(coverage, dict):
            items.append(
                EvidenceItem(
                    id=f"{result.tool_call_id}:match_parse_status:{match_id}",
                    kind="match_parse_status",
                    subject=f"Valve match {match_id} parse coverage",
                    value=coverage,
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
        if isinstance(coverage, dict) and coverage.get("has_parsed") is True:
            for kind, field, label in (
                (
                    "player_purchase_timeline",
                    "purchase_timeline",
                    "player purchase timeline",
                ),
                ("player_skill_build", "ability_upgrade_sequence", "player skill builds"),
                (
                    "player_talent_selection",
                    "talent_selections",
                    "player talent selections",
                ),
            ):
                rows = [
                    _project_player_progress(row, field)
                    for row in players
                    if isinstance(row, dict) and row.get(field)
                ]
                if rows:
                    items.append(
                        EvidenceItem(
                            id=f"{result.tool_call_id}:{kind}:{match_id}",
                            kind=kind,
                            subject=f"Valve match {match_id} {label}",
                            value={
                                "players": rows,
                                "catalog_snapshot": summary.get("catalog_snapshot"),
                            },
                            source=result.source,
                            tool_call_id=result.tool_call_id,
                            tool=result.tool,
                        )
                    )
        draft = draft_data.get("draft") if isinstance(draft_data, dict) else None
        if not isinstance(draft, list):
            continue
        rows = [
            row
            for row in draft
            if isinstance(row, dict)
            and row.get("action") in {"pick", "ban"}
            and row.get("team") in {"radiant", "dire"}
            and isinstance(row.get("hero_id"), int)
        ]
        if rows:
            items.append(
                EvidenceItem(
                    id=f"{result.tool_call_id}:match_draft:{match_id}",
                    kind="match_draft",
                    subject=f"Valve match {match_id} draft",
                    value={
                        "match": {"valve_match_id": match_id, "match_id": match_id},
                        "draft": rows,
                        "draft_timings": draft_data.get("draft_timings", []),
                        "coverage": draft_data.get("coverage", {}),
                        "catalog_snapshot": draft_data.get("catalog_snapshot"),
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
    return items
