"""Agentic OpenDota tools for Valve match details."""

from __future__ import annotations

from typing import Any

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


class DotaExtractMatchPlayerProgressInput(BaseModel):
    """Select a complete player post-match configuration from normalized data."""

    matches: list[dict[str, Any]] = Field(min_length=1)
    player_query: str = Field(min_length=1)

    @field_validator("player_query")
    @classmethod
    def validate_player_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player_query must not be blank")
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
                "Return core match-detail facts: result, ten-player scoreboard, parse coverage, "
                "and picks/bans for up to five Valve match ids. Player progress is extracted "
                "separately by dota.extract_match_player_progress so the Answer receives only "
                "the requested timeline, skill, or talent data. "
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
    registry.register(
        ToolDefinition(
            name="dota.extract_match_player_progress",
            description=(
                "Deterministically extract a complete player post-match configuration from the "
                "normalized "
                "matches output of opendota.match_details. It performs no network request and "
                "accepts only that tool's data.matches reference. The result includes final "
                "inventory, purchase timeline, ability upgrades, and talent selections."
            ),
            input_model=DotaExtractMatchPlayerProgressInput,
            handler=extract_match_player_progress,
            source=ToolSource(
                name="OpenDota",
                kind="derived",
                url=settings.opendota_base_url,
                status="derived",
            ),
            evidence_extractor=match_player_progress_evidence,
            evidence_kinds=("player_match_progress",),
            arg_contracts={
                "matches": ArgContract(
                    description="Normalized matches from opendota.match_details; no raw JSONPath.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="opendota.match_details",
                            path="data.matches",
                            type="list[dict]",
                        ),
                    ),
                    requires_reference=True,
                )
            },
            output_paths={
                "matches": OutputPathContract(
                    path="data.matches",
                    type="list[dict]",
                    description=(
                        "Complete selected player post-match configurations, one row per "
                        "matching game."
                    ),
                )
            },
            metadata={
                "game": "dota2",
                "domain": "match_player_progress",
                "execution_kind": "deterministic_transform",
            },
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


def _project_final_inventory(player: dict[str, Any]) -> dict[str, Any]:
    inventory = player.get("inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    neutral = inventory.get("neutral")
    neutral = neutral if isinstance(neutral, dict) else {}
    return {
        "main": inventory.get("main") or [],
        "backpack": inventory.get("backpack") or [],
        "neutral": {
            "item": neutral.get("item"),
            "enhancement": neutral.get("enhancement"),
        },
    }


def _project_player_match_progress(player: dict[str, Any]) -> dict[str, Any]:
    """Return the compact complete post-match configuration used by Answer."""

    projected = _project_fields(player, _PLAYER_IDENTITY_FIELDS)
    projected.update(
        {
            "level": player.get("level"),
            "final_inventory": _project_final_inventory(player),
            "purchase_timeline": player.get("purchase_timeline") or [],
            "ability_upgrade_sequence": player.get("ability_upgrade_sequence") or [],
            "talent_selections": player.get("talent_selections") or [],
        }
    )
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


def extract_match_player_progress(
    args: DotaExtractMatchPlayerProgressInput,
    context: QueryContext,
) -> dict[str, Any]:
    """Project complete player post-match configurations from normalized match rows."""

    del context
    query = args.player_query.casefold()
    selected: list[dict[str, Any]] = []
    for entry in args.matches:
        match_id = entry.get("valve_match_id")
        summary = entry.get("summary")
        if not isinstance(match_id, int) or not isinstance(summary, dict):
            raise ValueError("matches must contain normalized Valve match summaries")
        coverage = summary.get("parse_coverage")
        if not isinstance(coverage, dict) or coverage.get("has_parsed") is not True:
            raise ValueError(f"Valve match {match_id} has no parsed player progress")
        players = summary.get("players")
        if not isinstance(players, list):
            raise ValueError(f"Valve match {match_id} has no normalized players")
        matching_players = [
            player
            for player in players
            if isinstance(player, dict)
            and query
            in {
                str(player.get("name") or "").casefold(),
                str(player.get("personaname") or "").casefold(),
            }
        ]
        if len(matching_players) != 1:
            raise ValueError(
                f"player_query {args.player_query!r} matched {len(matching_players)} "
                f"players in Valve match {match_id}"
            )
        for player in matching_players:
            selected.append(
                {
                    "valve_match_id": match_id,
                    "player": _project_player_match_progress(player),
                    "catalog_snapshot": summary.get("catalog_snapshot"),
                }
            )
    if not selected:
        raise ValueError(f"player_query {args.player_query!r} was not found in parsed matches")
    return {
        "status": "resolved",
        "player_query": args.player_query,
        "matches": selected,
    }


def match_player_progress_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    rows = data.get("matches")
    if not isinstance(rows, list):
        return []
    items: list[EvidenceItem] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("valve_match_id"), int):
            continue
        match_id = row["valve_match_id"]
        identity = row.get("player")
        if not isinstance(identity, dict):
            continue
        player_name = identity.get("name") or identity.get("personaname") or "unknown"
        items.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:player_match_progress:{match_id}:{player_name}",
                kind="player_match_progress",
                subject=f"Valve match {match_id} {player_name} post-match configuration",
                value={
                    "match": {"valve_match_id": match_id, "match_id": match_id},
                    "players": [identity],
                    "catalog_snapshot": row.get("catalog_snapshot"),
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return items
