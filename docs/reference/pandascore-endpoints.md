# PandaScore Dota 2 Endpoint Guide

> PandaScore Dota 2 端点权威指南 / PandaScore Dota 2 Endpoint Authority

This document defines which PandaScore Dota 2 endpoints DotaMind may rely on.

本文档定义 DotaMind 当前允许依赖的 PandaScore Dota 2 API 端点。

PandaScore's official plan classification is the authoritative source for endpoint availability in this project. DotaMind currently allows only endpoints classified as **All plans**.

PandaScore 官方文档中的套餐等级标记，是本项目判断端点可用性的权威依据。DotaMind 当前仅允许依赖标记为 **All plans** 的端点。

---

# 中文

## 1. 项目规则

DotaMind 当前 **仅使用 PandaScore 标记为 `All plans` 的 Dota 2 API 端点**。

以下套餐等级的端点当前均不得作为 DotaMind 运行时能力的依赖：

- `Historical`
- `Historical Pro`

这些端点可能由 PandaScore 官方提供，但不属于当前项目的可用端点白名单。

因此：

```text
PandaScore 官方存在
!=
DotaMind 当前允许使用
```

只有 PandaScore 官方计划等级为 `All plans` 的端点，才能作为当前 PandaScore provider 的基础能力。

如果未来 PandaScore 套餐升级，需要使用 `Historical` 或 `Historical Pro` 端点，应先：

1. 更新本文档中的端点白名单；
2. 明确对应的新 provider 能力与数据合同；
3. 完成相关架构讨论；
4. 再进入实现。

不得因为某个受限端点在开发环境中暂时可调用，就默认将其作为 DotaMind 的稳定依赖。

## 2. 当前允许使用的端点

### 2.1 Match discovery

| 用途 | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| 查询即将开始的 Dota 2 比赛 | [`GET /dota2/matches/upcoming`](https://developers.pandascore.co/reference/get_dota2_matches_upcoming) | All plans | 允许 |
| 查询已经结束的 Dota 2 比赛 | [`GET /dota2/matches/past`](https://developers.pandascore.co/reference/get_dota2_matches_past) | All plans | 允许 |
| 查询正在进行的 Dota 2 比赛 | [`GET /dota2/matches/running`](https://developers.pandascore.co/reference/get_dota2_matches_running) | All plans | 允许 |

### 2.2 Series 与 Tournament discovery

| 用途 | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| 查询 / 搜索 Dota 2 Series | [`GET /dota2/series`](https://developers.pandascore.co/reference/get_dota2_series) | All plans | 允许 |
| 查询即将开始的 Dota 2 Series | [`GET /dota2/series/upcoming`](https://developers.pandascore.co/reference/get_dota2_series_upcoming) | All plans | 允许 |
| 查询正在进行的 Dota 2 Series | [`GET /dota2/series/running`](https://developers.pandascore.co/reference/get_dota2_series_running) | All plans | 允许 |
| 查询已经结束的 Dota 2 Series | [`GET /dota2/series/past`](https://developers.pandascore.co/reference/get_dota2_series_past) | All plans | 允许 |
| 查询 / 搜索 Dota 2 Tournament | [`GET /dota2/tournaments`](https://developers.pandascore.co/reference/get_dota2_tournaments) | All plans | 允许 |
| 查询即将开始的 Dota 2 Tournament | [`GET /dota2/tournaments/upcoming`](https://developers.pandascore.co/reference/get_dota2_tournaments_upcoming) | All plans | 允许 |
| 查询正在进行的 Dota 2 Tournament | [`GET /dota2/tournaments/running`](https://developers.pandascore.co/reference/get_dota2_tournaments_running) | All plans | 允许 |
| 查询已经结束的 Dota 2 Tournament | [`GET /dota2/tournaments/past`](https://developers.pandascore.co/reference/get_dota2_tournaments_past) | All plans | 允许 |

### 2.3 Context & reference data

| 用途 | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| 获取 Dota 2 英雄列表 | [`GET /dota2/heroes`](https://developers.pandascore.co/reference/get_dota2_heroes) | All plans | 允许 |
| 获取指定英雄 | [`GET /dota2/heroes/{id}`](https://developers.pandascore.co/reference/get_dota2_heroes_dota2heroidorslug) | All plans | 允许 |
| 获取 Dota 2 物品列表 | [`GET /dota2/items`](https://developers.pandascore.co/reference/get_dota2_items) | All plans | 允许 |
| 获取指定物品 | [`GET /dota2/items/{id}`](https://developers.pandascore.co/reference/get_dota2_items_dota2itemidorslug) | All plans | 允许 |
| 获取 Dota 2 技能列表 | [`GET /dota2/abilities`](https://developers.pandascore.co/reference/get_dota2_abilities) | All plans | 允许 |
| 获取 / 搜索 Dota 2 选手 | [`GET /dota2/players`](https://developers.pandascore.co/reference/get_dota2_players) | All plans | 允许 |
| 获取 / 搜索 Dota 2 战队 | [`GET /dota2/teams`](https://developers.pandascore.co/reference/get_dota2_teams) | All plans | 允许 |
| 获取 / 搜索 Dota 2 联赛 | [`GET /dota2/leagues`](https://developers.pandascore.co/reference/get_dota2_leagues) | All plans | 允许 |
| 查询指定 Team 的比赛 | [`GET /teams/{team_id_or_slug}/matches`](https://developers.pandascore.co/reference/get_teams_teamidorslug_matches) | All plans | 允许 |

`GET /dota2/teams` 返回的 Team source object 可以包含当前 roster (`players`)。因此，DotaMind 不应仅仅为了获得战队阵容，就假定必须调用额外的 Team detail endpoint。

## 3. 当前禁止依赖的受限端点

以下 endpoint 是 PandaScore 官方 Dota 2 API 的一部分，但其套餐等级不是 `All plans`，因此 **当前不得成为 DotaMind 运行时实现的依赖**。

### 3.1 Match & game data

| 用途 | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| 获取指定 Dota 2 match | [`GET /dota2/matches/{id}`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug) | Historical | 禁止依赖 |
| 获取指定 match 中的 games | [`GET /dota2/matches/{id}/games`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug_games) | Historical | 禁止依赖 |
| 获取指定 Dota 2 game | [`GET /dota2/games/{id}`](https://developers.pandascore.co/reference/get_dota2_games_dota2gameid) | Historical | 禁止依赖 |
| 获取 Dota 2 post-game frames | [`GET /dota2/games/{id}/frames`](https://developers.pandascore.co/reference/get_dota2_games_dota2gameid_frames) | Historical Pro | 禁止依赖 |

### 3.2 Player & team stats

| 用途 | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| 获取选手总体统计 | [`GET /dota2/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_players_playeridorslug_stats) | Historical | 禁止依赖 |
| 获取战队总体统计 | [`GET /dota2/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_teams_teamidorslug_stats) | Historical | 禁止依赖 |
| 获取比赛全部选手统计 | [`GET /dota2/matches/{id}/players/stats`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug_players_stats) | Historical | 禁止依赖 |
| 获取选手 Tournament 统计 | [`GET /dota2/tournaments/{id}/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_tournaments_tournamentidorslug_players_playeridorslug_stats) | Historical | 禁止依赖 |
| 获取战队 Tournament 统计 | [`GET /dota2/tournaments/{id}/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_tournaments_tournamentidorslug_teams_teamidorslug_stats) | Historical | 禁止依赖 |
| 获取选手 Series 统计 | [`GET /dota2/series/{id}/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_players_playeridorslug_stats) | Historical | 禁止依赖 |
| 获取战队 Series 统计 | [`GET /dota2/series/{id}/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_teams_teamidorslug_stats) | Historical | 禁止依赖 |
| 获取战队已完成 games | [`GET /dota2/teams/{id}/games`](https://developers.pandascore.co/reference/get_dota2_teams_teamidorslug_games) | Historical | 禁止依赖 |

## 4. 架构约束

本文档不仅是 PandaScore API 索引，同时也是 PandaScore provider 的能力边界。

设计新的模型工具、Service 或 Adapter 时，不应设计出只能通过受限 PandaScore endpoint 才能实现的合同，再假设底层数据源能够满足。

例如，PandaScore 官方存在 `GET /dota2/matches/{id}`，不意味着“通过 PandaScore 按 ID 获取任意历史 Match 详情”是当前 provider 的基础能力。同样，`GET /dota2/games/{id}` 的存在也不意味着 PandaScore 可以作为当前 DotaMind Game detail 的稳定来源。

能力设计必须从当前白名单出发，而不是从 PandaScore 完整商业 API 能力出发。

## 5. 与 esports discovery 工具接缝的关系

未来的 esports source discovery 工具接缝应建立在允许使用的 `All plans` endpoint 上。例如：

```text
match
  -> /dota2/matches/upcoming
  -> /dota2/matches/past
  -> /dota2/matches/running

team
  -> /dota2/teams
  -> /teams/{team_id_or_slug}/matches（仅用于 Match 的 teams AND 约束）

player
  -> /dota2/players

league
  -> /dota2/leagues

tournament
  -> /dota2/tournaments
  -> /dota2/tournaments/upcoming
  -> /dota2/tournaments/running
  -> /dota2/tournaments/past

series
  -> /dota2/series
  -> /dota2/series/upcoming
  -> /dota2/series/running
  -> /dota2/series/past
```

这些 endpoint 返回的完整 provider source objects 可以写入 source artifact。模型侧应通过未来的 esports discovery 工具、`artifact.read` 和 `artifact.grep` 探索这些 source facts，而不是通过增加依赖 `Historical` endpoint 的 provider-specific detail 工具来绕过当前套餐边界。旧的统一 `esports.search` 合同已删除，重建新合同时必须从本白名单出发。

---

# English

## 1. Project policy

DotaMind currently **uses only PandaScore Dota 2 endpoints classified as `All plans`**.

Endpoints classified as either of the following must not currently become runtime dependencies:

- `Historical`
- `Historical Pro`

These endpoints may officially exist in PandaScore, but they are outside the current DotaMind PandaScore endpoint allowlist.

Therefore:

```text
Officially available in PandaScore
!=
currently allowed in DotaMind
```

Only endpoints whose official PandaScore plan classification is `All plans` may be treated as baseline capabilities of the current PandaScore provider.

If DotaMind adopts a PandaScore plan that enables `Historical` or `Historical Pro` endpoints in the future, the project must first:

1. update the allowlist in this document;
2. define the new provider capabilities and data contracts;
3. review the architectural impact;
4. only then implement the new dependency.

An endpoint must not be treated as a stable DotaMind dependency merely because it happens to be accessible in a development environment.

## 2. Allowed endpoints

### 2.1 Match discovery

| Purpose | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| List upcoming Dota 2 matches | [`GET /dota2/matches/upcoming`](https://developers.pandascore.co/reference/get_dota2_matches_upcoming) | All plans | Allowed |
| List past Dota 2 matches | [`GET /dota2/matches/past`](https://developers.pandascore.co/reference/get_dota2_matches_past) | All plans | Allowed |
| List running Dota 2 matches | [`GET /dota2/matches/running`](https://developers.pandascore.co/reference/get_dota2_matches_running) | All plans | Allowed |

### 2.2 Series and tournament discovery

| Purpose | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| List or search Dota 2 series | [`GET /dota2/series`](https://developers.pandascore.co/reference/get_dota2_series) | All plans | Allowed |
| List upcoming Dota 2 series | [`GET /dota2/series/upcoming`](https://developers.pandascore.co/reference/get_dota2_series_upcoming) | All plans | Allowed |
| List running Dota 2 series | [`GET /dota2/series/running`](https://developers.pandascore.co/reference/get_dota2_series_running) | All plans | Allowed |
| List past Dota 2 series | [`GET /dota2/series/past`](https://developers.pandascore.co/reference/get_dota2_series_past) | All plans | Allowed |
| List or search Dota 2 tournaments | [`GET /dota2/tournaments`](https://developers.pandascore.co/reference/get_dota2_tournaments) | All plans | Allowed |
| List upcoming Dota 2 tournaments | [`GET /dota2/tournaments/upcoming`](https://developers.pandascore.co/reference/get_dota2_tournaments_upcoming) | All plans | Allowed |
| List running Dota 2 tournaments | [`GET /dota2/tournaments/running`](https://developers.pandascore.co/reference/get_dota2_tournaments_running) | All plans | Allowed |
| List past Dota 2 tournaments | [`GET /dota2/tournaments/past`](https://developers.pandascore.co/reference/get_dota2_tournaments_past) | All plans | Allowed |

### 2.3 Context & reference data

| Purpose | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| List Dota 2 heroes | [`GET /dota2/heroes`](https://developers.pandascore.co/reference/get_dota2_heroes) | All plans | Allowed |
| Get a specific hero | [`GET /dota2/heroes/{id}`](https://developers.pandascore.co/reference/get_dota2_heroes_dota2heroidorslug) | All plans | Allowed |
| List Dota 2 items | [`GET /dota2/items`](https://developers.pandascore.co/reference/get_dota2_items) | All plans | Allowed |
| Get a specific item | [`GET /dota2/items/{id}`](https://developers.pandascore.co/reference/get_dota2_items_dota2itemidorslug) | All plans | Allowed |
| List Dota 2 abilities | [`GET /dota2/abilities`](https://developers.pandascore.co/reference/get_dota2_abilities) | All plans | Allowed |
| List or search Dota 2 players | [`GET /dota2/players`](https://developers.pandascore.co/reference/get_dota2_players) | All plans | Allowed |
| List or search Dota 2 teams | [`GET /dota2/teams`](https://developers.pandascore.co/reference/get_dota2_teams) | All plans | Allowed |
| List or search Dota 2 leagues | [`GET /dota2/leagues`](https://developers.pandascore.co/reference/get_dota2_leagues) | All plans | Allowed |
| List matches for a team | [`GET /teams/{team_id_or_slug}/matches`](https://developers.pandascore.co/reference/get_teams_teamidorslug_matches) | All plans | Allowed |

A Team source object returned by `GET /dota2/teams` may already contain its current roster in `players`. DotaMind therefore must not assume that an additional Team detail endpoint is required merely to retrieve the roster.

## 3. Restricted endpoints not currently allowed

The following endpoints are part of the official PandaScore Dota 2 API, but their plan classification is not `All plans`. They therefore **must not currently become runtime dependencies of DotaMind**.

### 3.1 Match & game data

| Purpose | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| Get a specific Dota 2 match | [`GET /dota2/matches/{id}`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug) | Historical | Not allowed |
| List games within a Dota 2 match | [`GET /dota2/matches/{id}/games`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug_games) | Historical | Not allowed |
| Get a specific Dota 2 game | [`GET /dota2/games/{id}`](https://developers.pandascore.co/reference/get_dota2_games_dota2gameid) | Historical | Not allowed |
| Get Dota 2 post-game frames | [`GET /dota2/games/{id}/frames`](https://developers.pandascore.co/reference/get_dota2_games_dota2gameid_frames) | Historical Pro | Not allowed |

### 3.2 Player & team stats

| Purpose | Endpoint | PandaScore Plan | DotaMind |
| --- | --- | --- | --- |
| Get overall player statistics | [`GET /dota2/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_players_playeridorslug_stats) | Historical | Not allowed |
| Get overall team statistics | [`GET /dota2/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_teams_teamidorslug_stats) | Historical | Not allowed |
| Get player statistics for a match | [`GET /dota2/matches/{id}/players/stats`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug_players_stats) | Historical | Not allowed |
| Get player statistics for a tournament | [`GET /dota2/tournaments/{id}/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_tournaments_tournamentidorslug_players_playeridorslug_stats) | Historical | Not allowed |
| Get team statistics for a tournament | [`GET /dota2/tournaments/{id}/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_tournaments_tournamentidorslug_teams_teamidorslug_stats) | Historical | Not allowed |
| Get player statistics for a series | [`GET /dota2/series/{id}/players/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_players_playeridorslug_stats) | Historical | Not allowed |
| Get team statistics for a series | [`GET /dota2/series/{id}/teams/{id}/stats`](https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_teams_teamidorslug_stats) | Historical | Not allowed |
| List finished games for a team | [`GET /dota2/teams/{id}/games`](https://developers.pandascore.co/reference/get_dota2_teams_teamidorslug_games) | Historical | Not allowed |

## 4. Architectural constraint

This document is not only an API index. It defines the capability boundary of the PandaScore provider in DotaMind.

New model tools, services, and adapters must not define contracts that inherently require restricted PandaScore endpoints and then assume that the provider can satisfy them.

For example, the official existence of `GET /dota2/matches/{id}` does not make retrieval of arbitrary historical PandaScore match details by ID a baseline capability of the current provider. Likewise, the existence of `GET /dota2/games/{id}` must not be interpreted as making PandaScore a generally available Game-detail provider for DotaMind.

DotaMind capabilities must be designed from the current endpoint allowlist rather than from the complete commercial PandaScore API surface.

## 5. Relationship to the future esports discovery tool seam

The esports source-discovery tool seam should be built on the allowed `All plans` endpoints. For example:

```text
match
  -> /dota2/matches/upcoming
  -> /dota2/matches/past
  -> /dota2/matches/running

team
  -> /dota2/teams
  -> /teams/{team_id_or_slug}/matches (only for Match `teams` AND constraints)

player
  -> /dota2/players

league
  -> /dota2/leagues

tournament
  -> /dota2/tournaments
  -> /dota2/tournaments/upcoming
  -> /dota2/tournaments/running
  -> /dota2/tournaments/past

series
  -> /dota2/series
  -> /dota2/series/upcoming
  -> /dota2/series/running
  -> /dota2/series/past
```

Complete provider source objects returned by these endpoints may be persisted as source artifacts. The model should explore these facts through the future esports discovery tool, `artifact.read`, and `artifact.grep`, rather than by introducing provider-specific detail tools that depend on `Historical` endpoints outside the current plan boundary. The previous unified `esports.search` contract has been removed; any new contract must be designed from this allowlist.

---

## Raw response snapshots / 真实响应快照

Bounded raw responses captured from the configured PandaScore account are stored under [`pandascore-snapshots/`](pandascore-snapshots/). They are useful implementation references, but they are observations rather than the authoritative endpoint-availability contract.

当前 PandaScore 账号采集的有限原始响应保存在 [`pandascore-snapshots/`](pandascore-snapshots/) 下。它们可以作为实现参考，但属于实测观察，不取代 PandaScore 官方套餐等级与本文档定义的端点白名单。
