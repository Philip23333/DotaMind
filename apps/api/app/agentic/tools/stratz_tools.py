from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
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

STRATZ_BRACKET_BASIC_DESCRIPTION = (
    "STRATZ RankBracketBasicEnum scope filter, set on plan.context.bracket. "
    "Use exact enum values only: HERALD_GUARDIAN, CRUSADER_ARCHON, "
    "LEGEND_ANCIENT, DIVINE_IMMORTAL. Map 冠绝/Immortal/Divine to "
    "DIVINE_IMMORTAL; do not use DIVINE or IMMORTAL separately."
)


@lru_cache(maxsize=1)
def _hero_name_index() -> dict[int, str]:
    return {
        hero.id: hero.localized_name
        for hero in load_default_hero_resolver().heroes
    }


class ResolveHeroInput(BaseModel):
    query: str = Field(min_length=1)


class PairLaneOutcomeInput(BaseModel):
    hero_id: int = Field(gt=0)
    partner_hero_id: int = Field(gt=0)
    is_with: bool


class HeroMatchupRankingInput(BaseModel):
    hero_id: int = Field(gt=0)
    side: Literal["vs"] = "vs"
    take: int = Field(default=10, ge=1, le=50)
    min_sample_size: int = Field(default=100, ge=0)


class LaneMetaGlobalInput(BaseModel):
    is_with: bool
    min_sample_size: int = Field(default=200, ge=0)
    highlight_top: int = Field(default=15, ge=1, le=50)


class HeroPositionStatsInput(BaseModel):
    hero_id: int | None = Field(default=None, gt=0)
    position_id: str | None = None
    take: int = Field(default=15, ge=1, le=50)

    @model_validator(mode="after")
    def validate_exactly_one_filter(self) -> "HeroPositionStatsInput":
        if (self.hero_id is None) == (self.position_id is None):
            raise ValueError(
                "exactly one of hero_id or position_id is required"
            )
        return self


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
            name="stratz.pair_lane_outcome",
            description=(
                "Return the lane win rate for a specific pair of heroes "
                "(target hero + partner). Fetches the target hero's lane "
                "outcome and filters to the partner. Emits 0 rows if the "
                "partner pair has no recorded sample; the critic then "
                "flags insufficient evidence."
            ),
            input_model=PairLaneOutcomeInput,
            handler=_pair_lane_outcome_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=pair_lane_outcome_evidence,
            evidence_kinds=("pair_lane_winrate", "sample_size"),
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
                "partner_hero_id": ArgContract(
                    description="The other hero in the pair.",
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
                        "true for lane partners with this hero; false for "
                        "lane opponents against this hero."
                    ),
                ),
            },
            metadata={"game": "dota2", "domain": "lane_outcome"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_matchup_ranking",
            description=(
                "Return STRATZ hero-vs-hero matchup ranking rows for a "
                "target hero. Keeps advantage and disadvantage groups "
                "separate (each sorted by synergy desc, then match_count "
                "desc, top `take` per group); does NOT merge into a "
                "single ranking. side='vs' is the only supported value "
                "in this version. This is evidence ranking, not a final "
                "draft recommendation."
            ),
            input_model=HeroMatchupRankingInput,
            handler=_hero_matchup_ranking_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=hero_matchup_ranking_evidence,
            evidence_kinds=("matchup_ranking_row", "sample_size"),
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
                "side": ArgContract(
                    description="Matchup side. Only 'vs' is supported in this version.",
                ),
                "take": ArgContract(description="Top rows per advantage/disadvantage group."),
                "min_sample_size": ArgContract(
                    description="Drop rows below this match_count threshold."
                ),
            },
            metadata={"game": "dota2", "domain": "hero_matchup"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.lane_meta_global",
            description=(
                "Return high-sample lane pair rows from the global lane "
                "outcome distribution (no hero filter). Returns top "
                "`highlight_top` rows sorted by match_count desc, after "
                "dropping rows below `min_sample_size`. Note: sorting by "
                "match_count surfaces COMMON pairs, not necessarily the "
                "STRONGEST by win rate."
            ),
            input_model=LaneMetaGlobalInput,
            handler=_lane_meta_global_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=lane_meta_global_evidence,
            evidence_kinds=("lane_meta_row", "sample_size"),
            arg_contracts={
                "is_with": ArgContract(
                    description="true for ally lane pairs; false for opposing pairs."
                ),
                "min_sample_size": ArgContract(
                    description="Drop rows below this match_count threshold."
                ),
                "highlight_top": ArgContract(
                    description="Cap on rows emitted as evidence."
                ),
            },
            metadata={"game": "dota2", "domain": "lane_meta"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_position_stats",
            description=(
                "Return hero position distribution from heroStats.stats. "
                "Exactly one of hero_id or position_id is required: "
                "hero_id returns that hero's 5 position rows; position_id "
                "returns top `take` heroes in that position."
            ),
            input_model=HeroPositionStatsInput,
            handler=_hero_position_stats_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=hero_position_stats_evidence,
            evidence_kinds=("position_stat", "sample_size"),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Optional hero filter.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                ),
                "position_id": ArgContract(
                    description="Optional position filter (POSITION_1 .. POSITION_5).",
                ),
                "take": ArgContract(description="Top rows when filtering by position_id."),
            },
            metadata={"game": "dota2", "domain": "hero_position"},
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


def _resolve_hero_handler(args: ResolveHeroInput, context: QueryContext) -> dict[str, Any]:
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


def pair_lane_outcome_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    pair = data.get("pair_record")
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    evidence: list[EvidenceItem] = []
    if not isinstance(pair, dict):
        return evidence
    hero_id = data.get("hero_id")
    partner_hero_id = data.get("partner_hero_id")
    match_count = pair.get("match_count")
    evidence.append(
        EvidenceItem(
            id=(
                f"{result.tool_call_id}:pair_lane_winrate:"
                f"{hero_id}-{partner_hero_id}"
            ),
            kind="pair_lane_winrate",
            subject=f"{hero_id} paired with {partner_hero_id}",
            value={
                "hero_id": hero_id,
                "partner_hero_id": partner_hero_id,
                "is_with": data.get("is_with"),
                "position": pair.get("position"),
                "match_count": match_count,
                "match_win_rate": pair.get("match_win_rate"),
                "win_count": pair.get("win_count"),
                "loss_count": pair.get("loss_count"),
                "draw_count": pair.get("draw_count"),
                "filters": filters,
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
                    f"{result.tool_call_id}:sample_size:pair:"
                    f"{hero_id}-{partner_hero_id}"
                ),
                kind="sample_size",
                subject=f"pair sample for {hero_id}-{partner_hero_id}",
                value={
                    "sample_size": match_count,
                    "hero_id": hero_id,
                    "partner_hero_id": partner_hero_id,
                    "filters": filters,
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return evidence


def hero_matchup_ranking_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    target_hero_id = data.get("hero_id")
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    evidence: list[EvidenceItem] = []
    for source_side in ("advantage", "disadvantage"):
        rows = data.get(source_side, [])
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            match_count = row.get("match_count")
            evidence.append(
                EvidenceItem(
                    id=(
                        f"{result.tool_call_id}:matchup_ranking_row:"
                        f"{source_side}:{row.get('hero_id')}:{index}"
                    ),
                    kind="matchup_ranking_row",
                    subject=f"{row.get('hero_id')} vs {target_hero_id}",
                    value={
                        "source_side": source_side,
                        "hero_id": row.get("hero_id"),
                        "target_hero_id": row.get("target_hero_id", target_hero_id),
                        "win_rate": row.get("win_rate"),
                        "match_count": match_count,
                        "synergy": row.get("synergy"),
                        "filters": filters,
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
                            f"{source_side}:{row.get('hero_id')}:{index}"
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
                            "filters": filters,
                        },
                        source=result.source,
                        tool_call_id=result.tool_call_id,
                        tool=result.tool,
                    )
                )
    return evidence


def lane_meta_global_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return []
    names = _hero_name_index()
    evidence: list[EvidenceItem] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        match_count = row.get("match_count")
        hero_id = row.get("hero_id")
        target_hero_id = row.get("target_hero_id")
        hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
        target_hero_name = (
            names.get(target_hero_id) if isinstance(target_hero_id, int) else None
        )
        hero_label = hero_name or hero_id
        target_label = target_hero_name or target_hero_id
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:lane_meta_row:"
                    f"{hero_id}-{target_hero_id}:{index}"
                ),
                kind="lane_meta_row",
                subject=f"{hero_label} + {target_label}",
                value={
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "target_hero_id": target_hero_id,
                    "target_hero_name": target_hero_name,
                    "match_count": match_count,
                    "match_win_rate": row.get("match_win_rate"),
                    "is_with": data.get("is_with"),
                    "filters": filters,
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
                        f"{result.tool_call_id}:sample_size:lane_meta:"
                        f"{hero_id}-{target_hero_id}:{index}"
                    ),
                    kind="sample_size",
                    subject=f"lane meta sample for {hero_label} + {target_label}",
                    value={
                        "sample_size": match_count,
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "target_hero_id": target_hero_id,
                        "target_hero_name": target_hero_name,
                        "filters": filters,
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
    return evidence


def hero_position_stats_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return []
    evidence: list[EvidenceItem] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        match_count = row.get("match_count")
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:position_stat:"
                    f"{row.get('hero_id')}-{row.get('position')}:{index}"
                ),
                kind="position_stat",
                subject=f"hero {row.get('hero_id')} at {row.get('position')}",
                value={
                    "hero_id": row.get("hero_id"),
                    "position": row.get("position"),
                    "match_count": match_count,
                    "filters": filters,
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
                        f"{result.tool_call_id}:sample_size:position_stat:"
                        f"{row.get('hero_id')}-{row.get('position')}:{index}"
                    ),
                    kind="sample_size",
                    subject=f"position sample for hero {row.get('hero_id')}",
                    value={
                        "sample_size": match_count,
                        "hero_id": row.get("hero_id"),
                        "position": row.get("position"),
                        "filters": filters,
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
    return evidence


def _pair_lane_outcome_handler(settings: Settings):
    async def handle(
        args: PairLaneOutcomeInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            records = await heroes.lane_outcome(
                args.hero_id,
                is_with=args.is_with,
                week=context.week,
                bracket_basic_ids=context.bracket,
                position_ids=context.position_ids,
            )
        finally:
            await transport.aclose()

        matches = [
            record
            for record in records
            if isinstance(record, dict) and record.get("hero_id") == args.partner_hero_id
        ]
        pair_record = matches[0] if matches else None
        return {
            "hero_id": args.hero_id,
            "partner_hero_id": args.partner_hero_id,
            "is_with": args.is_with,
            "filters": {
                "week": context.week,
                "bracket_basic_ids": context.bracket,
                "position_ids": context.position_ids,
                "is_with": args.is_with,
            },
            "pair_record": pair_record,
            "total_partner_matches": len(matches),
        }

    return handle


def _hero_matchup_ranking_handler(settings: Settings):
    async def handle(
        args: HeroMatchupRankingInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            data = await heroes.hero_vs_hero_matchup(
                args.hero_id,
                take=max(args.take, 50),
                week=context.week,
                bracket_basic_ids=context.bracket,
            )
        finally:
            await transport.aclose()

        advantage = _filter_matchup_rows(data.get("advantage", []), args.min_sample_size, args.take)
        disadvantage = _filter_matchup_rows(
            data.get("disadvantage", []), args.min_sample_size, args.take
        )
        return {
            "hero_id": args.hero_id,
            "side": args.side,
            "advantage": advantage,
            "disadvantage": disadvantage,
            "filters": {
                "take": args.take,
                "min_sample_size": args.min_sample_size,
                "week": context.week,
                "bracket_basic_ids": context.bracket,
            },
        }

    return handle


def _lane_meta_global_handler(settings: Settings):
    async def handle(
        args: LaneMetaGlobalInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            records = await heroes.lane_outcome(
                None,
                is_with=args.is_with,
                week=context.week,
                bracket_basic_ids=context.bracket,
            )
        finally:
            await transport.aclose()

        qualifying = [
            record
            for record in records
            if isinstance(record, dict)
            and (record.get("match_count") or 0) >= args.min_sample_size
        ]
        qualifying.sort(key=lambda r: (r.get("match_count") or 0), reverse=True)
        top = qualifying[: args.highlight_top]
        for row in top:
            row.pop("position", None)
        return {
            "is_with": args.is_with,
            "filters": {
                "week": context.week,
                "bracket_basic_ids": context.bracket,
                "is_with": args.is_with,
            },
            "rows": top,
            "total_available": len(qualifying),
            "returned_count": len(top),
            "selection_policy": (
                f"min_sample_size>={args.min_sample_size}, "
                f"sorted_by=match_count desc, top={args.highlight_top}"
            ),
        }

    return handle


def _hero_position_stats_handler(settings: Settings):
    async def handle(
        args: HeroPositionStatsInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            rows = await heroes.hero_position_stats(
                hero_ids=[args.hero_id] if args.hero_id is not None else None,
                position_ids=[args.position_id] if args.position_id is not None else None,
                bracket_basic_ids=context.bracket,
                week=context.week,
            )
        finally:
            await transport.aclose()

        if args.position_id is not None:
            rows = sorted(rows, key=lambda r: r.get("match_count") or 0, reverse=True)
            rows = rows[: args.take]
        return {
            "hero_id": args.hero_id,
            "position_id": args.position_id,
            "filters": {
                "week": context.week,
                "bracket_basic_ids": context.bracket,
            },
            "rows": rows,
            "returned_count": len(rows),
        }

    return handle


def _filter_matchup_rows(
    rows: list[dict[str, Any]],
    min_sample_size: int,
    take: int,
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if isinstance(row, dict) and (row.get("match_count") or 0) >= min_sample_size
    ]
    filtered.sort(
        key=lambda r: (
            float(r.get("synergy") or 0),
            int(r.get("match_count") or 0),
        ),
        reverse=True,
    )
    return filtered[:take]
