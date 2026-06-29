import time
from typing import Any

from pydantic import BaseModel, Field

from app.agentic.models import ToolSource
from app.agentic.registry import ToolDefinition, ToolRegistry
from app.core.config import Settings, get_policy
from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.teams import OpenDotaTeams
from app.integrations.opendota.transport import OpenDotaTransport
from app.pipeline.retriever import RetrieverTool


class OpenDotaResolveTeamInput(BaseModel):
    query: str = Field(min_length=1)


class OpenDotaTeamRecentMatchesInput(BaseModel):
    team_id: int = Field(gt=0)
    days: int = Field(default=30, ge=0)


class OpenDotaTeamPlayersInput(BaseModel):
    team_id: int = Field(gt=0)
    current_only: bool = True


class OpenDotaTeamHeroesInput(BaseModel):
    matches: list[dict[str, Any]] = Field(default_factory=list)
    detail_sample_size: int | None = Field(default=None, ge=1, le=100)


class OpenDotaHeroStatsByRoleInput(BaseModel):
    role: str = Field(min_length=1)
    min_pub_pick: int = Field(default=100, ge=0)


def register_opendota_tools(registry: ToolRegistry, settings: Settings) -> None:
    source = ToolSource(
        name="OpenDota",
        kind="public_api",
        url=settings.opendota_base_url,
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="opendota.resolve_team",
            description="Resolve a Dota 2 pro team query to OpenDota team candidates.",
            input_model=OpenDotaResolveTeamInput,
            handler=_resolve_team_handler(settings),
            source=source,
            metadata={"game": "dota2", "domain": "team_identity"},
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.team_recent_matches",
            description="Return OpenDota team matches inside a requested time window.",
            input_model=OpenDotaTeamRecentMatchesInput,
            handler=_team_recent_matches_handler(settings),
            source=source,
            metadata={"game": "dota2", "domain": "team_matches"},
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.team_players",
            description="Return OpenDota team players, optionally current roster only.",
            input_model=OpenDotaTeamPlayersInput,
            handler=_team_players_handler(settings),
            source=source,
            metadata={"game": "dota2", "domain": "team_players"},
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.team_heroes",
            description="Aggregate hero usage from OpenDota match detail samples.",
            input_model=OpenDotaTeamHeroesInput,
            handler=_team_heroes_handler(settings),
            source=source,
            metadata={"game": "dota2", "domain": "team_heroes"},
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.hero_stats_by_role",
            description="Return OpenDota hero stats filtered by inferred role.",
            input_model=OpenDotaHeroStatsByRoleInput,
            handler=_hero_stats_by_role_handler(settings),
            source=source,
            metadata={"game": "dota2", "domain": "hero_meta"},
        )
    )


def _resolve_team_handler(settings: Settings):
    async def handle(args: OpenDotaResolveTeamInput) -> dict[str, Any]:
        transport, _heroes, teams = _clients(settings)
        try:
            all_teams = await teams.get_all()
            resolution = RetrieverTool.resolve_team(args.query, all_teams)
            return {
                "status": resolution.status,
                "query": args.query,
                "team": resolution.team,
                "candidates": resolution.candidates,
            }
        finally:
            await transport.aclose()

    return handle


def _team_recent_matches_handler(settings: Settings):
    async def handle(args: OpenDotaTeamRecentMatchesInput) -> dict[str, Any]:
        transport, _heroes, teams = _clients(settings)
        try:
            cache_before = transport.cache_stats()
            all_matches = await teams.get_matches(args.team_id)
            cutoff = time.time() - args.days * 86400 if args.days > 0 else None
            matches = [
                match
                for match in all_matches
                if cutoff is None or match.get("start_time", 0) >= cutoff
            ]
            matches.sort(
                key=lambda match: int(match.get("start_time") or 0),
                reverse=True,
            )
            wins = sum(1 for match in matches if OpenDotaTeams._is_team_win(match))
            latest_match_time = OpenDotaTeams._latest_match_time(matches)
            cache_after = transport.cache_stats()
            return {
                "team_id": args.team_id,
                "days": args.days,
                "matches": matches,
                "matches_in_window": len(matches),
                "wins": wins,
                "losses": len(matches) - wins,
                "recent_record": f"{wins}-{len(matches) - wins} in last {len(matches)} matches",
                "latest_match_time": latest_match_time,
                "latest_match_at": OpenDotaTeams._format_timestamp(latest_match_time),
                "opendota_cache_hits": max(0, cache_after["hits"] - cache_before["hits"]),
                "opendota_cache_misses": max(
                    0,
                    cache_after["misses"] - cache_before["misses"],
                ),
            }
        finally:
            await transport.aclose()

    return handle


def _team_players_handler(settings: Settings):
    async def handle(args: OpenDotaTeamPlayersInput) -> dict[str, Any]:
        transport, _heroes, teams = _clients(settings)
        try:
            players = await teams.get_players(args.team_id)
            if args.current_only:
                players = [
                    player
                    for player in players
                    if player.get("is_current_team_member") is True
                ]
            return {
                "team_id": args.team_id,
                "current_only": args.current_only,
                "players": players,
                "player_count": len(players),
            }
        finally:
            await transport.aclose()

    return handle


def _team_heroes_handler(settings: Settings):
    async def handle(args: OpenDotaTeamHeroesInput) -> dict[str, Any]:
        transport, _heroes, teams = _clients(settings)
        try:
            sample_size = args.detail_sample_size or teams.detail_sample_size
            detail_matches = args.matches[: min(sample_size, teams.max_detail_sample_size)]
            heroes = await teams.aggregate_heroes(detail_matches)
            return {
                "heroes": heroes,
                "match_details_analyzed": len(detail_matches),
            }
        finally:
            await transport.aclose()

    return handle


def _hero_stats_by_role_handler(settings: Settings):
    async def handle(args: OpenDotaHeroStatsByRoleInput) -> dict[str, Any]:
        transport, heroes, _teams = _clients(settings)
        try:
            records = await heroes.get_stats_for_role(
                args.role,
                min_pub_pick=args.min_pub_pick,
            )
            return {
                "role": args.role,
                "min_pub_pick": args.min_pub_pick,
                "heroes": records,
                "hero_count": len(records),
            }
        finally:
            await transport.aclose()

    return handle


def _clients(settings: Settings) -> tuple[OpenDotaTransport, OpenDotaHeroes, OpenDotaTeams]:
    policy = get_policy()
    transport = OpenDotaTransport(
        settings.opendota_base_url,
        settings.opendota_api_key,
        request_timeout_seconds=policy.opendota.request_timeout_seconds,
        default_cache_ttl_seconds=policy.opendota.default_cache_ttl_seconds,
    )
    heroes = OpenDotaHeroes(transport)
    match_details = policy.team_report.match_details
    teams = OpenDotaTeams(
        transport,
        heroes,
        detail_sample_size=match_details.default_sample_size,
        max_detail_sample_size=match_details.max_sample_size,
        detail_concurrency=match_details.concurrency,
        match_detail_cache_ttl_seconds=match_details.cache_ttl_seconds,
    )
    return transport, heroes, teams
