# Product

## Purpose

DotaMind is a Dota 2 esports agent. It answers questions about professional
competitions, series, games, teams, professional players, and the Dota objects
needed to understand those matches.

It is for fans, analysts, and viewers who want a trustworthy conversational
interface to current esports facts and match context rather than a dashboard of
generic game statistics.

## Core product surface

- Competition discovery, status, and schedule
- Series and game search, results, and match detail
- Team schedule, recent results, and roster context
- Professional-player match records and single-game performance
- Player builds, skill upgrades, talents, and item progression when data exists
- Hero, item, and ability information that explains a match
- Cached hero item builds, skill-build suggestions, and professional-match
  examples when `hero.guide` is enabled by the run configuration
- Natural follow-up questions grounded in the actual conversation
- Optional web search for current external information, when enabled by the
  deployment

## Core user journeys

- Ask what is happening in a tournament, what has finished, and what is next.
- Find a series or game and understand its result, draft, scoreboard, and
  player performance.
- Ask about a team, its next match, recent results, or roster.
- Follow a player from a match to their performance and build.
- Continue with references such as "game two", "that player", or "their previous
  match" without restating the whole question.

## 首页与快捷查询（已确认设计，待实现）

本节定义首页赛事列表与快捷查询入口的用户可见行为。它是该交互契约的
唯一归属；数据排序与缓存细节见 [DATA.md](DATA.md)，实现顺序见
[ROADMAP.md](ROADMAP.md)。以下是待实现设计，不表示当前页面已具备这些行为。

### 首页布局与近期赛事

首页按以下顺序组织：缩小后的 DotaMind 品牌区、最近赛事列表、四个快捷
入口、聊天输入框。移除硬编码的 TI 宣传内容。最近赛事最多展示三条，采用
轻量列表；每条显示状态、赛事届次名称和日期。已结束赛事只有在获胜对象
明确且冠军能解析为战队名称时才追加冠军名称；没有获胜信息或名称不可用时
不显示冠军。首页与“赛事查询”展开层使用同一份最多十条的候选及顺序，
首页只显示其前三条。

最近赛事行可用鼠标、键盘或触屏操作。点击后直接发送一条普通聊天消息，
其中包含赛事名称、`Series` 类型和 Series ID，例如：

```text
查询赛事「赛事名称」的最新战况和赛程（赛事届次 Series ID：12345）。
```

该操作保留输入框已有草稿，并关闭展开层。赛事加载、有效空列表或数据
不可用时均有对应状态；数据加载或失败不能阻止用户使用聊天输入框。完整
Trace 调试入口收进调试区域，普通查询进度仍可见。

### 四个快捷入口

快捷入口为“赛事查询”“英雄攻略”“玩家战绩”“单局解析”。开始聊天后
保留这四个入口，首页品牌区和最近赛事区收起。输入框按产品能力更新提示语。

点击入口在入口栏上方展开相应面板；同一时间只展开一个。再次点击当前
入口或按 Escape 关闭面板；切换入口保留本次已填写的各面板内容。

| 入口 | 面板行为 |
| --- | --- |
| 赛事查询 | 展示与首页共用的最多十条候选；点击一条直接发送 Series 普通文本并关闭面板。 |
| 英雄攻略 | 自由输入英雄名称，不要求头像或名称联想；位置 1～5 多选，默认全选，并可全选或清空。 |
| 玩家战绩 | 输入 Dota 2 好友 ID（Steam32 ID）。 |
| 单局解析 | 输入比赛 ID；消息中沿用现有 Valve game ID 语义。 |

后三个入口只收集参数并生成可编辑的普通问题草稿，不自动发送。示例文本为
“查询英雄斯温的1～5号位攻略”“查询 Steam32 ID 为……的玩家近期战绩”与
“分析比赛 ID 为……的单局详情”。英雄名称非空、位置至少选择一个；账号和
比赛 ID 去除首尾空格后须为正整数格式。不符合要求时说明原因，不填入草稿。
输入或选择过程本身不覆盖聊天草稿。

点击“填入问题”或在面板内按 Enter，将生成的问题填入聊天输入框并聚焦，
关闭面板且不触发聊天发送。填入会替换当前草稿，不拼接不同问题，并支持撤销恢复；
若编辑器无法可靠恢复，已有草稿时须明确提示并让用户确认“替换当前草稿”。
面板输入值在关闭、切换面板后保留。赛事直接发送不替换已有草稿。

生成期间仍可打开面板、填写参数和更新草稿；赛事一键发送暂时禁用，避免
打断正在进行的回答。小屏下四个入口排为两列；面板内容可在面板内滚动，
输入框保持可操作，日期和冠军文字允许换行。交互支持键盘和触屏，不依赖
悬停。

## Hero guides and shared game data (Redis query and operator refresh implemented; file updates pending)

The hero-guide tool answers a request for one specified Valve hero ID and
position. Pub build data is the primary guide; recent professional matches for
the same hero and position provide separate practical examples. The two sources
remain distinguishable, and a professional example is not presented as
evidence that its player followed a particular Pub build. The query reads the
shared Redis cache only and does not trigger a D2PT request or refresh. When the
cache has not been populated, it reports the source as missing.

Today, the query reads guide snapshots from the injected Redis cache, and an
operator-only CLI can refresh those snapshots. The Valve entity catalog is
loaded from files bundled with the API code. The shared file store, unified
update task, and API hot reload described below are target behavior; they are
not part of the current query path.

This journey is a specified-hero guide lookup. It does not add an all-hero
strength ranking, matchup/counter analysis, or draft recommendation. Pub and Pro
partitions may be independently missing or stale; answers must identify which
source data is available and must not fill gaps with invented facts. A cache
snapshot is shown as stale after 36 hours or when its latest refresh attempt
failed; the stale threshold is a display rule, not the provider's statistics
window. `hero.guide` now adds English and Chinese hero, item, and ability names
from the bundled Valve catalog to the fields selected by its result section. The
result includes the catalog snapshot version; IDs and provider-supplied labels
remain intact, and unresolved IDs remain visible with empty catalog names. This
enrichment happens when queried and does not write into Redis, so existing cache
snapshots need no refresh for the names to appear. The same resolver is not yet
connected to `game.detail`.

## Shared game-data updates (target)

Heroes, abilities and talents, items and recipes, images, patch records, and
Pub/Pro guides are shared application data. The target update task publishes new
data in the background; user queries read the last successfully published data
and never trigger a remote refresh. Entity catalogs update by default when the
official patch changes, while guide partitions update daily. Images and patch
records are maintained independently from the entity-catalog version.

After the shared file store and API hot reload are deployed, routine data
updates should not require an API restart or redeployment. If an update fails,
the last successful catalog or guide partition remains available, while missing,
stale, and failed-source states remain visible to the query. The official latest
patch, the patch represented by the last successful catalog, the catalog
snapshot number, guide source scope and retrieval time, and image-resource
version describe different things and must not be conflated. This is a confirmed
implementation target; it does not describe current file-backed guide storage or
hot reload.

## Steam-account and game-detail scope

Users can look up a STRATZ player profile by Steam32 account ID when
`DOTAMIND_STRATZ_TOKEN` is configured. The account need not belong to a
professional player. DotaMind does not automatically associate it with a
PandaScore professional-player identity. With the same token configured,
`player.recent_games` can return a bounded latest-first sample for that exact
Steam32 account. A one-match live check confirmed that STRATZ's ID for the
provided match also resolves as the same OpenDota match ID. A live query for
one participant returned 20 rows newest-first; that older final was outside the
bounded sample. This is a single-account check, not a general availability
guarantee. `game.detail` reads an existing OpenDota game record and registers
only when `DOTAMIND_OPENDOTA_ENABLED=true`. Reading a record does not submit a
replay for parsing. The profile query has not been verified against the live
STRATZ API, and the new OpenDota client has not had a live request test.

For the account-to-game journey, a user can provide a Steam32 ID, inspect its
bounded recent-games list, select one returned `valve_game_id`, and request
that game's detail. The account's row in the detail must be matched by exact
`account_id`; names and other player attributes are not identity proof. A
follow-up such as “the second game” refers to the earlier list retained in the
conversation, not a refreshed list with potentially different ordering. The
agent does not fetch every listed game's detail automatically. Static hero and
item labels may be resolved from the bundled Valve catalog; unknown IDs remain
unknown. Missing timelines or purchase data are evidence gaps, not proof that
events or purchases did not occur.

## Product boundaries

Current integrated capabilities are described by the enabled tool inventory
generated from the run's actual registry. Earlier assistant claims about what
DotaMind can do may be incorrect or outdated and do not override that inventory.
Capability questions can be answered directly without executing a tool. Concrete
supported lookups use the relevant enabled tool or request necessary missing
input. Tool registration, data availability, and successful retrieval are
distinct facts: an enabled guide tool does not promise cached data, complete
laning instruction, or a real-time optimal build. An answer without retrieved
guide data must acknowledge that gap without inventing a guide or claiming the
product lacks the enabled capability.

Answers distinguish provider facts, identity inferences, and model interpretation.
The agent must use tools for current or specific facts and must not invent data
that no tool returned.

When Tavily MCP search is configured and available, the agent can search the web
and cite URLs actually returned by that search. Search snippets are observations,
not proof that a full page was read; search availability is optional and provider
failures are reported as missing evidence rather than silently substituted.

The product is organized around user value, not around whatever a provider API
happens to expose.

## Non-goals

vNext Core does not include:

- Global ranked meta or hero win-rate dashboards
- Lane analytics, matchup rankings, or synergy rankings
- Hero-strength ranking systems or Wilson-score ranking systems
- Draft recommendation engines or 5v5 scoring
- Provider-specific reports offered solely because a source supports them
- Data scraping or paid-provider workarounds as implicit fallback paths

Any future analytics capability requires a separate product decision and does
not inherit Legacy V3 analytics design.
