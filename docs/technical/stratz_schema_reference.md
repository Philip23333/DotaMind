# STRATZ GraphQL Schema Reference

> Generated from STRATZ official GraphQL introspection. Re-run
> `python apps/api/scripts/stratz_schema_docs.py` to refresh.

Raw schema JSON: `stratz_schema_introspection.json`

## Root Types

- query: `DotaQuery`
- mutation: `DotaMutation`
- subscription: `DotaSubscription`

## Focus: HeroStatsQuery

These fields are the authoritative schema source for current STRATZ
tooling decisions around weekly lane data and daily hero trends.

Implementation notes:

- `HeroStatsQuery.winDay` is the official day-grain source for
  hero trend charts. Compute win rate as `winCount / matchCount`.
- `HeroStatsQuery.laneOutcome`, `heroVsHeroMatchup`, and `stats`
  use provider week epochs (`week: Long`) and should remain modeled
  as weekly buckets in DotaMind.
- The schema description for `week` says null gives the current week;
  DotaMind's live probe on 2026-07-03 found null matched the latest
  completed week. Treat the schema as the field contract, and
  `docs/design/tools/time_patch_filtering.md` as the empirical behavior
  record for null-week semantics.

### `HeroStatsQuery.winDay`

Type: `[HeroWinDayType]`

Returns the last 12 days by day showing the amount of matches and the amount of wins by hero id.

Arguments:

- `heroIds`: `[Short]` - An array of hero ids to include in this query, excluding all results that do not include one of these heroes.
- `take`: `Int` - The amount to have returned in your query. The maximum of this is always dynamic. Limit :
- `skip`: `Int` - The amount of data to skip before collecting your query. This is useful for Paging.
- `bracketIds`: `[RankBracket]` - An array of rank ids to include in this query, excluding all results that do not include one of these ranks. The value ranges from 0-8 with 0 being unknown MMR and 1-8 is low to high MMR brackets. Example 7 is Divine.
- `positionIds`: `[MatchPlayerPositionType]` - An array of positions ids (enum MatchPlayerPositionType) to include in this query, excluding all results that do not include one of these lanes.
- `regionIds`: `[BasicRegionType]` - An array of region ids to include in this query, excluding all results that do not include one of these regions.
- `gameModeIds`: `[GameModeEnumType]` - An array of game mode ids to include in this query, excluding all results that do not include one of these game modes.
- `groupBy`: `FilterHeroWinRequestGroupBy` - Only used when doing matchesGroupBy endpoint. This is how the data will be grouped and makes your return Id field.

Return fields on `HeroWinDayType`:

- `day`: `Long!`
- `heroId`: `Short!`
- `winCount`: `Int!`
- `matchCount`: `Int!`

### `HeroStatsQuery.laneOutcome`

Type: `[HeroLaneOutcomeType]`

Using out formula for determining the outcome of lane, the overall success of that hero in that role.

Arguments:

- `heroId`: `Short` - The hero id to include in this query, excluding all results that do not include this hero.
- `isWith`: `Boolean!` - The lane outcomes are split into with heroes and against. Send false if you want lane matchups against the heroid. Send true if you want friendly.
- `week`: `Long` - The week to include in this query, excluding all results that do not include this week. The value is an epoc TimeStamp of the week of data you want. Leaving null gives the current week.
- `bracketBasicIds`: `[RankBracketBasicEnum]` - An array of rank ids to include in this query, excluding all results that do not include one of these ranks. The value ranges from 0-8 with 0 being unknown MMR and 1-8 is low to high MMR brackets. Example 7 is Divine.
- `positionIds`: `[MatchPlayerPositionType]` - An array of positions ids (enum MatchPlayerPositionType) to include in this query, excluding all results that do not include one of these lanes.

Return fields on `HeroLaneOutcomeType`:

- `heroId1`: `Int!`
- `week`: `Int!`
- `bracketBasicIds`: `RankBracketBasicEnum`
- `position`: `MatchPlayerPositionType`
- `matchCount`: `Long`
- `drawCount`: `Long`
- `winCount`: `Long`
- `lossCount`: `Long`
- `stompWinCount`: `Long`
- `stompLossCount`: `Long`
- `matchWinCount`: `Long`
- `csCount`: `Long`
- `heroId2`: `Short!`

### `HeroStatsQuery.heroVsHeroMatchup`

Type: `HeroMatchupType`

This is used on the Hero page to show the comparison of skill with the selected hero with other heroes. It includes our Synergy and our Advantage formulas to ensure that a hero with a high win rate isn't simply just on the top of all the fields.

Arguments:

- `heroId`: `Short!` - The hero id to include in this query, excluding all results that do not include this hero.
- `week`: `Long` - The week to include in this query, excluding all results that do not include this week. The value is an epoc TimeStamp of the week of data you want. Leaving null gives the current week.
- `bracketBasicIds`: `[RankBracketBasicEnum]` - An array of rank ids to include in this query, excluding all results that do not include one of these ranks. The value ranges from 0-8 with 0 being unknown MMR and 1-8 is low to high MMR brackets. Example 7 is Divine.
- `matchLimit`: `Int` - Minimum amount of MatchCount required for a Duo to qualify
- `skip`: `Int` - The amount of data to skip before collecting your query. This is useful for Paging.
- `take`: `Int` - The amount to have returned in your query. The maximum of this is always dynamic. Limit :

Return fields on `HeroMatchupType`:

- `advantage`: `[HeroDryadType]`
- `disadvantage`: `[HeroDryadType]`

### `HeroStatsQuery.stats`

Type: `[HeroPositionTimeDetailType]`

Detailed output of data per minute for each hero.

Arguments:

- `heroIds`: `[Short]` - An array of hero ids to include in this query, excluding all results that do not include one of these heroes.
- `week`: `Long` - The week to include in this query, excluding all results that do not include this week. The value is an epoc TimeStamp of the week of data you want. Leaving null gives the current week.
- `bracketBasicIds`: `[RankBracketBasicEnum]` - An array of rank ids to include in this query, excluding all results that do not include one of these ranks. The value ranges from 0-8 with 0 being unknown MMR and 1-8 is low to high MMR brackets. Example 7 is Divine.
- `positionIds`: `[MatchPlayerPositionType]` - An array of positions ids (enum MatchPlayerPositionType) to include in this query, excluding all results that do not include one of these lanes.
- `groupByTime`: `Boolean`
- `groupByPosition`: `Boolean`
- `groupByBracket`: `Boolean`
- `minTime`: `Int` - Integer in minutes which determines the start of the data. For example, 10 would result in every event after 10:00 mark in-game. Minimum input value is 0.
- `maxTime`: `Int` - Integer in minutes which determines the start of the data. For example, 10 would result in every event before 10:00 mark in-game Maximum input value is 75.

Return fields on `HeroPositionTimeDetailType`:

- `heroId`: `Short!`
- `week`: `Int!`
- `time`: `Int!`
- `position`: `MatchPlayerPositionType`
- `bracketBasicIds`: `RankBracketBasicEnum`
- `matchCount`: `Long`
- `remainingMatchCount`: `Long`
- `winCount`: `Long`
- `mvp`: `Decimal`
- `topCore`: `Decimal`
- `topSupport`: `Decimal`
- `courierKills`: `Decimal`
- `apm`: `Decimal`
- `casts`: `Decimal`
- `abilityCasts`: `Decimal`
- `kills`: `Decimal`
- `deaths`: `Decimal`
- `assists`: `Decimal`
- `networth`: `Decimal`
- `xp`: `Decimal`
- `cs`: `Decimal`
- `dn`: `Decimal`
- `neutrals`: `Decimal`
- `heroDamage`: `Decimal`
- `towerDamage`: `Decimal`
- `physicalDamage`: `Decimal`
- `magicalDamage`: `Decimal`
- `physicalDamageReceived`: `Decimal`
- `magicalDamageReceived`: `Decimal`
- `tripleKill`: `Decimal`
- `ultraKill`: `Decimal`
- `rampage`: `Decimal`
- `godLike`: `Decimal`
- `goldPerMinute`: `Decimal`
- `disableCount`: `Decimal`
- `disableDuration`: `Decimal`
- `stunCount`: `Decimal`
- `stunDuration`: `Decimal`
- `slowCount`: `Decimal`
- `slowDuration`: `Decimal`
- `healingSelf`: `Decimal`
- `healingAllies`: `Decimal`
- `invisibleCount`: `Decimal`
- `runePower`: `Decimal`
- `runeBounty`: `Decimal`
- `level`: `Decimal`
- `campsStacked`: `Decimal`
- `supportGold`: `Decimal`
- `purgeModifiers`: `Decimal`
- `ancients`: `Decimal`
- `teamKills`: `Decimal`
- `goldLost`: `Decimal`
- `goldFed`: `Decimal`
- `buybackCount`: `Decimal`
- `weakenCount`: `Decimal`
- `weakenDuration`: `Decimal`
- `physicalItemDamage`: `Decimal`
- `magicalItemDamage`: `Decimal`
- `healingItemSelf`: `Decimal`
- `healingItemAllies`: `Decimal`
- `xpFed`: `Decimal`
- `pureDamageReceived`: `Decimal`
- `attackDamage`: `Decimal`
- `attackCount`: `Decimal`
- `castDamage`: `Decimal`
- `damageReceived`: `Decimal`
- `damage`: `Decimal`
- `pureDamage`: `Decimal`
- `kDAAverage`: `Decimal`
- `killContributionAverage`: `Decimal`
- `stompWon`: `Decimal`
- `stompLost`: `Decimal`
- `comeBackWon`: `Decimal`
- `comeBackLost`: `Decimal`

## Relevant Enums

### `RankBracket`

- `UNCALIBRATED`
- `HERALD`
- `GUARDIAN`
- `CRUSADER`
- `ARCHON`
- `LEGEND`
- `ANCIENT`
- `DIVINE`
- `IMMORTAL`

### `RankBracketBasicEnum`

- `UNCALIBRATED`
- `HERALD_GUARDIAN`
- `CRUSADER_ARCHON`
- `LEGEND_ANCIENT`
- `DIVINE_IMMORTAL`
- `FILTERED`
- `ALL`

### `MatchPlayerPositionType`

- `POSITION_1`
- `POSITION_2`
- `POSITION_3`
- `POSITION_4`
- `POSITION_5`
- `UNKNOWN`
- `FILTERED`
- `ALL`

### `GameModeEnumType`

- `NONE`
- `ALL_PICK`
- `CAPTAINS_MODE`
- `RANDOM_DRAFT`
- `SINGLE_DRAFT`
- `ALL_RANDOM`
- `INTRO`
- `THE_DIRETIDE`
- `REVERSE_CAPTAINS_MODE`
- `THE_GREEVILING`
- `TUTORIAL`
- `MID_ONLY`
- `LEAST_PLAYED`
- `NEW_PLAYER_POOL`
- `COMPENDIUM_MATCHMAKING`
- `CUSTOM`
- `CAPTAINS_DRAFT`
- `BALANCED_DRAFT`
- `ABILITY_DRAFT`
- `EVENT`
- `ALL_RANDOM_DEATH_MATCH`
- `SOLO_MID`
- `ALL_PICK_RANKED`
- `TURBO`
- `MUTATION`
- `UNKNOWN`

### `BasicRegionType`

- `CHINA`
- `SEA`
- `NORTH_AMERICA`
- `SOUTH_AMERICA`
- `EUROPE`

### `FilterHeroWinRequestGroupBy`

- `HERO_ID`
- `ALL`
- `HERO_ID_DURATION_MINUTES`
- `TIME`
- `HERO_ID_POSITION_BRACKET`
