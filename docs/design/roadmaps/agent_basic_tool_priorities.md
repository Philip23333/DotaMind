# Agent 基础完整体验工具优先级

## 目标

本文定义 Dota 自然语言 Agent 的基础工具补齐顺序。这里的“基础但完整体验”指：

```text
识别对象 -> 取证据 -> 按角色/场景过滤 -> 给出可解释回答
```

目标不是一次性做深所有能力，而是让常见 Draft / Meta 问题不在中间断链。

## 第一优先级：让 Draft / Meta 问题闭环

### 1. `resolve_position` / `resolve_draft_role`

本地确定性解析用户口语位置：

```text
resolve_position("4号位") -> POSITION_4
resolve_position("中单") -> POSITION_2
resolve_position("offlane") -> POSITION_3
```

- 数据源：本地别名表。
- evidence kind：`position_identity`。
- 价值：减少 planner 对“4 号位 / 中单 / 劣势路 / pos4 support”等表达的自由猜测，并复用到 STRATZ `position_ids`、`hero_position_stats`、`hero_daily_trends` 等工具。

### 2. `filter_heroes_by_position`

对候选英雄做角色/位置过滤。

输入建议：

```text
hero_ids
position_id
min_role_confidence / min_match_count
```

数据源可分阶段：

- 第一版：本地 hero role map。
- 第二版：STRATZ `hero_position_stats`。
- 后续：结合 OpenDota role stats。

evidence kind：`role_fit`。

价值：让 `hero_matchup_ranking` / `hero_synergy_ranking` / meta 候选能回答“我打 4 号位选什么”，而不是只返回一组未按位置约束的英雄。

### 3. `stratz.hero_synergy_ranking`

暴露 STRATZ `heroVsHeroMatchup.with` 盟友协同数据。

- 敌方英雄场景：`stratz.hero_matchup_ranking`。
- 队友英雄场景：`stratz.hero_synergy_ranking`。

价值：补齐 Draft 建议的另一半，使 Agent 能回答“队友 X，我选什么配合”。

### 4. `stratz.hero_daily_trends`

基于 STRATZ `winDay` 提供 day-grain 趋势。

典型问题：

```text
Lina 最近是不是掉了？
这个英雄现在还适合练吗？
版本后趋势怎么样？
```

价值：补齐“最近还强不强”的基础判断，不只依赖静态胜率。

## 第二优先级：让回答更像 Dota 助手

### 5. `stratz.hero_position_stats` 补 `winCount`

让 position 工具从“只答出场量”升级为能回答：

```text
当前 3 号位谁胜率高？
Lina 更适合几号位？
某英雄哪个位置表现最好？
```

胜率口径应显式标注：

```text
match_win_rate = winCount / matchCount
win_rate_basis = "match: winCount/matchCount"
```

### 6. `stratz.lane_outcome` 补 stomp/cs

补充对线主导度证据：

```text
stomp_win_count
stomp_loss_count
cs_count
```

典型问题：

```text
这组双人路是赢线还是只赢比赛？
补刀压力怎么样？
有没有碾压/被碾压风险？
```

约束：只透传证据，不发明综合分，不改变既有胜率口径。

### 7. `patch.hero_context`

对 `patch.hero_changes` 做轻量聚合，按英雄返回最近版本上下文。

返回建议：

- buff / nerf / neutral 分类。
- 影响技能、天赋、物品。
- patch 版本。
- 原始 change records。

价值：让 Draft / Meta 回答能解释“为什么强/弱”，而不是只给统计结果。

## 第三优先级：补完整产品感

### 8. `stratz.hero_guides_summary`

基于 STRATZ `HeroGuidesCount` / `HeroGuides` 做基础攻略摘要。

典型问题：

```text
这个英雄常见出装是什么？
4 号位 Lina 怎么出？
主流加点/装备节奏？
```

价值：用户问完“选什么”后，常见下一步是“怎么玩/怎么出”。

### 9. `stratz.hero_rank_bracket_trends`

按段位查看英雄表现差异。

典型问题：

```text
这个英雄是高分强还是低分强？
冠绝局和普通局差异大吗？
```

价值：补齐段位适配判断，避免把全分段数据误当成用户所在分段建议。

### 10. `rank.candidate_heroes`

本地确定性候选整理工具，用于把多个证据列表做透明规则的交集、过滤、排序。

第一版只做可解释规则：

```text
include hero if:
- role_fit matches position
- sample_size >= threshold
- appears in matchup/synergy/meta evidence

sort by:
- primary evidence metric
- sample_size tie-break
```

evidence kind：`candidate_ranking_row`。

约束：不发明复杂综合分。排序依据必须写进 `filters` / `selection_policy`。

## 最小可用组合

如果目标是先让 Agent 体验完整跑通一圈，优先落地：

1. `resolve_position`
2. `filter_heroes_by_position`
3. `stratz.hero_synergy_ranking`
4. `stratz.hero_daily_trends`
5. `stratz.hero_position_stats` 补 `winCount`
6. `rank.candidate_heroes`

这组能力覆盖：

```text
对面 Lina，我打 4 号位选什么？
队友骷髅王，我选什么辅助配合？
现在 3 号位练谁？
Lina 最近还强吗？
某英雄适合哪个位置？
```

## 与 P1 的关系

P1 计划中的 STRATZ 四项能力仍然成立：

- `hero_position_stats` 补 `winCount`
- `laneOutcome` 补 stomp/cs
- 新增 `stratz.hero_synergy_ranking`
- 新增 `stratz.hero_daily_trends`

但为了让这些 STRATZ 工具真正组成完整体验，建议在 P1 前后补两个地基工具：

- `resolve_position`
- `filter_heroes_by_position`

否则系统容易在“用户说的位置”和“证据里的英雄候选”之间断链。
