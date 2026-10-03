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

## 首页与输入框查询模式（四种模式已实现）

本节定义首页赛事列表与快捷查询入口的用户可见行为。它是该交互契约的
唯一归属；数据排序与缓存细节见 [DATA.md](DATA.md)，实现顺序见
[ROADMAP.md](ROADMAP.md)。

近期 Series 的后端读取、共享缓存、只读接口、首页展示和点击发送已实现。输入框
提供赛事查询、英雄攻略、玩家战绩、单局解析四种模式，用同一个自由文本输入框发送
普通聊天消息。模式只附加清晰的纯文本说明，不解析英雄、位置或 ID；真实模型对这些
问题的理解和回答质量仍需单独验收。

### 首页布局与近期赛事

首页按以下顺序组织：DotaMind 品牌区、最近赛事列表、聊天输入框及其模式按钮。
移除硬编码的 TI 宣传内容。品牌图标与名称比原尺寸放大约 20%。最近
赛事最多展示五条，采用轻量列表；每条显示状态、赛事届次名称和日期。赛事名称
组合可用的 League 名称与 Series 名称。已结束赛事优先使用 Series 明确的
Team 胜者；Series 没有 `winner_id` 时，可使用同一 Series 下名称精确匹配
`Playoffs` 的 Tournament 明确 Team 胜者。胜者战队名称解析成功后才追加冠军名称；
来源或名称不可用时不显示冠军。后端最多返回十条候选，首页只显示前五条；当前不提供
额外的候选展开层。桌面行在宽度允许时以单行显示；名称截断时保留完整辅助名称，
日期和可用冠军仍可读。进行中使用蓝色标识，已结束使用绿色标识。

最近赛事行可用鼠标、键盘或触屏操作。点击后直接发送一条普通聊天消息，
其中包含组合显示名称、`Series` 语义和 Series ID，例如：

```text
查询赛事「League 名称 · Series 名称」的最新战况和赛程（赛事届次 Series ID：12345）。
```

该操作直接发送一条普通聊天消息，保留输入框已有草稿和当前查询模式。赛事加载、有效
空列表或数据不可用时均有对应状态；加载和失败不能阻止用户使用聊天输入框。用户可从
首页赛事标题旁显式刷新列表，失败状态仍提供重试。普通查询进度仍显示在消息中。

### 输入框模式与会话抽屉

输入框底部左侧有四个按钮：“赛事查询”“英雄攻略”“玩家战绩”“单局解析”。
普通模式不标注名称；选中模式会在输入区顶部显示粗体名称并切换占位提示。再次点击
当前模式会返回普通聊天，切换模式始终保留已有文字。文字输入接受自由文本，允许在
Steam32 或比赛 ID 后补充要求。发送时只在普通消息前附加一行对应说明：

| 模式 | 发送说明 | 占位提示 |
| --- | --- | --- |
| 赛事查询 | `赛事查询（以赛事届次 Series 为查询对象）：` | 输入赛事名称或你想了解的赛程、战况… |
| 英雄攻略 | `英雄攻略（未指定位置时默认查询全部位置）：` | 输入英雄以及定位，不填定位默认全位置… |
| 玩家战绩 | `玩家战绩（账号使用 Dota 2 好友 ID / Steam32）：` | 输入 Dota 2 好友 ID（Steam32），可补充查询要求… |
| 单局解析 | `单局解析（比赛 ID 为 Valve 单局 ID）：` | 输入比赛 ID，可补充分析要求… |

用户输入内容和换行原样保留。空白输入不能因模式说明而变为可发送内容。聊天记录显示的
文本就是发送给 Agent 的纯文本。Composer 主动发送后，成功交给聊天运行时即清空本次
草稿并返回普通模式，不等待回答结束；会话创建或历史加载失败时保留草稿和模式。发送
准备期间编辑的新草稿不会被清除。切换或新建会话会重置模式，不由应用额外清除运行时
管理的草稿。生成期间仍可编辑下一条消息、切换模式，并保留原有停止行为。

聊天记录侧栏和会话 Trace 抽屉默认收起。桌面宽度达到 1024px 后，二者可独立
展开为左右栏，中间对话在布局变化时继续保持挂载。较窄屏幕使用覆盖式抽屉，
左右互斥，支持遮罩关闭、Escape 和焦点恢复。Trace 仅在右抽屉展开时读取当前
会话，切换会话后旧响应不会显示。桌面抽屉宽度以 180ms 缓动收放；窄屏侧滑，
遮罩同步淡入淡出。减少动态效果设置下关闭过渡。中央对话保持挂载。Test Observer
仍是独立调试入口，悬浮 Trace 按钮为其留出空间。

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
