# STRATZ 工具审计与重构输入

> 本文是「下周 STRATZ 工具全面重构」的输入材料：把**现有工具实现**与**官方
> GraphQL schema** 逐项对照，列出字段映射、未用能力、语义歧义与跨层问题，
> 并给出分优先级的重构建议。
>
> schema 来源：`docs/technical/stratz_schema_introspection.json`（官方
> introspection，~2.1MB）与 `stratz_schema_reference.md`。可用
> `apps/api/scripts/stratz_schema_docs.py` 重新抓取。

## 1. 范围与涉及代码

| 层 | 文件 | 职责 |
|---|---|---|
| agentic 工具 | `apps/api/app/agentic/tools/stratz_tools.py` | 参数 schema、handler、镜像折叠、排序/topK、per-week 扇出、evidence extractor |
| provider 集成 | `apps/api/app/integrations/stratz/heroes.py` | GraphQL 查询体、字段 normalize、（部分）排序 |
| 传输 | `apps/api/app/integrations/stratz/transport.py` | urllib POST、重试由 agentic 层 `_with_retry` 包裹 |

审计覆盖 5 个已注册工具 + 1 个未实现的 schema 能力：

- `stratz.pair_lane_outcome` → `heroStats.laneOutcome`（指定 hero + partner）
- `stratz.lane_meta_global` → `heroStats.laneOutcome`（heroId=null，全局）
- `stratz.hero_matchup_ranking` → `heroStats.heroVsHeroMatchup`
- `stratz.hero_position_stats` → `heroStats.stats`（groupByPosition）
- `resolve_hero` → 本地英雄常量，**非 STRATZ**（不在重构范围内，仅注明）
- **未实现**：`heroStats.winDay`（day-grain 趋势，见 §3.6）

## 2. 工具逐项审计

### 2.1 `laneOutcome`（pair_lane_outcome + lane_meta_global 共用）

**GraphQL 操作** `HeroLaneOutcome`（[heroes.py:52](../../apps/api/app/integrations/stratz/heroes.py:52)）
参数：`heroId`、`isWith`、`week`、`bracketBasicIds`、`positionIds`。

**请求字段**：`heroId1, heroId2, position, matchCount, winCount, lossCount, drawCount, matchWinCount`

**schema `HeroLaneOutcomeType` 完整字段**（introspection 权威）：

| 字段 | 类型 | 我们是否取 | 说明 |
|---|---|---|---|
| `heroId1` | `Int!` | ✅ | 映射为 `target_hero_id` |
| `heroId2` | `Short!` | ✅ | 映射为 `hero_id` |
| `week` | `Int!` | ❌ | 已由 args 决定 |
| `bracketBasicIds` | enum | ❌ | 已由 args 决定 |
| `position` | enum | ✅ | lane_meta 会 `pop` 掉 |
| `matchCount` | Long | ✅ | 样本数 |
| `winCount` | Long | ✅ | **lane 级**胜场（对线胜负） |
| `lossCount` | Long | ✅ | lane 级负场 |
| `drawCount` | Long | ✅ | lane 级平 |
| `matchWinCount` | Long | ✅ | **match 级**胜场（整局胜负） |
| `stompWinCount` | Long | ❌ | **未用**：碾压赢 |
| `stompLossCount` | Long | ❌ | **未用**：碾压输 |
| `csCount` | Long | ❌ | **未用**：对线补刀 |

**集成层派生**（[`_normalize_lane_outcome`](../../apps/api/app/integrations/stratz/heroes.py:216)）：
`match_win_rate = matchWinCount / matchCount`（match 级，4 位小数）；同时原样保留 lane 级 `win_count/loss_count/draw_count`。

**agentic 层变换**：
- `pair_lane_outcome`：按 partner 过滤到 1 行。
- `lane_meta_global`：`_dedupe_pair_rows` 镜像折叠（按 `match_count` 取较大方向）→ `min_sample_size` 过滤 → 按 `selection_mode` 排序（strong=`match_win_rate` desc，popular=`match_count` desc）→ `highlight_top` 截断。

**歧义/风险**：
- ⚠️ **同一 record 里 match 级与 lane 级计数混存**：`match_win_rate` 用 match 级，但 `win_count/loss_count/draw_count` 是 lane 级。下游若把 `win_count/match_count` 当胜率会得到「对线胜率」而非「比赛胜率」。见 memory `lane-match-win-rate-derivation`。
- ⚠️ `heroId1: Int!` 与 `heroId2: Short!` 类型不对称（STRATZ schema 怪癖），代码统一按 int 处理，目前无碍。

### 2.2 `heroVsHeroMatchup`（hero_matchup_ranking）

**GraphQL 操作** `HeroVsHeroMatchup`（[heroes.py:5](../../apps/api/app/integrations/stratz/heroes.py:5)）
参数：`heroId, take, week, bracketBasicIds, matchLimit`。

**请求字段**：`advantage/disadvantage → { heroId, matchCountVs, vs { heroId1, heroId2, matchCount, winCount, synergy, winRateHeroId1, winRateHeroId2 } }`

**schema `HeroDryadType`（advantage/disadvantage 元素）字段**：

| 字段 | 类型 | 我们是否取 |
|---|---|---|
| `heroId` | Short | ✅ |
| `matchCountVs` | Long | ✅ |
| `vs` | `[HeroStatsHeroDryadType]` | ✅ |
| **`with`** | `[HeroStatsHeroDryadType]` | ❌ **未用** |
| **`matchCountWith`** | Long | ❌ **未用** |

> 🔑 **关键差距**：`HeroDryadType` 同时有 `vs`（克制）和 `with`（盟友协同）两个子列表。我们只查 `vs`。`with` 正是「英雄搭配/协同」查询的数据源——而 planner prompt 此前正是以「synergy/teammate combo 不支持」为由拒绝这类查询（该限制已于 2026-07-03 移除）。**数据可得，工具未暴露。**

**schema `HeroStatsHeroDryadType`（vs/with 内层行）字段**（共 24 个）：
我们只取 `heroId1, heroId2, matchCount, winCount, synergy, winRateHeroId1, winRateHeroId2`。
**未取**：`kills, deaths, assists, networth, duration, firstBloodTime, cs, dn, goldEarned, xp, heroDamage, towerDamage, heroHealing, level, winsAverage`。

**集成层派生**（[`_normalize_matchup_side`](../../apps/api/app/integrations/stratz/heroes.py:187)）：
- `hero_id=heroId2`, `target_hero_id=heroId1`
- 本地 `win_rate = winCount / matchCount`（这里的 `winCount` 是 **matchup 级**，语义不同于 lane 的 match 级）
- 重命名 `winRateHeroId1→target_win_rate`、`winRateHeroId2→hero_win_rate`
- **集成层自己排序**：按 `(synergy, match_count) desc`

**agentic 层变换**（[`_filter_matchup_rows`](../../apps/api/app/agentic/tools/stratz_tools.py)）：`min_sample_size` 过滤 → 按 `(synergy, match_count)` desc → `take` 截断。

**歧义/风险**：
- ⚠️ **排序发生两层**：集成层已按 synergy 排序，agentic 层又排一次。冗余且职责不清。
- ⚠️ **provider 原生胜率被弃用**：STRATZ 给了原生 `winRateHeroId1/winRateHeroId2`（Decimal）与合成 `synergy`，但 ranking 用 `synergy`；本地又算了个 `win_rate=winCount/matchCount` 几乎没被下游用到（`_filter_matchup_rows` 用 synergy 不用 win_rate）。本地 `win_rate` 基本是死字段。
- ⚠️ **服务端能过滤却客户端过滤**：`matchLimit` 参数（duo 最低样本数）集成层暴露了 `match_limit` 形参，但 agentic handler **不传**，改在客户端 `_filter_matchup_rows` 做 `min_sample_size` 过滤——多传了行数据。
- ⚠️ `matchCountVs`（每个对手分组的总样本）取了但下游没用。

### 2.3 `stats`（hero_position_stats）

**GraphQL 操作** `HeroPositionStats`（[heroes.py:81](../../apps/api/app/integrations/stratz/heroes.py:81)）
参数：`heroIds, bracketBasicIds, positionIds, week` + 固定 `groupByPosition: true`。

**请求字段**：仅 `heroId, position, matchCount`。

**schema `HeroPositionTimeDetailType` 字段**：共 **~75 个**（introspection 权威）。我们只取 3 个。

**关键未取字段**：
- `winCount`（→ 可算 **英雄胜率**，目前完全没有）
- `remainingMatchCount`、`mvp`、`kills/deaths/assists`、`networth`、`xp`、`cs/dn/neutrals`、`goldPerMinute`、`heroDamage/towerDamage`、`physical/magicalDamage(Received)`、`disableCount/Duration`、`stunCount/Duration`、`healingSelf/Allies`、`runePower/Bounty`、`campsStacked`、`supportGold`、`stompWon/Lost`、`comeBackWon/Lost`、`kDAAverage`、`killContributionAverage` …
- args 还有 `groupByTime/Position/Bracket`、`minTime/maxTime`（按游戏内时长大切片，未用）。

**歧义/风险**：
- ⚠️ **只输出 pick 量，无胜率**：`hero_position_stats` 当前只能答「某位置谁出场多」，答不了「某位置谁胜率高」——尽管 `winCount` 现成可得。能力利用率 <5%。

### 2.4 `resolve_hero`（非 STRATZ）

本地英雄常量解析（`hero_tools.py`），不经 STRATZ。重构不涉及，仅说明以避免误改。

### 2.5 `winDay`（**未实现**）

**schema `HeroStatsQuery.winDay`** → `[HeroWinDayType]`，返回最近 12 天 day-grain 数据。
字段：`day: Long!, heroId: Short!, winCount: Int!, matchCount: Int!`。
胜率口径：`winCount/matchCount`（reference 明确）。
**参数差异**：用 `bracketIds: [RankBracket]`（**全枚举** UNCALIBRATED…IMMORTAL），不是 `bracketBasicIds`；还支持 `regionIds`、`gameModeIds`、`positionIds`、`take/skip`、`groupBy`。

> 这是官方的「英雄趋势」数据源（按天），我们完全没有趋势类工具。新增需解决 bracket 全枚举与现有 basic 枚举（`DIVINE_IMMORTAL`）的翻译。

## 3. 横切问题（跨工具）

| # | 问题 | 现状 | 影响 |
|---|---|---|---|
| A | **胜率语义不统一** | lane=`matchWinCount/matchCount`(match 级)；matchup=`winCount/matchCount`(matchup 级)；position=无胜率 | 跨工具比较与 answer 措辞口径不一 |
| B | **排序/截断跨层分散** | matchup 在集成层+agentic 层都排序；lane 只在 agentic 层 | 职责模糊、冗余 |
| C | **provider 原生胜率被忽略 + 本地重复算** | matchup 有原生 `winRateHeroId1/2` 却用本地 `win_rate`（且基本未用） | 死字段、口径漂移风险 |
| D | **per-week 扇出样板** | 每个 handler 重复 `for epoch in epochs: await _with_retry(...); bucket.append(_bucket(...))` | 4 处重复，易漂移 |
| E | **provenance 透传不一致** | 仅 `lane_meta_global` 有 `selection_policy`；只有把字段塞进 `filters` 才到 answer（见 memory `answer-sees-evidence-graph-only`） | answer 措辞口径缺失 |
| F | **bracket 枚举 basic vs full** | lane/matchup/stats 用 `RankBracketBasicEnum`；winDay 用 `RankBracket` | 新增 winDay 需枚举翻译层 |
| G | **服务端能过滤却客户端过滤** | matchup 不传 `matchLimit`，客户端 `min_sample_size` | 多传数据、语义重复 |
| H | **context 字段与工具支持不对齐** | `QueryContext` 有 `region_ids/game_mode_ids`，但 lane/matchup/stats 都不传；仅 winDay 支持 | 声明了的能力实则无效 |
| I | **position 过滤透传不一致** | `pair_lane_outcome` 传 `position_ids`；`lane_meta_global` 不传（测试还断言它不在 filters） | 同操作不同行为，意图不清 |
| J | **`hero_matchup_ranking` over-fetch** | 传 `take=max(args.take,50)` 再客户端截到 `take` | 可接受但应记录 |

## 4. 重构建议（分优先级）

### P0 — 正确性与语义（必须先收敛）
1. **统一胜率口径**：每个工具显式声明并命名其胜率是 match 级 / matchup 级 / lane 级。lane 的 `match_win_rate` 保持 match 级（见 §5 约束）。
2. **排序/截断收敛到单层**：建议集成层只做 normalize（不排序），排序/topK/selection_policy 全放 agentic 层。删除 `_normalize_matchup_side` 里的排序。
3. **决定 matchup 排序键**：在 `synergy`（STRATZ 合成优势分）/ 原生 `winRateHeroId*` / 本地 `win_rate` 中显式选一个，删掉其余死字段；或像 lane_meta 一样做成 planner 可选。

### P1 — 能力扩展（配合 schema，价值最高）
4. **新增 `winDay` 趋势工具**：day-grain 英雄胜率/出场趋势（最近 12 天）。需配套 bracket 全枚举翻译（basic→full）。
5. **`hero_position_stats` 扩展 `winCount`**：让它能答「某位置胜率最高/出场最多」，复用 lane_meta 的 `selection_mode` 思路。
6. **laneOutcome 补 `stompWinCount/stompLossCount/csCount`**：作为对线主导度/补刀证据，丰富 lane 证据。
7. **matchup 补 `with` 子查询**：暴露盟友协同数据，真正支持「英雄搭配」类查询（呼应已删除的 synergy 限制）。

### P2 — 一致性与清理
8. **抽 per-week 扇出 helper**：`_fan_out_weeks(epochs, fetch_fn) -> buckets`，消除 4 处重复。
9. **统一 provenance 透传**：所有工具把 selection/sort 口径塞进 `filters`，确保到达 answer。
10. **对齐 context 与工具支持**：`region_ids/game_mode_ids` 要么在支持的查询里实现，要么从 `QueryContext` 移除，避免「声明即生效」的假象。
11. **统一 position 过滤透传**：明确 lane_meta 是否接受 position（当前刻意丢弃，需写清理由或改为透传）。
12. **服务端过滤优先**：matchup 用 `matchLimit` 替代客户端 `min_sample_size`。

## 5. 重构必须保留的约束（do-not-break）

- **`match_win_rate = matchWinCount / matchCount`（match 级）**：不可「简化」成 `winCount/matchCount`（那是 lane 级）。见 memory `lane-match-win-rate-derivation`。
- **已完成周口径**：`_resolve_week_window` 永远跳过当前未完成周，传显式 epoch（不依赖 schema 里 null 的歧义语义）。见 `docs/design/time_patch_filtering.md`。
- **provenance 必须进 evidence `value["filters"]`**：answer LLM 只看 evidence graph，不看 `result.data`。见 memory `answer-sees-evidence-graph-only`。
- **薄 relay 原则**：工具只做排序/过滤/字段映射，不发明自创聚合分（如加权综合分）。见 memory `prefer-honest-data-boundaries-over-aggregation`。
- **镜像折叠语义**：`_dedupe_pair_rows` 按 `match_count` 取较大样本方向（可信度，非最终排序）。

## 6. 下一步

- 本文档即重构的输入地图。建议按 P0 → P1 → P2 顺序拆成独立 PR/commit。
- 每个 P0/P1 项落地后，更新对应工具的 `description`（planner 可见契约）与 evidence extractor，并补单测。
- 重构期间如 schema 字段有变动，重跑 `stratz_schema_docs.py` 刷新本文依据。
