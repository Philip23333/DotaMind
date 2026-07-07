# STRATZ Player Page GraphQL Inventory

Capture target: player-domain queries for V3.0 G2 (玩家战绩查询).

Capture date: 2026-07-07

Methodology: **schema-introspection based** (parsed `docs/technical/stratz_schema_introspection.json`), not live Playwright capture. Field/description facts below are schema-confirmed; items needing live-query confirmation are marked 🚦LIVE-GATE. No live requests were issued for this inventory.

## Summary of confirmed facts (schema-level)

| 关切 | 结论 | 来源 |
| --- | --- | --- |
| 玩家查询根 | `DotaQuery.player(steamAccountId:Long!): PlayerType` | introspection |
| 批量玩家 | `DotaQuery.players(accountIds:Long![]): PlayerType[]` | introspection |
| 单局按 ID | `DotaQuery.matches(ids:Long![]): MatchType[]`(G4 用,本切片仅记录) | introspection |
| 玩家对局 | `PlayerType.matches(request: PlayerMatchesRequestType!): MatchType[]` | introspection |
| 玩家英雄表现 | `PlayerType.heroesPerformance(request, take, skip): PlayerHeroesPerformanceType[]` | introspection |
| 单局取当前玩家 | `MatchType.players(steamAccountId:Long): MatchPlayerType[]` | introspection |
| 胜负字段 | `MatchPlayerType.isVictory: Boolean`(**native,不推导**) | introspection |
| winRate | `PlayerHeroesPerformanceType` **无 native winRate**;本地派生 `winCount/matchCount` | introspection |

## Bracket / Rank 编码(P0 设计关键)

两个 request 类型对段位过滤的字段不同:

| request 类型 | `bracketIds` | `rankIds` | 用途 |
| --- | --- | --- | --- |
| `PlayerMatchesRequestType` | ✅ `[Int 0-8]` | ✅ `[Int 0-80]` | `PlayerType.matches`(recent_matches) |
| `PlayerHeroPerformanceMatchesRequestType` | ❌ 无 | ✅ `[Int 0-80]` | `PlayerType.heroesPerformance`(hero_performance) |

schema 描述(原文):
- `rankIds`: "The value ranges from **0-80** with 0 being unknown MMR"
- `bracketIds`: "The value ranges from **0-8** with 0 being unknown MMR"

### `basic_to_bracket_ids` (0-8 空间,recent_matches 用)

`RankBracket` enum(ordinal 即整数 0-8):
```
UNCALIBRATED=0  HERALD=1  GUARDIAN=2  CRUSADER=3  ARCHON=4
LEGEND=5  ANCIENT=6  DIVINE=7  IMMORTAL=8
```
项目 `RankBracketBasicEnum` → bracketIds 映射(相邻对):
```
UNCALIBRATED      -> [0]
HERALD_GUARDIAN   -> [1, 2]
CRUSADER_ARCHON   -> [3, 4]
LEGEND_ANCIENT    -> [5, 6]
DIVINE_IMMORTAL   -> [7, 8]
```
**风险低**(ordinal 即值是 STRATZ 通行约定),但 enum description 为空,建议 Commit 2 实现时用一个 live query 抽验一次。`FILTERED`/`ALL` 不应进 basic helper(抛错)。

### `basic_to_rank_ids` (0-80 细分空间,hero_performance 用) 🚦LIVE-GATE

introspection 描述**只给 "0-80, 0=unknown"**,不给每个 bracket 的细分范围。用户本地核验数据点:`74 = Divine 4 Stars`。推断编码 = `bracket(1-8) * 10 + star`:
```
HERALD_GUARDIAN   -> [10..24]   (Herald 10-14, Guardian 20-24)
CRUSADER_ARCHON   -> [30..44]
LEGEND_ANCIENT    -> [50..64]
DIVINE_IMMORTAL   -> [70..75, 80]   (Divine 70-74 或 71-75?,Immortal 80)  ← star 索引(0-4 vs 1-5)未定
UNCALIBRATED      -> [0]
```
**🚦HARD GATE**:Divine/Immortal 的精确边界(70-74 vs 71-75、Immortal 是否含 81+)**必须 live query 锁定**(发真实 `heroesPerformance` 请求,变 rankIds 看返回)。**Commit 3 实现前若未锁定 → hero_performance 的 bracket 过滤不实现**(暴露"不支持",不加假 fallback)。

## `PlayerType` 关键字段

```
steamAccountId: Long
steamAccount: SteamAccountType          # 身份(name/avatar/rank)
matchCount: Int                          # 玩家全局场次
winCount: Int                            # 玩家全局胜场(可派生全局胜率)
imp: Int
firstMatchDate / lastMatchDate: Long
ranks(seasonRankIds: Byte[]): SteamAccountSeasonRankType[]
performance: PlayerPerformanceType       # 全局表现(含 mmrTier/mmrBracket/position 等)
heroPerformance(heroId:Short!, request): PlayerPerformanceType     # 单英雄(本切片不用)
heroesPerformance(request, take:Int, skip:Int): PlayerHeroesPerformanceType[]   # ★ hero_performance 用
matches(request: PlayerMatchesRequestType!): MatchType[]          # ★ recent_matches 用
matchesGroupBy(request): MatchGroupByType[]
```

⚠️ **命名陷阱**:`heroesPerformance`(plural,返回 `PlayerHeroesPerformanceType[]`)的 `request` 参数类型是 **`PlayerHeroPerformanceMatchesRequestType`**(单数命名!),**不是** `PlayerHeroesPerformanceMatchesRequestType`(plural 命名的 input type 也存在但本字段不用)。Commit 3 handler 构造的是 `PlayerHeroPerformanceMatchesRequestType`。

## `PlayerMatchesRequestType`(recent_matches,relevant 字段)

```
startDateTime: Long        # unix seconds,日期窗口下界
endDateTime: Long          # 上界
bracketIds: Byte[]/Int[]   # 0-8(用这个)
rankIds: Int[]             # 0-80(也可,但 bracketIds 更干净)
positionIds: MatchPlayerPositionType[]
gameModeIds: Byte[]        # 🚫 v1 不支持(QueryContext 是字符串枚举,类型不一致)
lobbyTypeIds: Byte[]
regionIds: Int[]           # 🚫 v1 不支持(同上)
heroIds: Short[]
isStats: Boolean           # STRATZ 判定"真实"对局(过滤 AFK/送头)
take: Int                  # 返回对局数(= recent_matches.take)
skip: Int                  # 分页
orderBy: FindMatchPlayerOrderBy   # 可按日期倒序
playerList: FindMatchPlayerList   # 决定 players 数组返回单玩家还是全 10 人
```

`days` → `startDateTime = now - days*86400`;`take` → request.take;按日期倒序取最近 take 场(交集语义)。

## `PlayerHeroPerformanceMatchesRequestType`(hero_performance,relevant 字段)

```
startDateTime / endDateTime: Long     # days 窗口
rankIds: Int[]                        # 0-80(★ 唯一段位过滤,无 bracketIds)
positionIds: MatchPlayerPositionType[]
gameModeIds: Byte[]                   # 🚫 v1 不支持
regionIds: Int[]                      # 🚫 v1 不支持
heroIds: Short[]
take: Int                             # ★ 参与统计的 match 数(= match_take),非 hero rows
skip: Int
orderBy / matchGroupOrderBy           # 排序
```
**双 take 确认**:外层 `heroesPerformance(request, take, skip)` 的 `take` = 返回 hero rows 数;request 内 `take` = 参与统计 match 数。Commit 3:`take`(工具 arg)= output hero rows;`match_take`(工具 arg)= request.take;`hero_row_take = max(take*3, 50)`(strong 模式 ~150,见下)over-fetch。

## `PlayerHeroesPerformanceType`(每英雄一行)

```
heroId: Short!           hero: HeroType
winCount: Int!           matchCount: Int!       # ← 派生 win_rate = winCount/matchCount
kDA: Float               avgKills/avgDeaths/avgAssists: Float
duration: Int!           imp: Int               best: Float
goldPerMinute: Int!      experiencePerMinute: Int!
positionScore: PlayerHeroesPerformanceScoreType[]
lastPlayedDateTime: Long
```
**无 native winRate** → `win_rate_basis = "player_hero: winCount/matchCount"`。

**默认排序**:schema 未声明 `heroesPerformance` 默认排序 🚦。→ strong 模式不信任外层排序,over-fetch `hero_row_take ≈ max(take*3, 50)`(玩家英雄池小,strong 拉接近全量~150 避免漏低出场高胜率),本地 `min_match_count` 过滤 → selection_mode 排序 → take 截断。popular 模式可直接用外层 take。

## `MatchType.players(steamAccountId)` + `MatchPlayerType`(单局当前玩家)

```
MatchType:
  id: Long
  startDateTime: Long
  duration: Long
  lobbyType: LobbyTypeEnum
  gameMode: GameModeEnumType
  players(steamAccountId: Long): MatchPlayerType[]    # ★ 按 steamAccountId 过滤到当前玩家

MatchPlayerType(relevant):
  isVictory: Boolean        # ★ native 胜负(recent_summary wins/losses 直接用)
  isRadiant: Boolean
  heroId: Short             kills/deaths/assists: Byte
  goldPerMinute: Short      experiencePerMinute: Short
  position: MatchPlayerPositionType
  lane: MatchLaneType       role: MatchPlayerRoleType
  imp: Short                level: Byte
  numLastHits/numDenies: Short
  item0Id..item5Id / backpack* / neutral0Id: Short    # (出装,G1/G4 用,本切片记录不实现)
```
recent_matches handler:`PlayerType.matches(request)` → 每 `MatchType` 取 `players(steamAccountId)` 的当前玩家行 → `isVictory` 定胜负。

## `SteamAccountType`(identity)

```
id: Long        name: String        avatar: String
seasonRank: Byte        smurfFlag: Byte
proSteamAccount: ProSteamAccountType     # 职业选手关联(可选)
```
`player_profile` evidence 用这些 + `PlayerType` 的 `matchCount/winCount/imp/lastMatchDate`。

## 给 Commit 2/3 的锁定项

- ✅ `basic_to_bracket_ids`(0-8)—— 映射确定(ordinal),Commit 2 可实现,live 抽验一次。
- 🚦 `basic_to_rank_ids`(0-80)—— **HARD GATE**,Commit 3 前必须 live query 锁定 Divine/Immortal 边界;锁不定则 hero_performance 不做 bracket 过滤。
- 🚦 `heroesPerformance` 默认排序 —— 未声明,strong 模式 over-fetch(~150)兜底;popular 用外层 take。
- ✅ `MatchType.players(steamAccountId)` 拿当前玩家行 + `isVictory` —— 确认,recent_matches 用。
- ✅ 双 take(outer=hero rows / request.take=match 统计数)—— 确认,Commit 3 分 `take`/`match_take`。
- ✅ `PlayerHeroPerformanceMatchesRequestType`(单数命名)是 `heroesPerformance` 实际用的 request 类型 —— Commit 3 别用错 plural 命名。

## v1 不做(类型边界)

- `regionIds`/`gameModeIds` 翻译层:QueryContext 是字符串枚举(hero_daily_trends 用),player request 要 `[Int]`/`[Byte]` → v1 不支持;现有 `validate_context_scope` 已拒绝(player 工具归入非 hero_daily_trends)。
- `lobbyTypeIds`、`isStats`、`leagueId` 等高级过滤 —— 留后续。
