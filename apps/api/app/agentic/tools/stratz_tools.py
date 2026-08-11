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
from app.core.config import Settings, get_policy
from app.integrations.stratz.brackets import (
    basic_to_bracket_ids,
    basic_to_full,
    basic_to_rank_ids,
)
from app.integrations.stratz.heroes import StratzHeroes
from app.integrations.stratz.players import StratzPlayers
from app.integrations.stratz.transport import StratzTransport
from app.integrations.stratz.wilson import wilson_lower_bound
from app.integrations.valve.catalog_repository import load_default_catalog_repository

STRATZ_BRACKET_BASIC_DESCRIPTION = (
    "STRATZ RankBracketBasicEnum scope filter, set on plan.context.bracket. "
    "Use exact enum values only: HERALD_GUARDIAN, CRUSADER_ARCHON, "
    "LEGEND_ANCIENT, DIVINE_IMMORTAL. Map 冠绝/Immortal/Divine to "
    "DIVINE_IMMORTAL; do not use DIVINE or IMMORTAL separately."
)

# Provenance for Wilson-score rating fields on hero-recommendation evidence.
# STRATZ documents its /heroes/meta/trends rating as a Wilson score over
# (win rate, match count) but does not publish z; z=1.96 (95% CI) is assumed.
_WILSON_PROVENANCE = (
    "wilson_lower_bound(winCount, matchCount, z=1.96); "
    "method per STRATZ trends rating; z assumed 95% CI"
)
# Lane win rate is match-level (matchWinCount) — distinct from the winCount the
# position/matchup/synergy tools feed into Wilson. The lane handler sources
# match_win_count (GraphQL matchWinCount), so its provenance must name that field,
# not winCount. See memory lane-match-win-rate-derivation.
_WILSON_PROVENANCE_MATCH = (
    "wilson_lower_bound(matchWinCount, matchCount, z=1.96); "
    "method per STRATZ trends rating; z assumed 95% CI"
)


@lru_cache(maxsize=1)
def _hero_name_index() -> dict[int, str]:
    return load_default_catalog_repository().hero_name_index()


class PairLaneOutcomeInput(BaseModel):
    hero_id: int = Field(gt=0)
    partner_hero_id: int = Field(gt=0)
    is_with: bool


class HeroMatchupRankingInput(BaseModel):
    hero_id: int = Field(gt=0)
    side: Literal["vs"] = "vs"
    take: int = Field(default=10, ge=1, le=50)
    # keep in sync with policy.yaml planning.sample_policy
    # .tools[stratz.hero_matchup_ranking].default
    min_sample_size: int = Field(default=2000, ge=0)


class HeroSynergyRankingInput(BaseModel):
    hero_id: int = Field(gt=0)
    side: Literal["with"] = "with"
    take: int = Field(default=10, ge=1, le=50)
    # keep in sync with policy.yaml planning.sample_policy
    # .tools[stratz.hero_synergy_ranking].default
    min_sample_size: int = Field(default=2000, ge=0)


class LaneMetaGlobalInput(BaseModel):
    is_with: bool
    # keep in sync with policy.yaml planning.sample_policy.tools[stratz.lane_meta_global].default
    min_sample_size: int = Field(default=1000, ge=0)
    highlight_top: int = Field(default=15, ge=1, le=50)
    selection_mode: Literal["popular", "strong"] = "strong"


class HeroPositionStatsInput(BaseModel):
    hero_id: int | None = Field(default=None, gt=0)
    position_id: str | None = None
    take: int = Field(default=15, ge=1, le=50)
    # keep in sync with policy.yaml planning.sample_policy.tools[stratz.hero_position_stats].default
    min_sample_size: int = Field(default=1000, ge=0)
    selection_mode: Literal["popular", "strong"] = "strong"

    @model_validator(mode="after")
    def validate_exactly_one_filter(self) -> "HeroPositionStatsInput":
        if (self.hero_id is None) == (self.position_id is None):
            raise ValueError(
                "exactly one of hero_id or position_id is required"
            )
        return self


class PlayerProfileInput(BaseModel):
    steam_account_id: int = Field(gt=0)


class PlayerRecentMatchesInput(BaseModel):
    steam_account_id: int = Field(gt=0)
    # Count cap. days is a date-window lower bound (within last N days). Both
    # apply as an intersection: within the days window, newest first, capped at
    # take. See docs/technical/stratz_player_page_graphql_inventory.md.
    take: int = Field(default=20, ge=1, le=50)
    days: int | None = Field(default=None, ge=1)


class PlayerHeroPerformanceInput(BaseModel):
    steam_account_id: int = Field(gt=0)
    # take = output hero rows (outer heroesPerformance take). match_take = the
    # match sample size contributing to each hero's stats (request.take). days =
    # date window. Three independent knobs — see inventory §双 take.
    take: int = Field(default=15, ge=1, le=50)
    days: int | None = Field(default=None, ge=1)
    match_take: int | None = Field(default=None, ge=1)
    min_match_count: int = Field(default=3, ge=0)
    selection_mode: Literal["popular", "strong"] = "strong"


def register_stratz_tools(registry: ToolRegistry, settings: Settings) -> None:
    registry.register(
        ToolDefinition(
            name="stratz.pair_lane_outcome",
            description=(
                "Return the lane win rate for a specific pair of heroes "
                "(target hero + partner). Fetches the target hero's lane "
                "outcome and filters to the partner. Emits 0 rows if the "
                "partner pair has no recorded sample; the critic then "
                "flags insufficient evidence. Also returns stomp_win_count/"
                "stomp_loss_count/cs_count as lane dominance / cs evidence "
                "(win_count/loss_count/draw_count are lane-level; match_win_rate is match-level)."
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
            mandatory_evidence=("pair_lane_winrate",),
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
                    requires_reference=True,
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
                    requires_reference=True,
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
                "target hero. Ranking basis is `synergy` desc (STRATZ's "
                "composite matchup advantage score, sample-weighted), "
                "tie-break `match_count` desc. Sorting and the "
                "`min_sample_size` floor are applied in the agentic layer "
                "after the integration layer normalizes field names only. "
                "Keeps advantage and disadvantage groups separate (top "
                "`take` per group); does NOT merge into a single ranking. "
                "Each row carries `matchup_win_rate` (= winCount/matchCount, "
                "the target hero's game win rate versus that opponent) with "
                "`win_rate_basis` declaring the caliber. "
                "side='vs' is the only supported value in this version. "
                "This is evidence ranking, not a final draft recommendation."
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
            mandatory_evidence=("matchup_ranking_row",),
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
                    requires_reference=True,
                ),
                "side": ArgContract(
                    description="Matchup side. Only 'vs' is supported in this version.",
                ),
                "take": ArgContract(description="Top rows per advantage/disadvantage group."),
                "min_sample_size": ArgContract(
                    description="Drop rows below this match_count threshold."
                ),
            },
            output_paths={
                "candidate_rows": OutputPathContract(
                    path="data.candidate_rows",
                    type="list[dict]",
                    description=(
                        "Latest completed week's ranking rows "
                        "(advantage+disadvantage flattened)."
                    ),
                ),
            },
            metadata={"game": "dota2", "domain": "hero_matchup"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_synergy_ranking",
            description=(
                "Return STRATZ hero-hero ALLY synergy ranking rows for a target "
                "hero (ally pairs, from heroVsHeroMatchup.with). Ranking basis is "
                "`synergy` desc (STRATZ's composite synergy score, sample-weighted), "
                "tie-break `match_count` desc; sorting and the `min_sample_size` floor "
                "are applied in the agentic layer after the integration layer normalizes "
                "field names only. Keeps advantage (strong allies) and disadvantage "
                "(weak allies) groups separate (top `take` per group); does NOT merge. "
                "side='with' is the only supported value. Use this for 'teammate X, what "
                "should I pick to synergize' queries; use stratz.hero_matchup_ranking for "
                "enemy counter-picks. Each row carries `pair_win_rate` (= winCount/matchCount, "
                "the ally pair's game win rate) with `win_rate_basis` declaring the ally-pair "
                "caliber (distinct from matchup's matchup_win_rate)."
            ),
            input_model=HeroSynergyRankingInput,
            handler=_hero_synergy_ranking_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=hero_synergy_ranking_evidence,
            evidence_kinds=("hero_synergy_ranking_row", "sample_size"),
            mandatory_evidence=("hero_synergy_ranking_row",),
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
                    requires_reference=True,
                ),
                "side": ArgContract(
                    description="Synergy side. Only 'with' is supported in this version.",
                ),
                "take": ArgContract(description="Top rows per advantage/disadvantage group."),
                "min_sample_size": ArgContract(
                    description="Drop rows below this match_count threshold."
                ),
            },
            output_paths={
                "candidate_rows": OutputPathContract(
                    path="data.candidate_rows",
                    type="list[dict]",
                    description=(
                        "Latest completed week's ranking rows "
                        "(advantage+disadvantage flattened)."
                    ),
                ),
            },
            metadata={"game": "dota2", "domain": "hero_synergy"},
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
                "match_count. After dropping rows below `min_sample_size`, "
                "`selection_mode` picks the ranking basis: 'strong' ranks by "
                "wilson_rating desc (Wilson lower bound of the match win rate, "
                "z=1.96, confidence-aware; tie-break match_count desc) — the "
                "strongest, most reliable pairs; 'popular' ranks by match_count "
                "desc — the most-played pairs. `match_win_rate` is match-level "
                "(matchWinCount/matchCount, the pair's game win rate), NOT "
                "lane-level (winCount/lossCount track lane outcome instead). "
                "Each row also carries stomp_win_count/stomp_loss_count/cs_count "
                "as lane dominance / cs evidence, and `win_rate_basis` declaring "
                "the win-rate caliber. Global view: this tool IGNORES "
                "context.position_ids (laneOutcome positionIds are dropped by design "
                "to keep the global pair perspective); for a specific hero+partner "
                "lane query use stratz.pair_lane_outcome. Returns the top "
                "`highlight_top` rows per completed week."
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
            mandatory_evidence=("lane_meta_row",),
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
                "selection_mode": ArgContract(
                    description=(
                        "Ranking basis after the min_sample_size floor. "
                        "'strong' = 强势/胜率高 (sort by wilson_rating desc "
                        "(Wilson lower bound of match win rate, z=1.96), "
                        "tie-break match_count desc); 'popular' = 常见/出场多 "
                        "(sort by match_count desc). Default 'strong'."
                    )
                ),
            },
            metadata={"game": "dota2", "domain": "lane_meta"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_position_stats",
            description=(
                "Return hero position stats (matchCount + winCount -> match_win_rate) "
                "from heroStats.stats. Exactly one of hero_id or position_id is required. "
                "selection_mode/min_sample_size apply to BOTH branches: 'strong' = "
                "wilson_rating desc (Wilson lower bound of match win rate, z=1.96, "
                "confidence-aware; tie-break match_count desc) — answers 某位置胜率最高 / "
                "某英雄最强位置; 'popular' = match_count desc — answers 出场最多. hero_id "
                "returns the hero's position rows ranked but NOT truncated (full "
                "distribution); position_id returns top `take` heroes in that position "
                "(take truncates only this branch). win_rate_basis declares match-level "
                "caliber (winCount/matchCount)."
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
            mandatory_evidence=("position_stat",),
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
                    requires_reference=True,
                ),
                "position_id": ArgContract(
                    description="Optional position filter (POSITION_1 .. POSITION_5).",
                ),
                "take": ArgContract(
                    description="Top rows when filtering by position_id "
                    "(position_id branch only)."
                ),
                "min_sample_size": ArgContract(
                    description="Drop rows below this match_count threshold (both branches)."
                ),
                "selection_mode": ArgContract(
                    description=(
                        "Ranking basis after the min_sample_size floor, applies to both "
                        "hero_id and position_id branches. 'strong' = 强势/胜率高 "
                        "(wilson_rating desc = Wilson lower bound of match win rate, "
                        "z=1.96; tie-break match_count desc); "
                        "'popular' = 常见/出场多 (match_count desc). Default 'strong'."
                    )
                ),
            },
            metadata={"game": "dota2", "domain": "hero_position"},
        )
    )


    registry.register(
        ToolDefinition(
            name="stratz.hero_daily_trends",
            description=(
                "Return STRATZ day-grain win-rate/played trend for a hero "
                "(heroStats.winDay, last `take` days, max 12). Each row is one "
                "day: win_count/match_count -> win_rate. NOT per-week — does NOT "
                "use weeks_back; the window is calendar days (STRATZ returns the "
                "most recent days, newest first). bracket on context.bracket is "
                "expanded from RankBracketBasicEnum to RankBracket (winDay only "
                "accepts the full enum); region_ids/game_mode_ids/position_ids on "
                "context are honored. Use for 'is Lina rising/falling recently / "
                "still worth practicing' questions. win_rate_basis declares the "
                "day-level caliber."
            ),
            input_model=HeroDailyTrendsInput,
            handler=_hero_daily_trends_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=hero_daily_trends_evidence,
            evidence_kinds=("hero_daily_trend",),
            mandatory_evidence=("hero_daily_trend",),
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
                    requires_reference=True,
                ),
                "take": ArgContract(description="Number of recent days (1..12, default 12)."),
            },
            metadata={"game": "dota2", "domain": "hero_trend"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.filter_heroes_by_position",
            description=(
                "Filter ranking candidates (from stratz.hero_matchup_ranking or "
                "stratz.hero_synergy_ranking) down to heroes that have a position "
                "sample at `position_id`. candidate_rows is a $ref to "
                "$<rank_call>.data.candidate_rows (list[dict]; preserves original "
                "source_side/synergy/win_rate/sample). Joins hero_position_stats at "
                "the position; keeps heroes with position match_count >= "
                "min_position_match_count. Output role_filtered_candidate_row "
                "evidence carries the ORIGINAL ranking row + position sample — no "
                "invented composite score (thin relay). Use for '4 号位克制 Lina' "
                "(matchup Lina -> filter by POSITION_4)."
            ),
            input_model=FilterHeroesByPositionInput,
            handler=_filter_heroes_by_position_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=filter_heroes_by_position_evidence,
            evidence_kinds=("role_filtered_candidate_row",),
            mandatory_evidence=("role_filtered_candidate_row",),
            arg_contracts={
                "candidate_rows": ArgContract(
                    description=(
                        "Ranking rows from matchup/synergy. Use ref "
                        "$<rank_call>.data.candidate_rows."
                    ),
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="stratz.hero_matchup_ranking",
                            path="data.candidate_rows",
                            type="list[dict]",
                        ),
                        AcceptedRef(
                            from_tool="stratz.hero_synergy_ranking",
                            path="data.candidate_rows",
                            type="list[dict]",
                        ),
                    ),
                ),
                "position_id": ArgContract(
                    description="Position to filter by (POSITION_1 .. POSITION_5)."
                ),
                "min_position_match_count": ArgContract(
                    description="Drop heroes below this match_count at the position."
                ),
            },
            metadata={"game": "dota2", "domain": "role_filter"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.player_profile",
            description=(
                "Return a player's STRATZ profile (name/avatar/seasonRank + "
                "global matchCount/winCount/imp/lastMatchDate) by steamAccountId "
                "(Steam32). v1: steamAccountId direct, no name search — non-numeric "
                "queries should return insufficient_tools. Use for 'who is this "
                "player / player overview'; pair with player_recent_matches or "
                "player_hero_performance for match questions."
            ),
            input_model=PlayerProfileInput,
            handler=_player_profile_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=player_profile_evidence,
            evidence_kinds=("player_identity",),
            mandatory_evidence=("player_identity",),
            arg_contracts={
                "steam_account_id": ArgContract(
                    description="Player Steam32 account id (steamAccountId)."
                ),
            },
            output_paths={
                "confirmed_steam_account_id": OutputPathContract(
                    path="data.confirmed_steam_account_id",
                    type="int",
                    description="Steam32 id confirmed by a live player profile.",
                )
            },
            metadata={"game": "dota2", "domain": "player_identity"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.player_recent_matches",
            description=(
                "Return a player's recent matches by steamAccountId. Win is native "
                "MatchPlayerType.isVictory (not derived). Scope filters (bracket, "
                "position_ids) come from plan.context; v1 does NOT support "
                "region_ids/game_mode_ids. Args: take=count cap (1-50, default 20); "
                "days=date window (within last N days, newest first, capped at take). "
                "Emits per-match player_recent_match rows + a player_recent_summary "
                "(wins/losses/match_count, deterministic counts) + sample_size."
            ),
            input_model=PlayerRecentMatchesInput,
            handler=_player_recent_matches_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=player_recent_matches_evidence,
            evidence_kinds=(
                "player_recent_match",
                "player_recent_summary",
                "sample_size",
            ),
            mandatory_evidence=("player_recent_summary",),
            arg_contracts={
                "steam_account_id": ArgContract(
                    description="Player Steam32 account id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="stratz.player_profile",
                            path="data.confirmed_steam_account_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
                "take": ArgContract(description="Max matches to return (1-50)."),
                "days": ArgContract(
                    description="Date window in days (within last N days). Optional."
                ),
            },
            metadata={"game": "dota2", "domain": "player_matches"},
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.player_hero_performance",
            description=(
                "Return a player's per-hero performance (winCount/matchCount/avg "
                "stats) by steamAccountId. win_rate is locally derived "
                "(winCount/matchCount; STRATZ has no native winRate). Scope filters "
                "(bracket->rankIds 0-80, position_ids) come from plan.context; v1 "
                "does NOT support region_ids/game_mode_ids. Three independent knobs: "
                "take=output hero rows (1-50, default 15); match_take=match sample "
                "size contributing to each hero's stats (the recent N matches); "
                "days=date window. selection_mode: 'strong' over-fetches then ranks "
                "by win_rate (min_match_count floor); 'popular' ranks by games "
                "played. Use for 'which heroes does this player win with lately'. "
                "Param mapping — '近N场什么英雄胜率高' -> match_take=N (NOT take); "
                "'返回前N个英雄' -> take=N; '最近一周' -> days=7."
            ),
            input_model=PlayerHeroPerformanceInput,
            handler=_player_hero_performance_handler(settings),
            source=ToolSource(
                name="STRATZ",
                kind="public_graphql_api",
                url=settings.stratz_graphql_url,
                status="live",
            ),
            evidence_extractor=player_hero_performance_evidence,
            evidence_kinds=(
                "player_hero_performance",
                "sample_size",
            ),
            mandatory_evidence=("player_hero_performance",),
            arg_contracts={
                "steam_account_id": ArgContract(
                    description="Player Steam32 account id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="stratz.player_profile",
                            path="data.confirmed_steam_account_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
                "take": ArgContract(
                    description="Number of hero rows to return (1-50)."
                ),
                "match_take": ArgContract(
                    description=(
                        "Match sample size per hero (recent N matches). Use this for "
                        "'近 N 场'. Optional — omit to use STRATZ default."
                    )
                ),
                "days": ArgContract(
                    description="Date window in days (within last N days). Optional."
                ),
                "min_match_count": ArgContract(
                    description=(
                        "Floor on games played; heroes below this are dropped "
                        "(filters small-sample noise in strong mode)."
                    )
                ),
                "selection_mode": ArgContract(
                    description="'strong' (rank by win_rate) or 'popular' (by games)."
                ),
            },
            metadata={"game": "dota2", "domain": "player_hero_performance"},
        )
    )


class HeroDailyTrendsInput(BaseModel):
    hero_id: int = Field(gt=0)
    take: int = Field(default=12, ge=1, le=12)


def hero_daily_trends_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    daily = data.get("daily_buckets")
    if not isinstance(daily, list):
        return []
    names = _hero_name_index()
    hero_id = data.get("hero_id")
    hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
    hero_label = hero_name or hero_id
    evidence: list[EvidenceItem] = []
    for index, row in enumerate(daily):
        if not isinstance(row, dict):
            continue
        day = row.get("day")
        evidence.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:hero_daily_trend:{hero_id}:{day}:{index}",
                kind="hero_daily_trend",
                subject=f"{hero_label} daily trend (day {day})",
                value={
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "day": day,
                    "win_count": row.get("win_count"),
                    "match_count": row.get("match_count"),
                    "win_rate": row.get("win_rate"),
                    "win_rate_basis": "day: winCount/matchCount",
                    "filters": {
                        **filters,
                        "win_rate_basis": "day: winCount/matchCount",
                    },
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return evidence


def _hero_daily_trends_handler(settings: Settings):
    async def handle(
        args: HeroDailyTrendsInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        bracket_full = basic_to_full(context.bracket)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            data = await _with_retry(
                lambda: heroes.hero_win_day(
                    args.hero_id,
                    take=args.take,
                    bracket_ids=bracket_full,
                    position_ids=context.position_ids,
                    region_ids=context.region_ids,
                    game_mode_ids=context.game_mode_ids,
                )
            )
        finally:
            await transport.aclose()

        daily = data.get("daily", []) if isinstance(data, dict) else []
        return {
            "hero_id": args.hero_id,
            "daily_buckets": daily,
            "filters": {
                "take": args.take,
                "bracket_basic_ids": context.bracket,
                "bracket_full_ids": bracket_full,
                "position_ids": context.position_ids,
                "region_ids": context.region_ids,
                "game_mode_ids": context.game_mode_ids,
                "grain": "day",
            },
        }

    return handle


class FilterHeroesByPositionInput(BaseModel):
    candidate_rows: list[dict[str, Any]] = Field(min_length=1)
    position_id: str
    # keep in sync with policy.yaml planning.sample_policy
    # .tools[stratz.filter_heroes_by_position].default
    min_position_match_count: int = Field(default=1000, ge=0)


def filter_heroes_by_position_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    filtered = data.get("filtered_rows")
    if not isinstance(filtered, list):
        return []
    names = _hero_name_index()
    evidence: list[EvidenceItem] = []
    for index, row in enumerate(filtered):
        if not isinstance(row, dict):
            continue
        hero_id = row.get("hero_id")
        hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
        # Detect original ranking caliber from the carried row fields.
        if "matchup_win_rate" in row:
            caliber = "matchup: winCount/matchCount"
        elif "pair_win_rate" in row:
            caliber = "ally_pair: winCount/matchCount"
        else:
            caliber = None
        value: dict[str, Any] = {
            **row,
            "hero_name": hero_name,
        }
        if caliber:
            value["win_rate_basis"] = caliber
        value["filters"] = {
            **filters,
            **({"win_rate_basis": caliber} if caliber else {}),
        }
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:role_filtered_candidate_row:"
                    f"{hero_id}:{index}"
                ),
                kind="role_filtered_candidate_row",
                subject=(
                    f"{hero_name or hero_id} at {row.get('position')} "
                    f"({row.get('source_side', 'ranked')})"
                ),
                value=value,
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return evidence


def _filter_heroes_by_position_handler(settings: Settings):
    async def handle(
        args: FilterHeroesByPositionInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        # Single latest completed week — this is a join, not a per-week fan-out.
        _weeks, epochs = _resolve_week_window(context.weeks_back)
        latest_epoch = epochs[0]
        candidate_rows = args.candidate_rows
        candidate_hero_ids = {
            row.get("hero_id")
            for row in candidate_rows
            if isinstance(row, dict) and isinstance(row.get("hero_id"), int)
        }

        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        try:
            position_rows = await _with_retry(
                lambda: heroes.hero_position_stats(
                    position_ids=[args.position_id],
                    bracket_basic_ids=context.bracket,
                    week=latest_epoch,
                )
            )
        finally:
            await transport.aclose()

        # Index heroes that have enough sample at this position.
        position_index = {
            row["hero_id"]: row
            for row in position_rows
            if isinstance(row, dict)
            and isinstance(row.get("hero_id"), int)
            and (row.get("match_count") or 0) >= args.min_position_match_count
        }

        filtered: list[dict[str, Any]] = []
        dropped: list[int] = []
        for row in candidate_rows:
            if not isinstance(row, dict):
                continue
            hero_id = row.get("hero_id")
            if not isinstance(hero_id, int):
                continue
            pos = position_index.get(hero_id)
            if pos is None:
                dropped.append(hero_id)
                continue
            # Thin relay: carry the ORIGINAL ranking row + attach position sample.
            # No composite role score is invented.
            filtered.append(
                {
                    **row,
                    "position": args.position_id,
                    "position_match_count": pos.get("match_count"),
                    "position_match_win_rate": pos.get("match_win_rate"),
                    "role_fit_basis": (
                        f"position_sample: matchCount@{args.position_id}"
                    ),
                }
            )

        return {
            "position_id": args.position_id,
            "filtered_rows": filtered,
            "dropped_hero_ids": sorted(set(dropped)),
            "filters": {
                "position_id": args.position_id,
                "min_position_match_count": args.min_position_match_count,
                "bracket_basic_ids": context.bracket,
                "week_epoch": latest_epoch,
                "candidate_count": len(candidate_rows),
                "candidate_hero_ids": sorted(candidate_hero_ids),
            },
        }

    return handle


def _rate(value: int | None, total: int | None) -> float | None:
    if not total or total <= 0:
        return None
    return round((value or 0) / total, 4)


def _kda(kills: int | None, deaths: int | None, assists: int | None) -> float | None:
    # deaths == 0 -> KDA undefined; relay None rather than inventing "perfect".
    if not deaths:
        return None
    return round(((kills or 0) + (assists or 0)) / deaths, 4)


def player_profile_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    profile = data.get("profile") or {}
    steam_id = data.get("confirmed_steam_account_id")
    if not profile.get("found"):
        return []
    win_count = profile.get("win_count")
    match_count = profile.get("match_count")
    basis = "player_global: winCount/matchCount"
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:player_identity:{steam_id}",
            kind="player_identity",
            subject=str(profile.get("name") or steam_id),
            value={
                "steam_account_id": steam_id,
                "name": profile.get("name"),
                "avatar": profile.get("avatar"),
                "season_rank": profile.get("season_rank"),
                "pro_name": profile.get("pro_name"),
                "match_count": match_count,
                "win_count": win_count,
                "global_win_rate": _rate(win_count, match_count),
                "win_rate_basis": basis,
                "imp": profile.get("imp"),
                "last_match_date": profile.get("last_match_date"),
                "filters": {**filters, "win_rate_basis": basis},
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def player_recent_matches_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    matches = data.get("matches") or []
    summary = data.get("summary") or {}
    names = _hero_name_index()
    steam_id = data.get("steam_account_id")
    basis = "stratz_native: MatchPlayerType.isVictory"
    evidence: list[EvidenceItem] = []
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            continue
        hero_id = match.get("hero_id")
        hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
        match_id = match.get("match_id")
        evidence.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:player_recent_match:{steam_id}:{match_id}:{index}",
                kind="player_recent_match",
                subject=(
                    f"{hero_name or hero_id} "
                    f"({'win' if match.get('win') else 'loss'})"
                ),
                value={
                    "steam_account_id": steam_id,
                    "match_id": match_id,
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "win": match.get("win"),
                    "win_rate_basis": basis,
                    "kills": match.get("kills"),
                    "deaths": match.get("deaths"),
                    "assists": match.get("assists"),
                    "kda": _kda(
                        match.get("kills"), match.get("deaths"), match.get("assists")
                    ),
                    "gold_per_minute": match.get("gold_per_minute"),
                    "experience_per_minute": match.get("experience_per_minute"),
                    "position": match.get("position"),
                    "lane": match.get("lane"),
                    "role": match.get("role"),
                    "duration": match.get("duration"),
                    "start_time": match.get("start_time"),
                    "lobby_type": match.get("lobby_type"),
                    "game_mode": match.get("game_mode"),
                    "level": match.get("level"),
                    "last_hits": match.get("last_hits"),
                    "denies": match.get("denies"),
                    "imp": match.get("imp"),
                    "filters": {**filters, "win_rate_basis": basis},
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    match_count = summary.get("match_count")
    summary_basis = "stratz_native: isVictory count / match_count"
    evidence.append(
        EvidenceItem(
            id=f"{result.tool_call_id}:player_recent_summary:{steam_id}",
            kind="player_recent_summary",
            subject=f"{steam_id} recent summary",
            value={
                "steam_account_id": steam_id,
                "match_count": match_count,
                "wins": summary.get("wins"),
                "losses": summary.get("losses"),
                "win_rate": _rate(summary.get("wins"), match_count),
                "win_rate_basis": summary_basis,
                "latest_match_time": summary.get("latest_match_time"),
                "filters": {**filters, "win_rate_basis": summary_basis},
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    )
    if match_count is not None:
        evidence.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:sample_size:player_recent:{steam_id}",
                kind="sample_size",
                subject=f"recent match sample for {steam_id}",
                value={
                    "sample_size": match_count,
                    "steam_account_id": steam_id,
                    "filters": filters,
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return evidence


def _player_profile_handler(settings: Settings):
    async def handle(args: PlayerProfileInput, context: QueryContext) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        players = StratzPlayers(transport)
        try:
            profile = await _with_retry(
                lambda: players.get_profile(args.steam_account_id)
            )
        finally:
            await transport.aclose()
        if not profile.get("found"):
            raise LookupError("player profile not found")
        return {
            "confirmed_steam_account_id": args.steam_account_id,
            "profile": profile,
            "filters": {"steam_account_id": args.steam_account_id},
        }

    return handle


def _player_recent_matches_handler(settings: Settings):
    async def handle(
        args: PlayerRecentMatchesInput, context: QueryContext
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")
        # Scope from plan.context (v2.5 boundary): bracket -> bracketIds(0-8),
        # position_ids passed through. region_ids/game_mode_ids intentionally NOT
        # read (v1 type mismatch; validator already rejects them on player plans).
        bracket_ids = basic_to_bracket_ids(context.bracket)
        position_ids = context.position_ids
        start_date_time = int(_now()) - args.days * 86400 if args.days else None
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        players = StratzPlayers(transport)
        try:
            matches = await _with_retry(
                lambda: players.get_recent_matches(
                    args.steam_account_id,
                    bracket_ids=bracket_ids,
                    position_ids=position_ids,
                    start_date_time=start_date_time,
                    take=args.take,
                )
            )
        finally:
            await transport.aclose()
        wins = sum(1 for m in matches if m.get("win") is True)
        losses = sum(1 for m in matches if m.get("win") is False)
        latest = max((m.get("start_time") or 0) for m in matches) if matches else None
        basis = "stratz_native: MatchPlayerType.isVictory"
        meaning = (
            f"within last {args.days} days, newest first, capped at {args.take} matches"
            if args.days
            else f"most recent {args.take} matches (newest first)"
        )
        return {
            "steam_account_id": args.steam_account_id,
            "matches": matches,
            "summary": {
                "match_count": len(matches),
                "wins": wins,
                "losses": losses,
                "latest_match_time": latest,
            },
            "filters": {
                "steam_account_id": args.steam_account_id,
                "bracket_basic_ids": context.bracket,
                "bracket_ids": bracket_ids,
                "position_ids": position_ids,
                "days": args.days,
                "take": args.take,
                "win_rate_basis": basis,
                "meaning": meaning,
            },
            "selection_policy": meaning,
        }

    return handle


def _hero_performance_meaning(args: PlayerHeroPerformanceInput) -> str:
    rank_by = "win_rate" if args.selection_mode == "strong" else "games played"
    parts = [
        f"top {args.take} heroes by {rank_by}",
        f"min {args.min_match_count} games each",
    ]
    if args.days:
        parts.append(f"within last {args.days} days")
    if args.match_take is not None:
        parts.append(f"stats from most recent {args.match_take} matches")
    return "; ".join(parts)


def player_hero_performance_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    heroes = data.get("heroes") or []
    names = _hero_name_index()
    steam_id = data.get("steam_account_id")
    basis = filters.get("win_rate_basis") or "player_hero: winCount/matchCount"
    evidence: list[EvidenceItem] = []
    for index, row in enumerate(heroes):
        if not isinstance(row, dict):
            continue
        hero_id = row.get("hero_id")
        hero_name = names.get(hero_id) if isinstance(hero_id, int) else None
        win_count = row.get("win_count")
        match_count = row.get("match_count")
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:player_hero_performance:"
                    f"{steam_id}:{hero_id}:{index}"
                ),
                kind="player_hero_performance",
                subject=f"{hero_name or hero_id} ({win_count}/{match_count})",
                value={
                    "steam_account_id": steam_id,
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "win_count": win_count,
                    "match_count": match_count,
                    "win_rate": row.get("win_rate"),
                    "win_rate_basis": basis,
                    "kda": row.get("kda"),
                    "avg_kills": row.get("avg_kills"),
                    "avg_deaths": row.get("avg_deaths"),
                    "avg_assists": row.get("avg_assists"),
                    "duration": row.get("duration"),
                    "gold_per_minute": row.get("gold_per_minute"),
                    "experience_per_minute": row.get("experience_per_minute"),
                    "imp": row.get("imp"),
                    "last_played_date_time": row.get("last_played_date_time"),
                    "filters": {**filters, "win_rate_basis": basis},
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    # Relay provider sample knobs verbatim; do not invent a single aggregate.
    # match_take caps the per-hero stat sample; returned_hero_match_sum covers
    # only the RETURNED heroes (a subset after min_match_count + take).
    evidence.append(
        EvidenceItem(
            id=f"{result.tool_call_id}:sample_size:player_hero:{steam_id}",
            kind="sample_size",
            subject=f"hero-performance sample for {steam_id}",
            value={
                "steam_account_id": steam_id,
                "match_take": filters.get("match_take"),
                "returned_hero_count": len(heroes),
                "returned_hero_match_sum": data.get("returned_hero_match_sum"),
                "filters": filters,
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    )
    return evidence


def _player_hero_performance_handler(settings: Settings):
    async def handle(
        args: PlayerHeroPerformanceInput, context: QueryContext
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")
        # Scope from plan.context: bracket -> rankIds(0-80, LIVE-LOCKED);
        # position_ids passed through. region/game_mode NOT read (v1 type
        # mismatch; validator already rejects them on player plans).
        rank_ids = basic_to_rank_ids(context.bracket)
        position_ids = context.position_ids
        start_date_time = int(_now()) - args.days * 86400 if args.days else None
        # Over-fetch hero rows in strong mode: heroesPerformance default order is
        # unconfirmed (inventory 🚦), and a low-play high-win hero may sit in the
        # tail if STRATZ sorts by games played. popular trusts provider order.
        if args.selection_mode == "strong":
            hero_row_take = min(max(args.take * 3, 50), 200)
        else:
            hero_row_take = args.take
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        players = StratzPlayers(transport)
        try:
            rows = await _with_retry(
                lambda: players.get_hero_performance(
                    args.steam_account_id,
                    rank_ids=rank_ids,
                    position_ids=position_ids,
                    start_date_time=start_date_time,
                    match_take=args.match_take,
                    hero_row_take=hero_row_take,
                )
            )
        finally:
            await transport.aclose()
        # win_rate derived locally (STRATZ has no native winRate on this type).
        for row in rows:
            row["win_rate"] = _rate(row.get("win_count"), row.get("match_count"))
        kept = [r for r in rows if (r.get("match_count") or 0) >= args.min_match_count]
        if args.selection_mode == "strong":
            kept.sort(
                key=lambda r: (r.get("win_rate") or 0, r.get("match_count") or 0),
                reverse=True,
            )
        else:
            kept.sort(key=lambda r: r.get("match_count") or 0, reverse=True)
        top = kept[: args.take]
        basis = "player_hero: winCount/matchCount"
        meaning = _hero_performance_meaning(args)
        return {
            "steam_account_id": args.steam_account_id,
            "heroes": top,
            "filters": {
                "steam_account_id": args.steam_account_id,
                "bracket_basic_ids": context.bracket,
                "rank_ids": rank_ids,
                "position_ids": position_ids,
                "days": args.days,
                "match_take": args.match_take,
                "min_match_count": args.min_match_count,
                "selection_mode": args.selection_mode,
                "hero_row_take": hero_row_take,
                "win_rate_basis": basis,
                "meaning": meaning,
            },
            "selection_policy": meaning,
            "returned_hero_match_sum": sum(
                (r.get("match_count") or 0) for r in top
            ),
        }

    return handle


def build_default_tool_registry(settings: Settings) -> ToolRegistry:
    from app.agentic.tools.conversation_tools import register_conversation_tools
    from app.agentic.tools.dota_catalog_tools import register_dota_catalog_tools
    from app.agentic.tools.opendota_tools import register_opendota_tools
    from app.agentic.tools.patch_tools import register_patch_tools

    registry = ToolRegistry()
    register_dota_catalog_tools(registry)
    register_stratz_tools(registry, settings)
    register_opendota_tools(registry, settings)
    register_patch_tools(registry)
    register_conversation_tools(registry)
    return registry


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
                    "win_rate_basis": "match: matchWinCount/matchCount",
                    "win_count": pair.get("win_count"),
                    "loss_count": pair.get("loss_count"),
                    "draw_count": pair.get("draw_count"),
                    "stomp_win_count": pair.get("stomp_win_count"),
                    "stomp_loss_count": pair.get("stomp_loss_count"),
                    "cs_count": pair.get("cs_count"),
                    "week_epoch": week_epoch,
                    "week_index": week_index,
                    "window_label": window_label,
                    "filters": {
                        **filters,
                        "win_rate_basis": "match: matchWinCount/matchCount",
                    },
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
                        "matchup_win_rate": row.get("matchup_win_rate"),
                        "pair_wilson_rating": row.get("pair_wilson_rating"),
                        "wilson_provenance": _WILSON_PROVENANCE,
                        "win_rate_basis": "matchup: winCount/matchCount",
                        "match_count": match_count,
                        "synergy": row.get("synergy"),
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
                        "filters": {
                            **filters,
                            "win_rate_basis": "matchup: winCount/matchCount",
                        },
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


def hero_synergy_ranking_evidence(result: ToolResult) -> list[EvidenceItem]:
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
                        f"{result.tool_call_id}:hero_synergy_ranking_row:"
                        f"{source_side}:{hero_id}:{week_epoch}:{index}"
                    ),
                    kind="hero_synergy_ranking_row",
                    subject=f"{hero_label} with {resolved_target_label} ({window_label})",
                    value={
                        "source_side": source_side,
                        "hero_id": hero_id,
                        "hero_name": hero_name,
                        "target_hero_id": resolved_target_id,
                        "target_hero_name": resolved_target_name,
                        "pair_win_rate": row.get("pair_win_rate"),
                        "pair_wilson_rating": row.get("pair_wilson_rating"),
                        "wilson_provenance": _WILSON_PROVENANCE,
                        "win_rate_basis": "ally_pair: winCount/matchCount",
                        "match_count": match_count,
                        "synergy": row.get("synergy"),
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
                        "filters": {
                            **filters,
                            "win_rate_basis": "ally_pair: winCount/matchCount",
                        },
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
                            f"{result.tool_call_id}:sample_size:synergy:"
                            f"{source_side}:{hero_id}:{week_epoch}:{index}"
                        ),
                        kind="sample_size",
                        subject=f"{hero_label} with {resolved_target_label} ({window_label})",
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
                        "wilson_rating": row.get("wilson_rating"),
                        "wilson_provenance": _WILSON_PROVENANCE_MATCH,
                        "win_rate_basis": "match: matchWinCount/matchCount",
                        "stomp_win_count": row.get("stomp_win_count"),
                        "stomp_loss_count": row.get("stomp_loss_count"),
                        "cs_count": row.get("cs_count"),
                        "is_with": data.get("is_with"),
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
                        "filters": {
                            **filters,
                            "win_rate_basis": "match: matchWinCount/matchCount",
                        },
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
                        subject=(
                            f"lane meta sample for {hero_label} + "
                            f"{target_label} ({window_label})"
                        ),
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
                        "match_win_rate": row.get("match_win_rate"),
                        "wilson_rating": row.get("wilson_rating"),
                        "wilson_provenance": _WILSON_PROVENANCE,
                        "win_count": row.get("win_count"),
                        "win_rate_basis": "match: winCount/matchCount",
                        "week_epoch": week_epoch,
                        "week_index": week_index,
                        "window_label": window_label,
                        "filters": {
                            **filters,
                            "win_rate_basis": "match: winCount/matchCount",
                        },
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
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:

            def _pair_lane_rows(records: Any) -> list[dict[str, Any]]:
                matches = [
                    record
                    for record in records
                    if isinstance(record, dict)
                    and record.get("hero_id") == args.partner_hero_id
                ]
                return [matches[0]] if matches else []

            buckets = await _fan_out_weeks(
                epochs,
                lambda e: heroes.lane_outcome(
                    args.hero_id,
                    is_with=args.is_with,
                    week=e,
                    bracket_basic_ids=context.bracket,
                    position_ids=context.position_ids,
                ),
                _pair_lane_rows,
            )
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
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:

            def _ranked_rows(data: Any) -> list[dict[str, Any]]:
                advantage = _filter_matchup_rows(
                    data.get("advantage", []), args.min_sample_size, args.take
                )
                disadvantage = _filter_matchup_rows(
                    data.get("disadvantage", []), args.min_sample_size, args.take
                )
                return [
                    {"source_side": "advantage", **row} for row in advantage
                ] + [
                    {"source_side": "disadvantage", **row} for row in disadvantage
                ]

            buckets = await _fan_out_weeks(
                epochs,
                lambda e: heroes.hero_vs_hero_matchup(
                    args.hero_id,
                    take=max(args.take, 50),
                    week=e,
                    bracket_basic_ids=context.bracket,
                ),
                _ranked_rows,
            )
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "hero_id": args.hero_id,
            "side": args.side,
            "weekly_buckets": buckets,
            "candidate_rows": (buckets[0]["rows"] if buckets else []),
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
            "selection_policy": (
                "per_completed_week: sorted_by=synergy desc, match_count desc, "
                f"min_sample_size>={args.min_sample_size}, top={args.take}, "
                "groups=advantage+disadvantage kept separate"
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


def _hero_synergy_ranking_handler(settings: Settings):
    async def handle(
        args: HeroSynergyRankingInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:

            def _ranked_rows(data: Any) -> list[dict[str, Any]]:
                advantage = _filter_matchup_rows(
                    data.get("advantage", []), args.min_sample_size, args.take
                )
                disadvantage = _filter_matchup_rows(
                    data.get("disadvantage", []), args.min_sample_size, args.take
                )
                return [
                    {"source_side": "advantage", **row} for row in advantage
                ] + [
                    {"source_side": "disadvantage", **row} for row in disadvantage
                ]

            buckets = await _fan_out_weeks(
                epochs,
                lambda e: heroes.hero_synergy_matchup(
                    args.hero_id,
                    take=max(args.take, 50),
                    week=e,
                    bracket_basic_ids=context.bracket,
                ),
                _ranked_rows,
            )
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        return {
            "hero_id": args.hero_id,
            "side": args.side,
            "weekly_buckets": buckets,
            "candidate_rows": (buckets[0]["rows"] if buckets else []),
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
            "selection_policy": (
                "per_completed_week: sorted_by=synergy desc, match_count desc, "
                f"min_sample_size>={args.min_sample_size}, top={args.take}, "
                "groups=advantage+disadvantage kept separate"
            ),
        }

    return handle


def _lane_meta_global_handler(settings: Settings):
    async def handle(
        args: LaneMetaGlobalInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:

            def _lane_meta_rows(records: Any) -> list[dict[str, Any]]:
                deduped = _dedupe_pair_rows(records)
                qualifying = [
                    record
                    for record in deduped
                    if isinstance(record, dict)
                    and (record.get("match_count") or 0) >= args.min_sample_size
                ]
                for r in qualifying:
                    r["wilson_rating"] = wilson_lower_bound(
                        int(r.get("match_win_count") or 0),
                        int(r.get("match_count") or 0),
                    )
                if args.selection_mode == "strong":
                    # Strongest, most reliable pairs: Wilson lower bound of the
                    # match win rate (confidence-aware); match_count breaks ties.
                    qualifying.sort(
                        key=lambda r: (
                            float(r.get("wilson_rating") or 0),
                            int(r.get("match_count") or 0),
                        ),
                        reverse=True,
                    )
                else:  # popular
                    qualifying.sort(
                        key=lambda r: int(r.get("match_count") or 0), reverse=True
                    )
                top = qualifying[: args.highlight_top]
                for row in top:
                    row.pop("position", None)
                return top

            buckets = await _fan_out_weeks(
                epochs,
                lambda e: heroes.lane_outcome(
                    None,
                    is_with=args.is_with,
                    week=e,
                    bracket_basic_ids=context.bracket,
                ),
                _lane_meta_rows,
            )
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        sort_clause = (
            "wilson_rating desc, match_count desc"
            if args.selection_mode == "strong"
            else "match_count desc"
        )
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
                    "selection_mode": args.selection_mode,
                },
                weeks,
                epochs,
            ),
            "selection_policy": (
                "per_completed_week: "
                "deduped=keep_larger_match_count_mirror, "
                f"selection_mode={args.selection_mode}, "
                f"min_sample_size>={args.min_sample_size}, "
                f"sorted_by={sort_clause}, top={args.highlight_top}"
            ),
        }

    return handle


def _hero_position_stats_handler(settings: Settings):
    async def handle(
        args: HeroPositionStatsInput,
        context: QueryContext,
    ) -> dict[str, Any]:
        if not settings.stratz_token:
            raise ValueError("DOTAMIND_STRATZ_TOKEN is required")

        weeks, epochs = _resolve_week_window(context.weeks_back)
        transport = StratzTransport(settings.stratz_graphql_url, settings.stratz_token)
        heroes = StratzHeroes(transport)
        buckets: list[dict[str, Any]] = []
        try:

            def _position_rows(rows: Any) -> list[dict[str, Any]]:
                rows = [
                    r
                    for r in rows
                    if isinstance(r, dict)
                    and (r.get("match_count") or 0) >= args.min_sample_size
                ]
                for r in rows:
                    r["wilson_rating"] = wilson_lower_bound(
                        int(r.get("win_count") or 0),
                        int(r.get("match_count") or 0),
                    )
                if args.selection_mode == "strong":
                    rows.sort(
                        key=lambda r: (
                            float(r.get("wilson_rating") or 0),
                            int(r.get("match_count") or 0),
                        ),
                        reverse=True,
                    )
                else:  # popular
                    rows.sort(
                        key=lambda r: int(r.get("match_count") or 0), reverse=True
                    )
                if args.position_id is not None:
                    rows = rows[: args.take]
                return rows

            buckets = await _fan_out_weeks(
                epochs,
                lambda e: heroes.hero_position_stats(
                    hero_ids=[args.hero_id] if args.hero_id is not None else None,
                    position_ids=[args.position_id] if args.position_id is not None else None,
                    bracket_basic_ids=context.bracket,
                    week=e,
                ),
                _position_rows,
            )
        finally:
            await transport.aclose()

        weeks_with_record, missing_epochs = _week_summary(buckets)
        sort_clause = (
            "wilson_rating desc, match_count desc"
            if args.selection_mode == "strong"
            else "match_count desc"
        )
        return {
            "hero_id": args.hero_id,
            "position_id": args.position_id,
            "weekly_buckets": buckets,
            "weeks_with_record": weeks_with_record,
            "missing_week_epochs": missing_epochs,
            "filters": _window_filters(
                {
                    "bracket_basic_ids": context.bracket,
                    "min_sample_size": args.min_sample_size,
                    "selection_mode": args.selection_mode,
                },
                weeks,
                epochs,
            ),
            "selection_policy": (
                "per_completed_week: "
                f"selection_mode={args.selection_mode}, "
                f"min_sample_size>={args.min_sample_size}, "
                f"sorted_by={sort_clause}"
                + (f", top={args.take}" if args.position_id is not None else "")
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
    # Sample-confidence co-signal: Wilson lower bound of the pairing's win rate.
    # Primary ranking stays STRATZ synergy (advantage/synergy formula); pair_wilson
    # only flags how reliable each pairing's sample is — do NOT merge into a score.
    for r in filtered:
        r["pair_wilson_rating"] = wilson_lower_bound(
            int(r.get("win_count") or 0),
            int(r.get("match_count") or 0),
        )
    filtered.sort(
        key=lambda r: (
            float(r.get("synergy") or 0),
            int(r.get("match_count") or 0),
        ),
        reverse=True,
    )
    return filtered[:take]


async def _fan_out_weeks(
    epochs: list[int],
    fetch_one: Callable[[int], Awaitable[Any]],
    transform: Callable[[Any], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Per-week fan-out: for each completed-week epoch, fetch one result (via
    _with_retry) and apply `transform` to produce that week's rows. Buckets are
    never merged across weeks. Sorting/filtering/top-K live inside `transform`
    (agentic layer); the integration layer is not involved here."""
    buckets: list[dict[str, Any]] = []
    for week_index, epoch in enumerate(epochs, start=1):
        raw = await _with_retry(lambda e=epoch: fetch_one(e))
        buckets.append(_bucket(epoch, week_index, transform(raw)))
    return buckets


# --- STRATZ week-window resolution -----------------------------------------
# A STRATZ week is 604800s-aligned to the Unix epoch; verified live that
# `week` is a single weekly bucket and `null` means the latest *completed*
# week (see docs/design/tools/time_patch_filtering.md). Handlers resolve a relative
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
