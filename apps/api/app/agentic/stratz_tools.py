from typing import Any

from pydantic import BaseModel, Field

from app.agentic.hero_resolver import load_default_hero_resolver
from app.agentic.models import ToolSource
from app.agentic.registry import ToolDefinition, ToolRegistry
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
            metadata={"game": "dota2", "domain": "lane_outcome"},
        )
    )


def build_default_tool_registry(settings: Settings) -> ToolRegistry:
    from app.agentic.opendota_tools import register_opendota_tools
    from app.agentic.patch_tools import register_patch_tools

    registry = ToolRegistry()
    register_stratz_tools(registry, settings)
    register_opendota_tools(registry, settings)
    register_patch_tools(registry)
    return registry


def _resolve_hero_handler(args: ResolveHeroInput) -> dict[str, Any]:
    return load_default_hero_resolver().resolve(args.query)


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
