"""Agentic cross-source PandaScore -> Valve match resolver."""

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
from app.integrations.match_resolution.valve_match_resolver import ValveMatchResolver
from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.leagues import OpenDotaLeagues
from app.integrations.opendota.teams import OpenDotaTeams
from app.integrations.opendota.transport import OpenDotaTransport


class DotaResolveValveMatchesInput(BaseModel):
    competition: dict[str, Any] = Field(min_length=1)
    game_contexts: list[dict[str, Any]] = Field(min_length=1, max_length=5)


def register_match_resolution_tools(registry: ToolRegistry, settings: Settings) -> None:
    source = ToolSource(
        name="PandaScore + OpenDota",
        kind="cross_source_inference",
        url=f"{settings.pandascore_base_url} + {settings.opendota_base_url}",
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="dota.resolve_valve_matches",
            description=(
                "Deterministically infer Valve match ids for PandaScore game contexts "
                "using OpenDota league, teams, time, duration, game position, and "
                "winner signals."
            ),
            input_model=DotaResolveValveMatchesInput,
            handler=_resolve_handler(settings),
            source=source,
            evidence_extractor=valve_match_evidence,
            evidence_kinds=("cross_source_match_mapping", "valve_match_identity"),
            mandatory_evidence=("cross_source_match_mapping", "valve_match_identity"),
            arg_contracts={
                "competition": ArgContract(
                    description="Resolved PandaScore competition context.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_competition",
                            path="data.competition",
                            type="dict",
                        ),
                    ),
                    requires_reference=True,
                ),
                "game_contexts": ArgContract(
                    description="Unique PandaScore game contexts.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_match_games",
                            path="data.resolution_inputs",
                            type="list[dict]",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "valve_match_ids": OutputPathContract(
                    path="data.valve_match_ids",
                    type="list[int]",
                    description="Inferred Valve match ids in game order.",
                ),
                "matches": OutputPathContract(
                    path="data.matches",
                    type="list[dict]",
                    description="Resolved Valve match rows in game order.",
                ),
                "mappings": OutputPathContract(
                    path="data.mappings",
                    type="list[dict]",
                    description="Auditable cross-source matching evidence in game order.",
                ),
            },
            metadata={"game": "dota2", "domain": "cross_source_match_resolution"},
        )
    )


def _resolve_handler(settings: Settings):
    async def handle(args: DotaResolveValveMatchesInput, context: QueryContext) -> dict[str, Any]:
        policy = get_policy()
        transport = OpenDotaTransport(
            settings.opendota_base_url,
            settings.opendota_api_key,
            request_timeout_seconds=policy.opendota.request_timeout_seconds,
            default_cache_ttl_seconds=policy.opendota.default_cache_ttl_seconds,
        )
        try:
            leagues = OpenDotaLeagues(transport)
            teams = OpenDotaTeams(transport, OpenDotaHeroes(transport))
            resolver_policy = policy.cross_source_match_resolution
            resolver = ValveMatchResolver(
                leagues,
                teams,
                start_time_tolerance_seconds=resolver_policy.start_time_tolerance_seconds,
                duration_tolerance_seconds=resolver_policy.duration_tolerance_seconds,
            )
            resolutions = [
                await resolver.resolve(args.competition, game_context)
                for game_context in args.game_contexts
            ]
            data = {
                "status": "resolved"
                if all(item.status == "resolved" for item in resolutions)
                else next(item.status for item in resolutions if item.status != "resolved"),
                "resolutions": [item.model_dump(mode="json") for item in resolutions],
            }
            if data["status"] != "resolved":
                data["valve_match_ids"] = []
                data["matches"] = []
                data["mappings"] = []
                return data
            data["matches"] = [
                item.match.model_dump(mode="json") for item in resolutions if item.match
            ]
            data["valve_match_ids"] = [
                item.match.valve_match_id for item in resolutions if item.match
            ]
            data["mappings"] = [
                item.mapping.model_dump(mode="json") for item in resolutions if item.mapping
            ]
            return data
        finally:
            await transport.aclose()

    return handle


def valve_match_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved":
        return []
    matches = data.get("matches")
    mappings = data.get("mappings")
    if not isinstance(matches, list) or not isinstance(mappings, list):
        return []
    if len(matches) != len(mappings):
        return []
    items: list[EvidenceItem] = []
    call_id = result.tool_call_id
    for match, mapping in zip(matches, mappings, strict=True):
        if not isinstance(match, dict) or not isinstance(mapping, dict):
            return []
        valve_id = match.get("valve_match_id")
        if not isinstance(valve_id, int) or valve_id <= 0:
            return []
        game_id = mapping.get("pandascore_game_id")
        items.extend(
            [
                EvidenceItem(
                    id=f"{call_id}:cross_source_match_mapping:{game_id}",
                    kind="cross_source_match_mapping",
                    subject=f"PandaScore game {game_id} -> Valve {valve_id}",
                    value=mapping,
                    source=result.source,
                    tool_call_id=call_id,
                    tool=result.tool,
                ),
                EvidenceItem(
                    id=f"{call_id}:valve_match_identity:{valve_id}",
                    kind="valve_match_identity",
                    subject=f"Valve match {valve_id}",
                    value=match,
                    source=result.source,
                    tool_call_id=call_id,
                    tool=result.tool,
                ),
            ]
        )
    return items
