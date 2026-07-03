import asyncio
import time
from collections.abc import Awaitable, Callable
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
from app.core.config import Settings, get_policy
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
                "outcome distribution (no hero filter). STRATZ returns two "
                "mirror rows per ally pair; this tool collapses them to one "
                "row per pair, keeping the direction with the larger "
                "match_count. Returns top `highlight_top` rows sorted by "
                "match_count desc, after dropping rows below "
                "`min_sample_size`. Note: sorting by match_count surfaces "
                "COMMON pairs, not necessarily the STRONGEST by win rate."
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
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    buckets = data.get("weekly_buckets")
    if not isinstance(buckets, list):
        return []
    names = _hero_name_index()
    hero_id = data.get("hero_id")
    partner_hero_id = data.get("partner_hero_id")
    hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
    partner_hero_name = (
        names.get(partner_hero_id) if isinstance(partner_hero_id, int) else None
    )
    hero_label = hero_name or hero_id
    partner_label = partner_hero_name or partner_hero_id
    evidence: list[EvidenceItem] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        rows = bucket.get("rows") or []
        if not rows:
            continue
        pair = rows[0] if isinstance(rows[0], dict) else {}
        week_epoch = bucket.get("week_epoch")
        week_index = bucket.get("week_index")
        window_label = bucket.get("window_label")
        match_count = pair.get("match_count")
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:pair_lane_winrate:"
                    f"{hero_id}-{partner_hero_id}:{week_epoch}"
                ),
                kind="pair_lane_winrate",
                subject=f"{hero_label} paired with {partner_label} ({window_label})",
                value={
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "partner_hero_id": partner_hero_id,
                    "partner_hero_name": partner_hero_name,
                    "is_with": data.get("is_with"),
                    "position": pair.get("position"),
                    "match_count": match_count,
                    "match_win_rate": pair.get("match_win_rate"),
                    "win_count": pair.get("win_count"),
                    "loss_count": pair.get("loss_count"),
                    "draw_count": pair.get("draw_count"),
                    "week_epoch": week_epoch,
                    "week_index": week_index,
                    "window_label": window_label,
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
                        f"{hero_id}-{partner_hero_id}:{week_epoch}"
                    ),
                    kind="sample_size",
                    subject=f"pair sample for {hero_label} + {partner_label} ({window_label})",
                    value={
                        "sample_size": match_count,
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "partner_hero_id": partner_hero_id,
                        "partner_hero_name": partner_hero_name,
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
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
    buckets = data.get("weekly_buckets")
    if not isinstance(buckets, list):
        return []
    names = _hero_name_index()
    evidence: list[EvidenceItem] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        week_epoch = bucket.get("week_epoch")
        week_index = bucket.get("week_index")
        window_label = bucket.get("window_label")
        rows = bucket.get("rows") or []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            match_count = row.get("match_count")
            hero_id = row.get("hero_id")
            resolved_target_id = row.get("target_hero_id", target_hero_id)
            hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
            resolved_target_name = (
                names.get(resolved_target_id)
                if isinstance(resolved_target_id, int)
                else None
            )
            hero_label = hero_name or hero_id
            resolved_target_label = resolved_target_name or resolved_target_id
            source_side = row.get("source_side", "advantage")
            evidence.append(
                EvidenceItem(
                    id=(
                        f"{result.tool_call_id}:matchup_ranking_row:"
                        f"{source_side}:{hero_id}:{week_epoch}:{index}"
                    ),
                    kind="matchup_ranking_row",
                    subject=f"{hero_label} vs {resolved_target_label} ({window_label})",
                    value={
                        "source_side": source_side,
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "target_hero_id": resolved_target_id,
                        "target_hero_name": resolved_target_name,
                        "win_rate": row.get("win_rate"),
                        "match_count": match_count,
                        "synergy": row.get("synergy"),
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
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
                            f"{source_side}:{hero_id}:{week_epoch}:{index}"
                        ),
                        kind="sample_size",
                        subject=f"{hero_label} vs {resolved_target_label} ({window_label})",
                        value={
                            "sample_size": match_count,
                            "hero_id": hero_id,
                            "hero_name": hero_name,
                            "target_hero_id": resolved_target_id,
                            "target_hero_name": resolved_target_name,
                            "week_epoch": week_epoch,
                            "week_index": week_index,
                            "window_label": window_label,
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
    buckets = data.get("weekly_buckets")
    if not isinstance(buckets, list):
        return []
    names = _hero_name_index()
    evidence: list[EvidenceItem] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        week_epoch = bucket.get("week_epoch")
        week_index = bucket.get("week_index")
        window_label = bucket.get("window_label")
        rows = bucket.get("rows") or []
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
                        f"{hero_id}-{target_hero_id}:{week_epoch}:{index}"
                    ),
                    kind="lane_meta_row",
                    subject=f"{hero_label} + {target_label} ({window_label})",
                    value={
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "target_hero_id": target_hero_id,
                        "target_hero_name": target_hero_name,
                        "match_count": match_count,
                        "match_win_rate": row.get("match_win_rate"),
                        "is_with": data.get("is_with"),
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
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
                            f"{hero_id}-{target_hero_id}:{week_epoch}:{index}"
                        ),
                        kind="sample_size",
                        subject=f"lane meta sample for {hero_label} + {target_label} ({window_label})",
                        value={
                            "sample_size": match_count,
                            "hero_id": hero_id,
                            "hero_name": hero_name,
                            "target_hero_id": target_hero_id,
                            "target_hero_name": target_hero_name,
                            "week_epoch": week_epoch,
                            "week_index": week_index,
                            "window_label": window_label,
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
    buckets = data.get("weekly_buckets")
    if not isinstance(buckets, list):
        return []
    names = _hero_name_index()
    evidence: list[EvidenceItem] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        week_epoch = bucket.get("week_epoch")
        week_index = bucket.get("week_index")
        window_label = bucket.get("window_label")
        rows = bucket.get("rows") or []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            match_count = row.get("match_count")
            hero_id = row.get("hero_id")
            hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
            hero_label = hero_name or hero_id
            evidence.append(
                EvidenceItem(
                    id=(
                        f"{result.tool_call_id}:position_stat:"
                        f"{hero_id}-{row.get('position')}:{week_epoch}:{index}"
                    ),
                    kind="position_stat",
                    subject=f"{hero_label} at {row.get('position')} ({window_label})",
                    value={
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "position": row.get("position"),
                        "match_count": match_count,
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
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
                            f"{hero_id}-{row.get('position')}:{week_epoch}:{index}"
                        ),
                        kind="sample_size",
                        subject=f"position sample for {hero_label} ({window_label})",
                        value={
                            "sample_size": match_count,
                            "hero_id": hero_id,
                            "hero_name": hero_name,
                            "position": row.get("position"),
                            "week_epoch": week_epoch,
                            "week_index": week_index,
                            "window_label": window_label,
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

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:
            for week_index, epoch in enumerate(epochs, start=1):
                records = await _with_retry(
                    lambda e=epoch: heroes.lane_outcome(
                        args.hero_id,
                        is_with=args.is_with,
                        week=e,
                        bracket_basic_ids=context.bracket,
                        position_ids=context.position_ids,
                    )
                )
                matches = [
                    record
                    for record in records
                    if isinstance(record, dict)
                    and record.get("hero_id") == args.partner_hero_id
                ]
                rows = [matches[0]] if matches else []
                buckets.append(_bucket(epoch, week_index, rows))
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "hero_id": args.hero_id,
            "partner_hero_id": args.partner_hero_id,
            "is_with": args.is_with,
            "weekly_buckets": buckets,
            "weeks_with_record": weeks_with_record,
            "missing_week_epochs": missing_epochs,
            "filters": _window_filters(
                {
                    "bracket_basic_ids": context.bracket,
                    "position_ids": context.position_ids,
                    "is_with": args.is_with,
                },
                weeks,
                epochs,
            ),
        }

    return handle


def _hero_matchup_ranking_handler(settings: Settings):
    async def handle(
        args: HeroMatchupRankingInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:
            for week_index, epoch in enumerate(epochs, start=1):
                data = await _with_retry(
                    lambda e=epoch: heroes.hero_vs_hero_matchup(
                        args.hero_id,
                        take=max(args.take, 50),
                        week=e,
                        bracket_basic_ids=context.bracket,
                    )
                )
                advantage = _filter_matchup_rows(
                    data.get("advantage", []), args.min_sample_size, args.take
                )
                disadvantage = _filter_matchup_rows(
                    data.get("disadvantage", []), args.min_sample_size, args.take
                )
                rows = [
                    {"source_side": "advantage", **row} for row in advantage
                ] + [
                    {"source_side": "disadvantage", **row} for row in disadvantage
                ]
                buckets.append(_bucket(epoch, week_index, rows))
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "hero_id": args.hero_id,
            "side": args.side,
            "weekly_buckets": buckets,
            "weeks_with_record": weeks_with_record,
            "missing_week_epochs": missing_epochs,
            "filters": _window_filters(
                {
                    "take": args.take,
                    "min_sample_size": args.min_sample_size,
                    "bracket_basic_ids": context.bracket,
                },
                weeks,
                epochs,
            ),
        }

    return handle


def _dedupe_pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse mirror (a,b) / (b,a) rows into one entry per pair.

    STRATZ `laneOutcome` returns two rows per ally pair (hero_id, target_hero_id
    and its reverse). Under bracket filters these rows can have asymmetric
    stats because each direction is sampled from a different match subset
    (heroId1's lane-bucket perspective). Keep the row with the larger
    match_count as the more statistically reliable view of the pair.
    """
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        a = row.get("hero_id")
        b = row.get("target_hero_id")
        if not isinstance(a, int) or not isinstance(b, int):
            continue
        key = (a, b) if a <= b else (b, a)
        previous = seen.get(key)
        if previous is None or (row.get("match_count") or 0) > (
            previous.get("match_count") or 0
        ):
            seen[key] = row
    return list(seen.values())


def _lane_meta_global_handler(settings: Settings):
    async def handle(
        args: LaneMetaGlobalInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("METAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:
            for week_index, epoch in enumerate(epochs, start=1):
                records = await _with_retry(
                    lambda e=epoch: heroes.lane_outcome(
                        None,
                        is_with=args.is_with,
                        week=e,
                        bracket_basic_ids=context.bracket,
                    )
                )
                deduped = _dedupe_pair_rows(records)
                qualifying = [
                    record
                    for record in deduped
                    if isinstance(record, dict)
                    and (record.get("match_count") or 0) >= args.min_sample_size
                ]
                qualifying.sort(key=lambda r: (r.get("match_count") or 0), reverse=True)
                top = qualifying[: args.highlight_top]
                for row in top:
                    row.pop("position", None)
                buckets.append(_bucket(epoch, week_index, top))
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "is_with": args.is_with,
            "weekly_buckets": buckets,
            "weeks_with_record": weeks_with_record,
            "missing_week_epochs": missing_epochs,
            "filters": _window_filters(
                {
                    "bracket_basic_ids": context.bracket,
                    "is_with": args.is_with,
                    "min_sample_size": args.min_sample_size,
                    "highlight_top": args.highlight_top,
                },
                weeks,
                epochs,
            ),
            "selection_policy": (
                "per_completed_week: "
                "deduped=keep_larger_match_count_mirror, "
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

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:
            for week_index, epoch in enumerate(epochs, start=1):
                rows = await _with_retry(
                    lambda e=epoch: heroes.hero_position_stats(
                        hero_ids=[args.hero_id] if args.hero_id is not None else None,
                        position_ids=[args.position_id] if args.position_id is not None else None,
                        bracket_basic_ids=context.bracket,
                        week=e,
                    )
                )
                if args.position_id is not None:
                    rows = sorted(rows, key=lambda r: r.get("match_count") or 0, reverse=True)
                    rows = rows[: args.take]
                buckets.append(_bucket(epoch, week_index, rows))
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "hero_id": args.hero_id,
            "position_id": args.position_id,
            "weekly_buckets": buckets,
            "weeks_with_record": weeks_with_record,
            "missing_week_epochs": missing_epochs,
            "filters": _window_filters(
                {"bracket_basic_ids": context.bracket},
                weeks,
                epochs,
            ),
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


# --- STRATZ week-window resolution -----------------------------------------
# A STRATZ week is 604800s-aligned to the Unix epoch; verified live that
# `week` is a single weekly bucket and `null` means the latest *completed*
# week (see docs/design/time_patch_filtering.md). Handlers resolve a relative
# `weeks_back` to concrete completed-week epochs and return one bucket per
# week (never merged across weeks).

_WEEK_SECONDS = 604_800


def _now() -> float:
    """Module clock so tests can monkeypatch deterministic time."""
    return time.time()


def resolve_recent_completed_weeks(weeks_back: int, *, now: float) -> list[int]:
    """Epoch seconds of the last `weeks_back` *completed* STRATZ weeks, newest
    first. The in-progress current week is always skipped (it is partial)."""
    if weeks_back < 1:
        return []
    current_index = int(now // _WEEK_SECONDS)
    return [(current_index - k) * _WEEK_SECONDS for k in range(1, weeks_back + 1)]


def _resolve_week_window(weeks_back: int | None) -> tuple[int, list[int]]:
    """Resolve plan-level weeks_back (null allowed) to (weeks, epochs) using
    the policy default for null."""
    default_weeks = get_policy().stratz.weeks_back_default
    weeks = weeks_back if weeks_back and weeks_back > 0 else default_weeks
    return weeks, resolve_recent_completed_weeks(weeks, now=_now())


def _window_label(week_index: int) -> str:
    if week_index == 1:
        return "latest_completed_week"
    if week_index == 2:
        return "prior_completed_week"
    return f"completed_week_{week_index}"


def _bucket(
    week_epoch: int, week_index: int, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "week_epoch": week_epoch,
        "week_index": week_index,
        "window_label": _window_label(week_index),
        "rows": rows,
    }


def _week_summary(
    buckets: list[dict[str, Any]],
) -> tuple[int, list[int]]:
    """(weeks_with_record, missing_week_epochs) — empty buckets are preserved
    so a partial-week gap stays visible to the synthesizer."""
    weeks_with_record = sum(1 for bucket in buckets if bucket.get("rows"))
    missing = [bucket["week_epoch"] for bucket in buckets if not bucket.get("rows")]
    return weeks_with_record, missing


def _window_filters(
    extra: dict[str, Any], weeks: int, epochs: list[int]
) -> dict[str, Any]:
    filters = dict(extra)
    filters.update(
        {
            "weeks_back": weeks,
            "week_epochs": epochs,
            "weeks_resolved": len(epochs),
            "skipped_current_week": True,
        }
    )
    return filters


async def _with_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 4,
    backoff: float = 2.0,
) -> Any:
    """Retry transient STRATZ failures. The last error is re-raised after
    attempts are exhausted — upstream errors surface, never swallowed into a
    false success."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001 - resilience against flaky upstream
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc
