"""Natural-language Answer prompt and message renderer."""

from __future__ import annotations

import json

from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan

ANSWER_CORE_RULES = (
    "You write concise evidence-grounded Dota 2 answers. "
    "Use only the provided evidence graph. Do not invent stats. "
    "If the evidence is insufficient, say exactly what is missing. "
    "Use current_query for the user's latest presentation wording and "
    "reconstructed_goal for the complete request reconstructed from conversation. "
    "Preserve explicit focus, exclusions, requested result count, and detail level; "
    "do not broaden the answer beyond them."
)

CATALOG_FACT_RULES = (
    "For Catalog facts, use only normalized text and values from the relevant "
    "Catalog evidence. Disclose the Catalog snapshot patch and generated_at when "
    "the requested facts are Catalog-backed hero, ability, talent, or item "
    "definitions. Catalog metadata describes only that static definition source. "
    "Do not expose Catalog internal_name values or other internal schema labels."
)

HERO_ATTRIBUTE_RULES = (
    "For hero_attributes evidence, distinguish base attribute values from "
    "per-level gains."
)

HERO_ABILITY_RULES = (
    "For hero_ability evidence, preserve ability level arrays instead of "
    "collapsing them into one number. Distinguish normal abilities, innate "
    "abilities, Scepter grants/upgrades, and Shard grants/upgrades from their "
    "explicit flags and text. Never expose flags or token names such as "
    "`has_shard = true`, `has_scepter`, `is_innate`, or `special_bonus_*`; "
    "translate them into natural headings such as 魔晶升级, 神杖升级, or 先天技能. "
    "Never infer skill leveling priority, popularity, or recommendations from "
    "static ability definitions. Talent-bonus entries inside ability special_values "
    "must not create a separate 相关天赋 section and must not be shown as internal "
    "token references beside a value. For a complete hero ability-list query, "
    "follow Catalog ability order and describe each requested ability with natural "
    "classification (normal, ultimate, innate, or sub-ability where supported), "
    "Chinese/English name, effect, levels, cast/cooldown/cost arrays, key values, "
    "and natural-language upgrades. Do not add separate 技能分类汇总 or 相关天赋 "
    "sections. For a single-ability query, output only the one ability matching "
    "the user's name. Do not output other abilities, a classification summary, a "
    "related-talents section, or the full talent tree unless the user explicitly "
    "also asked for talents."
)

HERO_TALENT_RULES = (
    "For hero_talent_tree evidence within the requested scope, present talents by "
    "level 10/15/20/25 and left/right side in a concise Markdown table with "
    "columns `等级 | 左侧天赋（中文 / English） | 右侧天赋（中文 / English）`. "
    "Do not expose `talent_internal_name` or `special_bonus_*`, repeat schema "
    "explanations, or infer talent win rate, popularity, or recommendations from "
    "static talent definitions."
)

ITEM_DEFINITION_RULES = (
    "For item_definition evidence, distinguish the final item from a recipe item, "
    "components, and upgrade targets. For a basic item, show only its name as "
    "`中文名（English）`, price, and attributes; do not invent a recipe table. "
    "Never infer item-build strength, popularity, or recommendations from static "
    "item definitions."
)

ITEM_RECIPE_RULES = (
    "For item_recipe evidence, render a Markdown table with columns "
    "`组件（中文名（English）） | 价格 | 属性`. Include every component and include "
    "the recipe scroll as an explicit row. Use each row's "
    "special_values/rendered display attributes; do not place Chinese and English "
    "names in mismatched columns. A recipe-scroll row with no display attributes "
    "may say `无`. Use cost_breakdown to verify and report the total price; explain "
    "a mismatch in natural language only when the calculated and finished-item "
    "prices differ, without exposing internal field names. If recipe_items "
    "evidence exists, never claim that the item has no recipe scroll."
)

STRATZ_METADATA_BOUNDARY_RULES = (
    "For STRATZ statistics, attribute the facts to STRATZ and their own query "
    "window, filters, and sample metadata. Catalog patch/generated_at carried by "
    "identity evidence describes only the static Catalog snapshot and must not be "
    "presented as a STRATZ patch, statistics snapshot, or statistics version. Do "
    "not disclose that Catalog metadata when the requested facts are solely STRATZ "
    "statistics. If the answer includes both Catalog definitions and STRATZ "
    "statistics, attribute each source's metadata locally to the relevant section."
)

MATCH_SOURCE_BOUNDARY_RULES = (
    "For competition and match evidence, attribute schedule, stage, team, status, "
    "score, and PandaScore Match/Game identifiers to PandaScore Fixture data. "
    "PandaScore `pandascore_match_id` and `pandascore_game_id` are provider ids; "
    "they are not Valve `valve_match_id`. Attribute result, player scoreboard, "
    "parse coverage, and picks/bans to OpenDota's Valve match and replay parsing. "
    "Do not treat PandaScore detailed_stats as OpenDota has_parsed. If OpenDota "
    "parse coverage or draft evidence is absent, say that the match is not parsed "
    "or the BP is unavailable; never claim a completed draft from an empty list."
)

WEEKLY_TREND_RULES = (
    "When evidence items carry week_index/week_epoch (per-week STRATZ buckets), "
    "compare across weeks and state the trend (rising/falling/stable). If any "
    "requested week returned no sample (missing_week_epochs), say so explicitly. "
    "The default one-week STRATZ query is only the current query window, not a "
    "system limitation: say that multiple completed weeks can be queried when no "
    "cross-week comparison was requested."
)

PAIR_LANE_RULES = (
    "For pair_lane_outcome evidence, distinguish lane outcome from match outcome. "
    "Report lane_win_rate, lane_draw_rate, and lane_loss_rate using the supplied "
    "five-category lane counts, and report match_win_rate separately from "
    "match_win_count/match_count. When a pair lane query is present, include both "
    "the lane result and the match result by default. Use filters.position_ids as "
    "the only position scope; null means the query was not position-scoped. Never "
    "expose or interpret a raw response-row position as the requested lane. Do not "
    "infer gameplay causes, comeback ability, mid-game strength, late-game "
    "strength, or causal explanations solely because match_win_rate differs from "
    "lane_win_rate. Report the statistical difference directly. Do not add "
    "unsupported gameplay interpretations or hypotheses. Only provide a causal "
    "or gameplay explanation when it is explicitly supported by the evidence "
    "graph, and attribute it to that evidence."
)

LANE_POSITION_RANKING_RULES = (
    "When lane_meta_row/position_stat evidence carries filters.selection_mode, "
    "phrase the ranking basis to match it: 'strong' = top rows ranked by "
    "wilson_rating after the sample-size floor (say so, e.g. \"按 Wilson 评分"
    "(置信度加权胜率) 排序的前 K 个\"); 'popular' = ranked by pick volume. Always "
    "state the sample floor (filters.min_sample_size) and that only completed "
    "weeks count."
)

MATCHUP_SYNERGY_RULES = (
    "For counter/synergy recommendations (matchup_ranking_row / "
    "hero_synergy_ranking_row), the PRIMARY ranking is STRATZ `synergy` — keep it "
    "first. `pair_wilson_rating` is a sample-confidence CO-SIGNAL: among comparable "
    "synergy prefer higher pair_wilson_rating, and flag low pair_wilson_rating as "
    "small-sample/uncertain. Do NOT merge synergy and pair_wilson_rating into a "
    "single composite score."
)

DAILY_TREND_RULES = (
    "When hero_daily_trend evidence is present (per-day STRATZ buckets, "
    "filters.grain == 'day'), describe the trend across calendar days, not weeks — "
    "name days/dates and the day-level win_rate direction; do not invent week "
    "buckets. day evidence uses win_rate_basis 'day: winCount/matchCount'."
)

CATALOG_DEFINITION_KINDS = frozenset(
    {
        "hero_attributes",
        "hero_ability",
        "hero_talent_tree",
        "item_definition",
        "item_recipe",
    }
)
WEEKLY_STRATZ_KINDS = frozenset(
    {
        "pair_lane_outcome",
        "lane_meta_row",
        "position_stat",
        "matchup_ranking_row",
        "hero_synergy_ranking_row",
    }
)
MATCH_EVIDENCE_KINDS = frozenset(
    {
        "competition_identity",
        "tournament_stage",
        "match_schedule",
        "match_state",
        "series_score",
        "match_identity",
        "series_context",
        "valve_match_identity",
        "match_result",
        "player_scoreboard",
        "match_parse_status",
        "match_draft",
    }
)


def _active_evidence_kinds(graph: EvidenceGraph) -> set[str]:
    return set(graph.required_evidence) | {item.kind for item in graph.evidence}


def _has_stratz_source(graph: EvidenceGraph) -> bool:
    sources = [item.source for item in graph.evidence]
    sources.extend(result.source for result in graph.tool_results)
    return any(source is not None and source.name == "STRATZ" for source in sources)


def _has_match_source(graph: EvidenceGraph) -> bool:
    sources = [item.source for item in graph.evidence]
    sources.extend(result.source for result in graph.tool_results)
    return any(
        source is not None and source.name in {"PandaScore", "OpenDota"}
        for source in sources
    )


def render_natural_language_system_prompt(graph: EvidenceGraph) -> str:
    """Render only the Answer rules relevant to the requested/available evidence."""

    kinds = _active_evidence_kinds(graph)
    sections = [ANSWER_CORE_RULES]

    if kinds & CATALOG_DEFINITION_KINDS:
        sections.append(CATALOG_FACT_RULES)
    if "hero_attributes" in kinds:
        sections.append(HERO_ATTRIBUTE_RULES)
    if "hero_ability" in kinds:
        sections.append(HERO_ABILITY_RULES)
    if "hero_talent_tree" in kinds:
        sections.append(HERO_TALENT_RULES)
    if "item_definition" in kinds:
        sections.append(ITEM_DEFINITION_RULES)
    if "item_recipe" in kinds:
        sections.append(ITEM_RECIPE_RULES)
    if _has_stratz_source(graph):
        sections.append(STRATZ_METADATA_BOUNDARY_RULES)
    if kinds & MATCH_EVIDENCE_KINDS or _has_match_source(graph):
        sections.append(MATCH_SOURCE_BOUNDARY_RULES)
    if kinds & WEEKLY_STRATZ_KINDS:
        sections.append(WEEKLY_TREND_RULES)
    if "pair_lane_outcome" in kinds:
        sections.append(PAIR_LANE_RULES)
    if kinds & {"lane_meta_row", "position_stat"}:
        sections.append(LANE_POSITION_RANKING_RULES)
    if kinds & {"matchup_ranking_row", "hero_synergy_ranking_row"}:
        sections.append(MATCHUP_SYNERGY_RULES)
    if "hero_daily_trend" in kinds:
        sections.append(DAILY_TREND_RULES)

    return "\n\n".join(sections)


def render_natural_language_answer_messages(
    plan: ExecutionPlan,
    graph: EvidenceGraph,
    *,
    current_query: str | None = None,
) -> list[dict[str, str]]:
    request_context = {
        "current_query": current_query or plan.goal,
        "reconstructed_goal": plan.goal,
    }
    return [
        {"role": "system", "content": render_natural_language_system_prompt(graph)},
        {
            "role": "user",
            "content": (
                "request_context="
                f"{json.dumps(request_context, ensure_ascii=False)}\n"
                f"required_evidence={graph.required_evidence}\n"
                f"evidence_graph={graph.model_dump(mode='json')}"
            ),
        },
    ]
