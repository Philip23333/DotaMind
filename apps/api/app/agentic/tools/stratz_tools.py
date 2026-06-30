from typing import Any

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import ToolResult, ToolSource
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.agentic.tools.hero_tools import load_default_hero_resolver
from app.core.config import Settings
from app.integrations.stratz.heroes import StratzHeroes
from app.integrations.stratz.transport import StratzTransport


class StratzHeroVsHeroMatchupInput(BaseModel):
    hero_id: int = Field(gt=0)
    take: int = Field(default=10, ge=1, le=50)
    week: int | None = Field(default=None, ge=0)
    bracket_basic_ids: list[str] | None = None
    match_limit: int | None = Field(default=None, ge=1)


class StratzLaneOutcomeInput(BaseModel):
    hero_id: int = Field(gt=0)
    is_with: bool
    week: int | None = Field(default=None, ge=0)
    bracket_basic_ids: list[str] | None = None
    position_ids: list[str] | None = None


class ResolveHeroInput(BaseModel):
    query: str = Field(min_length=1)


def register_stratz_tools(registry: ToolRegistry, settings: Settings) -> None:
    registry.register(
        ToolDefinition(
            name="resolve_hero",
            description="Resolve a Dota 2 hero name or alias to a canonical hero id.",
            input_model=ResolveHeroInput,
            handler=_resolve_hero_handler,
            source=ToolSource(
                name="Local Dota 2 hero constants",
                kind="local_constants",
                url=None,
                status="live",
            ),
            evidence_extractor=resolve_hero_evidence,
            evidence_kinds=("hero_identity",),
            arg_contracts={
                "query": ArgContract(description="Hero name or alias to resolve."),
            },
            output_paths={
                "hero_id": OutputPathContract(
                    path="data.hero.hero_id",
                    type="int",
                    description="Canonical Dota 2 hero id.",
                ),
            },
            metadata={"game": "dota2", "domain": "hero_identity"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_vs_hero_matchup",
            description="Return STRATZ hero-vs-hero matchup advantage and disadvantage data.",
            input_model=StratzHeroVsHeroMatchupInput,
            handler=_hero_vs_hero_matchup_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=hero_matchup_evidence,
            evidence_kinds=("matchup_win_rate", "sample_size"),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Target hero id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                ),
                "take": ArgContract(description="Maximum matchup rows to return."),
                "week": ArgContract(description="STRATZ week filter."),
                "bracket_basic_ids": ArgContract(description="STRATZ bracket filters."),
                "match_limit": ArgContract(description="Maximum source matches to scan."),
            },
            metadata={"game": "dota2", "domain": "hero_matchup"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.lane_outcome",
            description="Return STRATZ lane outcome records for with/against hero context.",
            input_model=StratzLaneOutcomeInput,
            handler=_lane_outcome_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=lane_outcome_evidence,
            evidence_kinds=("lane_outcome", "sample_size"),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Target hero id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                ),
                "is_with": ArgContract(
                    description=(
                        "true for lane partners with this hero; false for lane "
                        "opponents against this hero."
                    ),
                ),
                "week": ArgContract(description="STRATZ week filter."),
                "bracket_basic_ids": ArgContract(description="STRATZ bracket filters."),
                "position_ids": ArgContract(description="Lane position filters."),
            },
            metadata={"game": "dota2", "domain": "lane_outcome"},
        )
    )


def build_default_tool_registry(settings: Settings) -> ToolRegistry:
    from app.agentic.tools.opendota_tools import register_opendota_tools
    from app.agentic.tools.patch_tools import register_patch_tools

    registry = ToolRegistry()
    register_stratz_tools(registry, settings)
    register_opendota_tools(registry, settings)
    register_patch_tools(registry)
    return registry


def _resolve_hero_handler(args: ResolveHeroInput) -> dict[str, Any]:
    return load_default_hero_resolver().resolve(args.query)


def resolve_hero_evidence(result: ToolResult) -> list[EvidenceItem]:
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


def hero_matchup_evidence(result: ToolResult) -> list[EvidenceItem]:
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


def lane_outcome_evidence(result: ToolResult) -> list[EvidenceItem]:
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


def _hero_vs_hero_matchup_handler(settings: Settings):
    async def handle(args: StratzHeroVsHeroMatchupInput) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            return await heroes.hero_vs_hero_matchup(
                args.hero_id,
                take=args.take,
                week=args.week,
                bracket_basic_ids=args.bracket_basic_ids,
                match_limit=args.match_limit,
            )
        finally:
            await transport.aclose()

    return handle


def _lane_outcome_handler(settings: Settings):
    async def handle(args: StratzLaneOutcomeInput) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            records = await heroes.lane_outcome(
                args.hero_id,
                is_with=args.is_with,
                week=args.week,
                bracket_basic_ids=args.bracket_basic_ids,
                position_ids=args.position_ids,
            )
            return {
                "hero_id": args.hero_id,
                "is_with": args.is_with,
                "records": records,
            }
        finally:
            await transport.aclose()

    return handle
