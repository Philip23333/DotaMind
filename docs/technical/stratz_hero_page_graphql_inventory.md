# STRATZ Hero Page GraphQL Inventory

Capture target: `https://stratz.com/heroes/8` (Juggernaut / 主宰)

Capture date: 2026-07-01

This inventory records GraphQL operations observed from the STRATZ hero page tabs. Requests marked as `captured` were observed through Playwright network interception against local Chrome. Requests marked as `user-captured` came from the user's DevTools payload. Some tabs were blocked by STRATZ anti-bot/captcha during automated capture; those are listed as not captured instead of being inferred as exact website payloads.

## Capture Notes

- Automated Playwright capture was able to observe GraphQL requests for Leaderboard, Guides, Matchups, and Graphs Time.
- Later browser sessions hit a STRATZ captcha page, so Overview, Graphs default redirect, Attributes, Abilities, and Items did not emit reliable captured GraphQL payloads in automation.
- `/heroes/8/graphs/rank` was confirmed from the user's DevTools screenshot/payload as `GetGraphsRank`.
- The Matchups page uses `heroStats.heroVsHeroMatchup`, not `heroStats.laneOutcome`.

## Tab Summary

| Tab | URL | Status | Operation(s) |
| --- | --- | --- | --- |
| 概况 | `https://stratz.com/heroes/8` | not captured | None observed in automated capture |
| 排行榜 | `https://stratz.com/heroes/8/leaderboard` | captured | `LeaderboardHero` |
| 攻略 | `https://stratz.com/heroes/8/guides` | captured | `HeroGuidesCount`, `HeroGuides` |
| 对抗 | `https://stratz.com/heroes/8/matchups` | captured | `GetHeroMatchUps` |
| 图表 | `https://stratz.com/heroes/8/graphs` | not captured | Redirect/container; use `time` or `rank` subroute |
| 时间 | `https://stratz.com/heroes/8/graphs/time` | captured | `GetGraphsTime` |
| 段位 | `https://stratz.com/heroes/8/graphs/rank` | user-captured | `GetGraphsRank` |
| 属性 | `https://stratz.com/heroes/8/attributes` | not captured | None observed in automated capture |
| 技能 | `https://stratz.com/heroes/8/abilities` | not captured | None observed in automated capture |
| 物品 | `https://stratz.com/heroes/8/items` | not captured | None observed in automated capture |

## 排行榜 / Leaderboard

URL: `https://stratz.com/heroes/8/leaderboard`

Status: captured

Purpose: lists top players for the selected hero and bracket.

Variables:

```json
{
  "request": {
    "heroIds": [8],
    "bracketIds": ["IMMORTAL"],
    "take": 50
  }
}
```

Query:

```graphql
query LeaderboardHero($request: FilterLeaderboardHeroRequestType!) {
  leaderboard {
    hero(request: $request) {
      heroId
      impAverage
      losses
      regionId
      wins
      position
      steamAccount {
        id
        avatar
        name
        seasonLeaderboardRank
        seasonRank
        smurfFlag
        proSteamAccount {
          name
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
```

## 攻略 / Guides

URL: `https://stratz.com/heroes/8/guides`

Status: captured

Purpose: retrieves guide counts per position and paginated guide previews. The same `HeroGuides` query is repeated with different `skip` values as more guide rows are loaded.

Variables for guide counts:

```json
{
  "heroId": 8
}
```

Query:

```graphql
query HeroGuidesCount(
  $heroId: Short!,
  $itemId: Short,
  $isPro: Boolean,
  $withHeroId: Short,
  $againstHeroId: Short
) {
  heroStats {
    POSITION_1: guide(
      heroId: $heroId
      positionId: POSITION_1
      itemId: $itemId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
    }
    POSITION_2: guide(
      heroId: $heroId
      positionId: POSITION_2
      itemId: $itemId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
    }
    POSITION_3: guide(
      heroId: $heroId
      positionId: POSITION_3
      itemId: $itemId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
    }
    POSITION_4: guide(
      heroId: $heroId
      positionId: POSITION_4
      itemId: $itemId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
    }
    POSITION_5: guide(
      heroId: $heroId
      positionId: POSITION_5
      itemId: $itemId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
    }
  }
}
```

Variables for guide previews:

```json
{
  "heroId": 8,
  "skip": 10,
  "take": 10
}
```

Query:

```graphql
query HeroGuides(
  $heroId: Short!,
  $positionId: MatchPlayerPositionType,
  $isPro: Boolean,
  $skip: Int!,
  $take: Int!,
  $itemId: Short,
  $withHeroId: Short,
  $againstHeroId: Short
) {
  heroStats {
    guide(
      heroId: $heroId
      positionId: $positionId
      isPro: $isPro
      withHeroId: $withHeroId
      againstHeroId: $againstHeroId
    ) {
      heroId
      matchCount
      guides(skip: $skip, take: $take, itemId: $itemId) {
        heroId
        ...GuidePreviewHeroGuide
        __typename
      }
      __typename
    }
    __typename
  }
}

fragment GuidePreviewHeroGuide on HeroGuideType {
  heroId
  match {
    id
    durationSeconds
    players {
      matchId
      steamAccountId
      heroId
      position
      __typename
    }
    __typename
  }
  matchPlayer {
    matchId
    steamAccountId
    heroId
    position
    steamAccount {
      id
      name
      proSteamAccount {
        name
        __typename
      }
      __typename
    }
    assists
    deaths
    imp
    isRadiant
    item0Id
    item1Id
    item2Id
    item3Id
    item4Id
    item5Id
    neutral0Id
    kills
    additionalUnit {
      item0Id
      item1Id
      item2Id
      item3Id
      item4Id
      item5Id
      neutral0Id
      __typename
    }
    stats {
      itemPurchases {
        itemId
        time
        __typename
      }
      level
      __typename
    }
    level
    abilities {
      abilityId
      time
      __typename
    }
    __typename
  }
  __typename
}
```

## 对抗 / Matchups

URL: `https://stratz.com/heroes/8/matchups`

Status: captured

Purpose: powers hero matchup, counter, ally, and bad-pairing panels. This is the most relevant page for draft advice and hero pairing tools.

Important interpretation:

- `advantage.with`: same-team ally pairing data.
- `advantage.vs`: opponent matchup/counter data.
- `matchCountWith`: total same-team sample count for the hero group.
- `matchCountVs`: total against sample count for the hero group.
- `synergy`: STRATZ's score used for matchup/pairing ranking.
- `matchCount` and `winCount`: sample size and wins for a specific pair.

Variables:

```json
{
  "heroId": 8,
  "matchLimit": 0
}
```

The user also captured a variant with:

```json
{
  "heroId": 8,
  "matchLimit": 0,
  "bracketBasicIds": "LEGEND_ANCIENT"
}
```

Query:

```graphql
query GetHeroMatchUps(
  $heroId: Short!,
  $matchLimit: Int!,
  $bracketBasicIds: [RankBracketBasicEnum]
) {
  heroStats {
    heroVsHeroMatchup(
      heroId: $heroId
      matchLimit: $matchLimit
      bracketBasicIds: $bracketBasicIds
    ) {
      advantage {
        heroId
        matchCountWith
        matchCountVs
        with {
          heroId2
          matchCount
          winCount
          synergy
          __typename
        }
        vs {
          heroId2
          matchCount
          winCount
          synergy
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
```

## 图表 / 时间

URL: `https://stratz.com/heroes/8/graphs/time`

Status: captured

Purpose: charts win count and match count across recent days for the selected hero and all heroes.

Variables:

```json
{
  "heroIds": [8]
}
```

Query:

```graphql
query GetGraphsTime(
  $heroIds: [Short!]!,
  $bracketIds: [RankBracket],
  $positionIds: [MatchPlayerPositionType],
  $regionIds: [BasicRegionType],
  $gameModeIds: [GameModeEnumType]
) {
  heroStats {
    hero: winDay(
      take: 8
      heroIds: $heroIds
      bracketIds: $bracketIds
      positionIds: $positionIds
      regionIds: $regionIds
      gameModeIds: $gameModeIds
    ) {
      ...HeroDayFragment
      __typename
    }
    allHeroes: winDay(
      take: 8
      groupBy: ALL
      bracketIds: $bracketIds
      positionIds: $positionIds
      regionIds: $regionIds
      gameModeIds: $gameModeIds
    ) {
      ...AllHeroesDayFragment
      __typename
    }
    __typename
  }
}

fragment HeroDayFragment on HeroWinDayType {
  timestamp: day
  matchCount
  winCount
  __typename
}

fragment AllHeroesDayFragment on HeroWinDayType {
  timestamp: day
  matchCount
  __typename
}
```

## 图表 / 段位

URL: `https://stratz.com/heroes/8/graphs/rank`

Status: user-captured

Purpose: charts hero win rate, pick rate, and match count by rank bracket.

Variables from DevTools:

```json
{
  "heroIds": [8]
}
```

Observed operation:

```graphql
query GetGraphsRank(
  $heroIds: [Short!]!,
  $positionIds: [MatchPlayerPositionType],
  ...
) {
  ...
}
```

Notes:

- The screenshot confirms `operationName: "GetGraphsRank"` and `variables.heroIds: [8]`.
- The full query body was not fully captured in automation because Playwright sessions began receiving STRATZ captcha pages.
- The visible page charts win rate, pick rate, and match volume across rank brackets.

## Not Captured Yet

These tabs did not produce reliable GraphQL payloads during automated capture because STRATZ returned a captcha page or rendered data without a visible browser-side GraphQL POST:

- 概况: `https://stratz.com/heroes/8`
- 图表 container: `https://stratz.com/heroes/8/graphs`
- 属性: `https://stratz.com/heroes/8/attributes`
- 技能: `https://stratz.com/heroes/8/abilities`
- 物品: `https://stratz.com/heroes/8/items`

To complete these exactly, launch Chrome with remote debugging enabled and use the already verified listener against the authenticated/verified browser session:

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir="$env:TEMP\\stratz-cdp-profile"
```

Then open STRATZ, solve any captcha/login prompt once, and re-run the network capture against the CDP endpoint.

## Implementation Implications

- For hero pair/counter tools, prefer `heroStats.heroVsHeroMatchup` with both `with` and `vs`; do not use `laneOutcome` for ally/counter recommendations.
- A project tool such as `stratz.hero_matchups` or `stratz.hero_synergy` should expose:
  - target `hero_id`
  - optional rank bracket filters
  - optional minimum match count
  - mode/read side: `with` for allies and `vs` for opponents
- The existing project query in `apps/api/app/integrations/stratz/heroes.py` currently requests only `vs` and omits `with`, so it cannot fully reproduce STRATZ's ally-pairing panels.
