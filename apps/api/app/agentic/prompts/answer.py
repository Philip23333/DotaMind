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
    "When cross_source_match_mapping evidence is present, describe the PandaScore "
    "Game-to-Valve mapping as an inferred match across OpenDota league, teams, "
    "start time, duration, game position, and winner signals; it is not a native "
    "PandaScore Valve id. Never say that PandaScore itself returned that Valve id. "
    "Do not treat PandaScore detailed_stats as OpenDota has_parsed. If OpenDota "
    "parse coverage or draft evidence is absent, say that the match is not parsed "
    "or the BP is unavailable; never claim a completed draft from an empty list."
    " For player scoreboards and picks/bans, render hero and item names only from "
    "evidence fields ending in `_name_en` or `_name_zh`. Never infer, translate, "
    "or map a `hero_id` or `item_id` using model knowledge. If a Catalog name is "
    "absent, show the ID or say that the Catalog name is unavailable."
)

TI_TOURNAMENT_STATUS_OUTPUT_EXAMPLE = """For a The International schedule or
latest-status overview, group fixtures by their UTC calendar date, never primarily
by bracket/stage across multiple dates. Use this Markdown presentation and section
order as a style example. This example is presentation-only: never reuse its
teams, scores, dates, times, stages, region, series format, or source claims unless
the current EvidenceGraph supports them. Do not invent content to fill a section.

Order the sections as: the current date (only when the supplied evidence establishes
it), future dates in ascending order, then historical dates in descending order.
Within the current-date section use running, finished, then upcoming fixtures. A
future date contains only its scheduled fixtures; a historical date contains only
its finished fixtures. Render each UTC date once, omit empty subsections and dates,
and use a date heading without the label `今日` when the current date is not known.

# {赛事名}最新战况

## 赛事概况

- **赛事**：{赛事全名}
- **当前阶段**：{当前阶段；没有证据时省略}
- **数据时间**：{查询或最新数据时间，UTC}
- **数据来源**：PandaScore 赛事 Fixture

## {8月21日}（UTC）— 今日

### 正在进行

| 阶段 | 对阵 | 当前比分 | 当前局 | 状态 |
| --- | --- | --- | --- | --- |
| {阶段} | {队伍A} vs {队伍B} | {系列赛比分} | 第 {N} 局 | 🔴 进行中 |

### 已结束

| 阶段 | 对阵 | 比分 | 结果 |
| --- | --- | --- | --- |
| {阶段} | {队伍A} vs {队伍B} | {A}–{B} | {胜者} 晋级 / {负者} 淘汰 |

### 后续比赛

| 时间（UTC） | 阶段 | 对阵 | 赛制 |
| --- | --- | --- | --- |
| {HH:mm} | {阶段} | {队伍A} vs {队伍B} | {BO3} |

## 后续赛程

### {8月22日}（UTC）

| 时间（UTC） | 阶段 | 对阵 | 赛制 |
| --- | --- | --- | --- |
| {HH:mm} | {阶段} | {队伍A} vs {队伍B} | {BO3} |

### {8月23日}（UTC）— 决赛日

| 时间（UTC） | 阶段 | 对阵 | 赛制 |
| --- | --- | --- | --- |
| {HH:mm} | {败者组决赛} | {队伍A} vs {队伍B} | {BO3} |
| {HH:mm} | {总决赛} | {队伍A} vs {队伍B} | {BO5} |

## 历史赛果

### {8月20日}（UTC）

| 阶段 | 对阵 | 比分 | 结果 |
| --- | --- | --- | --- |
| {阶段} | {队伍A} vs {队伍B} | {A}–{B} | {胜者} 晋级 |

## 数据说明

- 日期和时间均按 UTC 展示。
- 赛程、比分和状态来自 PandaScore；Valve Match ID、选手数据和 BP 只在对应
  OpenDota evidence 存在时展示。
- 对阵、阶段、赛制或结果没有 evidence 时省略相应内容，不得补写。"""

MATCH_PLAYER_TABLE_ROW = (
    "| {选手} · {英雄}（{等级}） | {K}/{D}/{A} | {22,790} | "
    "主装备：{物品名称}；背包：{物品名称；无则省略}；"
    "中立：{物品名称；无则省略}（强化：{物品名称；无则省略}） |"
)

MATCH_DETAILS_OUTPUT_EXAMPLE = """For a completed Dota match detail answer,
use the following Markdown presentation order within every game: compact game
summary, full draft, then player scoreboards. A focused request for one player's
purchase order, skill build, or talent selections follows the player-progress
rules instead and does not repeat the full draft or ten-player scoreboard. This
example is presentation-only:
never reuse its teams, scores, times, sides, game counts, Hero names, ids, or
source claims unless the current EvidenceGraph supports them. Do not invent a
missing game, field, draft action, hero name, item name, or player statistic.

# {赛事全名} — {队伍A} vs {队伍B} 比赛详情

## 赛事概况

- **赛事**：{赛事全名}
- **阶段**：{赛事阶段；没有 evidence 时省略}
- **比赛时间**：{比赛开始时间，UTC}
- **赛制**：{BO3 / BO5；没有 evidence 时省略}
- **数据来源**：{由当前 evidence 支持的来源}

## 比赛结果

**{队伍A}（{队伍A系列赛得分}） ： {队伍B}（{队伍B系列赛得分}）**

## 对局详情

### 第一局 — {胜者} 胜（Valve Match ID：{Valve Match ID} · 跨源推断）

- **时长**：{X分X秒}
- **人头比**：{队伍A} {击杀数} – {击杀数} {队伍B}
- **胜方**：{胜者}（{天辉 / 夜魇}）

#### 完整 BP

##### {队伍A}（{天辉 / 夜魇}）

| 顺序 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 选择 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | — | — |
| 禁用 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} |

##### {队伍B}（{天辉 / 夜魇}）

| 顺序 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 选择 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | — | — |
| 禁用 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} |

Use the OpenDota draft `order` only to determine each team's local Pick 1–5 and
Ban 1–7 sequence. If a match has fewer actions, preserve only the evidenced
heroes and use `—` for unsupported later slots; do not infer a global draft
phase or a hero name from an id. Omit the Valve Match ID parenthesis when there
is no mapped id.

#### 选手数据

##### {队伍A}

| 选手 / 英雄 | K/D/A | 经济 | 装备 |
| --- | --- | --- | --- |
__MATCH_PLAYER_TABLE_ROW__

##### {队伍B}

| 选手 / 英雄 | K/D/A | 经济 | 装备 |
| --- | --- | --- | --- |
__MATCH_PLAYER_TABLE_ROW__

Repeat the same order only for games supported by evidence. Format net worth with
standard thousands separators (for example, `22,790`) and no decimal places. In
the `装备` column use only the fixed labels `主装备：`, `背包：`, `中立：`, and
`强化：` when their evidence is available. The client renders the main inventory
as medium Catalog icons, and removes the backpack, neutral, and enhancement
labels while rendering those items as small icons; the enhancement icon remains
inside parentheses. Do not put skill-leveling or talent information, full
purchase sequences, full skill sequences, or individual talent labels in the
normal match-detail table.
End the entire answer with a Markdown blockquote data note, with every visible
line prefixed by `>`, for example:

> **数据说明**
>
> - 日期和时间均按 UTC 展示。
> - 赛程、比分和状态来自 PandaScore；Valve Match ID 是跨源推断映射，并非 PandaScore 原生字段。
> - 选手数据和 BP 来自 OpenDota；英雄与物品名称仅来自 evidence 中的 Catalog 映射字段。

Do not emit raw HTML such as `<sub>` or `<br>`, CSS, or unsupported source claims.""".replace(
    "__MATCH_PLAYER_TABLE_ROW__", MATCH_PLAYER_TABLE_ROW
)

MATCH_PLAYER_PROGRESS_RULES = """For player_match_progress evidence, render the
complete post-match player configuration whenever the current request explicitly
asks for that player's item build, purchase order, skill order, or talent choices.
Render all three sections together even when the user explicitly mentions only
one of them. Select only the player, hero, and game supported by the current
request and evidence. If the request explicitly asks for every player's progress,
repeat the subsection for every evidenced player. Otherwise do not append this
section to a normal match-detail answer.

Do not render match overview, result, full draft, or ten-player scoreboard for a
focused player-progress request unless those facts are separately required by the
current request. Do not treat historical purchases as a recommendation,
popular build, core-build classification, or win-rate claim.

#### 出装、加点与天赋

##### {选手} · {英雄}（{等级}）

**出门装**

{所有开局前购买的物品；相同物品使用 `× N` 聚合}

**最终装备**

主装备：{物品名称}
背包：{物品名称；无则省略}
中立：{物品名称；无则省略}（强化：{物品名称；无则省略}）

**购买顺序**

| 相对开局时间 | 购买 |
| --- | --- |
| 00:33 | {物品} |

**技能加点**

{技能} → {技能}（5） → {技能}（4） → {大招}（3） → {全属性 +2（N）；无则省略}

**天赋选择**

- 10级：{天赋；无则省略}
- 15级：{天赋；无则省略}
- 20级：{天赋；无则省略}
- 25级：{天赋；无则省略}

For purchases, use only evidence-backed Catalog names. Aggregate every purchase
with a negative `time_seconds` into the **出门装** line immediately above
**最终装备**; preserve first-seen item order and write repeated items as `物品 × N`.
Omit 出门装 when there is no negative-time purchase. The purchase display is a
deterministic transform: it already excludes the configured post-start consumable
and ward item keys, so do not add any price-based filtering or invent a second
filter list in this Prompt. Render the remaining events in their original order.
Do not render a Markdown purchase table.
Render **技能加点** as one compact arrow sequence, not a table. Group each
non-talent selection by its first appearance and write its total selected rank
as `技能（N）`; preserve that first-appearance order. The deterministic
`attribute_bonus` mapping is named `全属性 +2` and belongs in this sequence.
For **天赋选择**, use each evidence row's `level_taken` exactly: it is the
player's fixed 10/15/20/25-level talent timing, not its raw `upgrade_index`.
List only mechanically evidenced talent selections; do not infer historical
talent-tree sides or tiers. Omit unavailable inventory groups."""

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
        "cross_source_match_mapping",
        "match_result",
        "player_scoreboard",
        "match_parse_status",
        "match_draft",
    }
)
TOURNAMENT_STATUS_EVIDENCE_KINDS = frozenset(
    {
        "competition_identity",
        "tournament_stage",
        "match_schedule",
        "match_state",
        "series_score",
    }
)
MATCH_DETAILS_EVIDENCE_KINDS = frozenset(
    {
        "match_result",
        "player_scoreboard",
        "match_parse_status",
        "match_draft",
        "valve_match_identity",
        "cross_source_match_mapping",
    }
)
MATCH_PLAYER_PROGRESS_EVIDENCE_KINDS = frozenset(
    {
        "player_match_progress",
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
        source is not None
        and source.name in {"PandaScore", "OpenDota", "PandaScore + OpenDota"}
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
    if kinds & TOURNAMENT_STATUS_EVIDENCE_KINDS:
        sections.append(TI_TOURNAMENT_STATUS_OUTPUT_EXAMPLE)
    if kinds & MATCH_DETAILS_EVIDENCE_KINDS:
        sections.append(MATCH_DETAILS_OUTPUT_EXAMPLE)
    if kinds & MATCH_PLAYER_PROGRESS_EVIDENCE_KINDS:
        sections.append(MATCH_PLAYER_PROGRESS_RULES)
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


def _answer_evidence_view(graph: EvidenceGraph) -> dict[str, object]:
    """Project the execution graph to the facts the Answer model may use."""

    required_kinds = set(graph.required_evidence)
    evidence = [item for item in graph.evidence if item.kind in required_kinds]
    return {
        "required_evidence": graph.required_evidence,
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "missing": graph.missing,
        "data_quality": graph.data_quality.model_dump(mode="json"),
    }


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
    answer_evidence = _answer_evidence_view(graph)
    answer_graph = graph.model_copy(
        update={
            "tool_results": [],
            "evidence": [
                item
                for item in graph.evidence
                if item.kind in set(graph.required_evidence)
            ],
        }
    )
    return [
        {"role": "system", "content": render_natural_language_system_prompt(answer_graph)},
        {
            "role": "user",
            "content": (
                "request_context="
                f"{json.dumps(request_context, ensure_ascii=False)}\n"
                f"evidence_view={json.dumps(answer_evidence, ensure_ascii=False)}"
            ),
        },
    ]
