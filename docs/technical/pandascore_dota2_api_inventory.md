# PandaScore Dota 2 API inventory

更新时间：2026-08-15。本文只记录当前第一阶段实现实际依赖的 PandaScore
Fixture API 能力，不把网页抓取或付费接口当作备用数据源。

## 官方文档声明

- Dota 2 资源位于 `/dota2` 命名空间，列表请求支持 `page[size]` 和资源过滤器。
- Bearer token 通过 `Authorization: Bearer <token>` 发送。
- Match Fixture 可以包含 `opponents`、`results`、`streams_list` 和 `games`。
- 具体套餐可用资源、字段和速率限制以 PandaScore 账户计划为准。

## 当前免费 token 实测

本次实测使用临时 token 的进程环境变量；token 未写入仓库、日志、fixture 或本文。

| 请求 | 结果 |
|---|---|
| `GET /dota2/series?page[size]=3` | 200，JSON 列表 |
| `GET /dota2/tournaments?page[size]=3` | 200，JSON 列表 |
| `GET /dota2/matches/upcoming?page[size]=3` | 200，JSON 列表 |
| `GET /dota2/matches/running?page[size]=3` | 200，JSON 列表 |
| `GET /dota2/matches/past?page[size]=3` | 200，JSON 列表 |
| `GET /dota2/matches/past?filter[serie_id]=10828&page[size]=100` | 200，TI 2026 过去赛程 |
| `GET /dota2/matches/upcoming?filter[serie_id]=10828&page[size]=100` | 200，TI 2026 后续赛程 |
| `GET /dota2/matches/running?filter[serie_id]=10828&page[size]=100` | 200，TI 2026 进行中赛程 |
| `GET /dota2/tournaments?filter[serie_id]=10828&page[size]=10` | 200，阶段 `Group Stage`（PandaScore tournament 21545） |
| `GET /dota2/matches/past?filter[id]=1631694&page[size]=10` | 200，已知 NGX vs OG Fixture |
| `GET /dota2/series/10828` | 404，当前计划不使用资源详情路径 |
| `GET /dota2/tournaments/21545` | 404，当前计划不使用资源详情路径 |
| `GET /dota2/matches/1631694` | 404，当前计划不使用资源详情路径 |
| `GET /dota2/games/738652` | 403，Game 详情受套餐限制 |

实测 Match 行包含 `opponents`、`results`、`streams_list`、`games`、状态、赛制、
赛程时间和 `detailed_stats`。Game 行包含 `id`、`position`、`match_id`、状态、
时长和时间字段。已知样本 `pandascore_match_id=1631694` 的第一局是
`pandascore_game_id=738652`。

重要边界：在当前免费 Fixture 响应中，`games[*].match_id` 是父级
PandaScore Match ID（例如 1631694），不是 Valve `match_id`；响应没有提供
Valve match ID。付费 Game 详情请求返回 403，因此第一阶段不会伪造或绕过
PandaScore → Valve 映射。当前批量解析工具保留 PandaScore Game context，
下游 OpenDota 工具只接受跨源解析得到的明确 Valve ID。

速率响应包含 `X-Rate-Limit-Remaining`；Transport 只保留数值，不记录认证 Header。
时间字段为带 `Z` 的 ISO 8601 UTC 字符串。实测状态至少包含
`not_started`、`running` 和 `finished`；取消/延期状态按官方枚举保留，未在本次
TI 样本中强行制造。

## 推断 / 尚未验证

- 更高套餐可能通过受限详情资源暴露额外 Game 或 Valve 映射字段，但当前 token
  无法验证，也不属于第一阶段免费能力。
- `detailed_stats=true` 表示 PandaScore Fixture 侧数据可用，不等于 OpenDota
  的 `has_parsed=true`，两者在 Answer 中必须分开归因。
- 赛程实时数量、比分、直播流和进行中状态会变化；代码和文档不固定这些数量。

## 第二阶段跨源映射边界

PandaScore 免费 Fixture 仍不返回 Valve ID。当前的
`dota.resolve_valve_matches` 是显式的跨源推断，接收
`pandascore.resolve_match_games` 返回的全部实际 Game context：

```text
PandaScore series/match/game
  -> OpenDota league name + year
  -> OpenDota team ids
  -> start time <= 1800s
  -> duration <= 5s
  -> sorted series game position
  -> winner consistency
  -> unique Valve match_id
```

它按局输出 `method=inferred_cross_source`、候选数量、匹配信号和时间/时长差，
不声称 PandaScore 原生提供了 Valve ID。联赛、战队或比赛存在歧义时保持
`ambiguous_*` 状态；没有唯一候选时不使用 closest/weighted fallback。已知
样本的 OpenDota 侧为 league `19719`、series `1130066`、Valve match
`8943244303`；同名 Nigma 候选通过 `/teams/{team_id}/matches` 的精确
`leagueid=19719` 参赛记录唯一消歧为 `10136357`。样本映射仍属于推断而非
PandaScore 原生字段。

## P2.2 赛事届次解析

`pandascore.resolve_competition` 不依赖 `/dota2/series` 返回顺序。查询中的独立
四位年份会被解析为显式届次；`year` 参数与查询年份冲突时由输入校验拒绝。
名称匹配按 series name/full label、parent league exact、label substring 分为
3/2/1 级，只保留最高级候选。没有显式年份时按当前时间优先选择进行中、最近
已开始/结束、最近即将开始的届次；同一时间仍无法唯一确定则返回 `ambiguous`。
响应的 `selection` 元数据记录模式、请求/选中年份、匹配等级和选择前候选数量。
这些是 DotaMind 的确定性选择语义，不是 PandaScore 原生的 `latest` 字段。

## P2.2.1 年份过滤下推

当用户显式给出年份（query 中提取或输入 `year`）时，
`PandaScoreCompetitions.list_series(year=...)` 将其发送为
`filter[year]`；缺省年份不发送该参数。Resolver 先取得该年份的 eligible rows，
再执行名称匹配等级，避免默认第一页中的其他年份候选把历史届次排除。显式年份
不存在时保持 `not_found`，不会回退到最新届；无年份仍使用 active → latest
historical → nearest future 选择。
