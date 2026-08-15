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


class DotaResolveValveMatchInput(BaseModel):
    competition: dict[str, Any] = Field(min_length=1)
    game_context: dict[str, Any] = Field(min_length=1)


def register_match_resolution_tools(registry: ToolRegistry, settings: Settings) -> None:
    source = ToolSource(
        name="PandaScore + OpenDota",
        kind="cross_source_inference",
        url=f"{settings.pandascore_base_url} + {settings.opendota_base_url}",
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="dota.resolve_valve_match",
            description=(
                "Deterministically infer a Valve match id from PandaScore competition "
                "and game context using OpenDota league, teams, time, duration, game "
                "position, and winner signals."
            ),
            input_model=DotaResolveValveMatchInput,
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
                "game_context": ArgContract(
                    description="Unique PandaScore game context.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_match_game",
                            path="data.resolution_input",
                            type="dict",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "valve_match_id": OutputPathContract(
                    path="data.match.valve_match_id",
                    type="int",
                    description="Inferred Valve match id.",
                ),
                "opendota_league_id": OutputPathContract(
                    path="data.match.opendota_league_id",
                    type="int",
                    description="OpenDota league id used for matching.",
                ),
                "opendota_series_id": OutputPathContract(
                    path="data.match.opendota_series_id",
                    type="int",
                    description="OpenDota series id used for matching.",
                ),
                "mapping": OutputPathContract(
                    path="data.mapping",
                    type="dict",
                    description="Auditable cross-source matching evidence.",
                ),
            },
            metadata={"game": "dota2", "domain": "cross_source_match_resolution"},
        )
    )


def _resolve_handler(settings: Settings):
    async def handle(args: DotaResolveValveMatchInput, context: QueryContext) -> dict[str, Any]:
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
            resolution = await ValveMatchResolver(
                leagues,
                teams,
                start_time_tolerance_seconds=resolver_policy.start_time_tolerance_seconds,
                duration_tolerance_seconds=resolver_policy.duration_tolerance_seconds,
            ).resolve(args.competition, args.game_context)
            return resolution.model_dump(mode="json")
        finally:
            await transport.aclose()

    return handle


def valve_match_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved":
        return []
    match = data.get("match")
    mapping = data.get("mapping")
    if not isinstance(match, dict) or not isinstance(mapping, dict):
        return []
    valve_id = match.get("valve_match_id")
    if not isinstance(valve_id, int) or valve_id <= 0:
        return []
    call_id = result.tool_call_id
    return [
        EvidenceItem(
            id=f"{call_id}:cross_source_match_mapping",
            kind="cross_source_match_mapping",
            subject=f"PandaScore game {mapping.get('pandascore_game_id')} -> Valve {valve_id}",
            value=mapping,
            source=result.source,
            tool_call_id=call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{call_id}:valve_match_identity",
            kind="valve_match_identity",
            subject=f"Valve match {valve_id}",
            value=match,
            source=result.source,
            tool_call_id=call_id,
            tool=result.tool,
        ),
    ]
