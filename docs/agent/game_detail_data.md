# Game Detail Data Contract

## Status, purpose, and boundaries

This document is the sole detailed data contract for `game.detail`.

- **Current implementation:** `game.detail` returns the complete validated OpenDota source object in `data`.
- **Accepted target:** `data` is an explicit DotaMind DTO containing source facts and necessary deterministic transformations.
- **Implementation status:** the closed DTO and eight-section OpenDota projector are implemented and tested offline. The public Service still returns the full OpenDota object; connecting the projector to the tool and verifying that public output is a separate pending step. Additional field candidates and opaque source-code meanings below remain unresolved.
- **Use:** minute-by-minute state review and final-game statistics.
- **Outside this contract:** performance ratings, role inference, lane-win judgments, teamfight classification, review recommendations, counterfactuals, simulated inventory states, and continuous map replay.

This describes data and tool behavior. It does not define a frontend page or visual layout.

## Input, envelope, and identity

The model-facing input remains:

    game.detail(valve_game_id)

The result keeps one outer provenance envelope:

| Field | Type | Meaning |
|---|---|---|
| `valve_game_id` | positive integer | Requested canonical Valve single-game identity |
| `provider` | `"opendota"` | Source that supplied the game record |
| `retrieved_at` | timezone-aware timestamp | Time DotaMind retrieved the response |
| `data` | `GameDetailData` | The eight governed sections below |

The eight sections in `data` are `match`, `draft`, `players`, `economy`, `builds`, `events`, `interactions`, and `coverage`. Each section appears once. Section fields use `null` for missing or unknown source facts; source-declared empty collections remain empty collections.

OpenDota `match_id` must be a positive integer equal to the requested `valve_game_id` before a successful result can be returned. The source identity check remains at the provider boundary. The DTO does not repeat `provider`, `retrieved_at`, or `valve_game_id` inside `data.match`.

The result and its Artifact contain the complete governed DTO. They contain no `raw` field and expose no model-facing handle that retrieves the original OpenDota object. Generic Artifact read and grep continue to read the stored DTO without provider-specific behavior.

The internal/public type split is implemented: the OpenDota adapter returns `OpenDotaGameRecord` with native `match_id`, provider, retrieval time, and complete source data. The resolver consumes that record directly. `GameDetailService` separately constructs the public `GameDetailResult`; it currently preserves the full source body. The eight-section projection will belong at this Service boundary. Internal records are not public retrieval handles, and future DTO conversion must leave the resolver's source values intact.

## Global data rules

| Situation | Contract |
|---|---|
| Source field is missing, null, or explicitly unknown | Emit `null`; do not substitute zero |
| Source explicitly provides an empty array or object | Preserve `[]` or `{}` |
| Source explicitly provides `0` or `false` | Preserve the value |
| Field rename or enum mapping | Record the source path and exact mapping below; leave unrecognized values unknown |
| Deterministic accumulation | State the formula, input facts, ordering, and missing-input behavior |
| Source facts disagree | Preserve the values and record a material conflict; do not select a winner |
| Time values | Keep calendar date, exact match seconds, minute samples, and final statistics distinct |
| Static names and images | Keep them outside recorded-game facts; do not use the current catalog to infer historical mechanics |
| Semantics not verified | Mark them pending; do not assign a business meaning |

Counts, ordering, and field mappings are data transformations, not performance judgments. Each still needs a reproducible rule.

## Section contracts

Every section below states its responsibility, target fields and types, source, transformation, and missing-data behavior. Where the plan has not approved an exact field list or source meaning, this document marks it pending instead of inventing a default.

### 1. `match`

**Responsibility:** identify the recorded game context and its result.

| Target field | Type | Source and rule |
|---|---|---|
| `match_date` | `YYYY-MM-DD` string or `null` | Convert source `start_time` from Unix seconds using `Asia/Shanghai`. If unavailable or invalid, emit `null`. |
| `duration_seconds` | integer or `null` | Source `duration`, representing formal game duration. Do not add `pre_game_duration` or expose a second pre-game duration. |
| `game_winner` | `"radiant"`, `"dire"`, or `null` | Strict mapping: `radiant_win=true` gives `radiant`; `false` gives `dire`; absent or unknown gives `null`. |
| `score` | object or `null` | Preserve source `radiant_score` and `dire_score` under those side keys. |
| `competition` | currently `null` | Reserved pending approval of an exact field list; the offline projector does not copy a League body or infer competition facts. This unapproved projection is not reported as a per-game source gap. |
| `teams` | side-keyed object or `null` | Preserve this game's OpenDota radiant and dire team identities using the confirmed minimal fields below. |

Each available `teams.radiant` or `teams.dire` record contains `source_team_id` (integer or `null`) and `name` (string or `null`). Read them from `radiant_team.team_id/name` and `dire_team.team_id/name`, respectively. Missing team records remain `null`. Additional fields such as team tags, logos, and captain IDs are candidates, not part of this confirmed minimum.

The side keys `radiant` and `dire` associate facts within this game. An OpenDota team ID remains an OpenDota identity and is never presented as a PandaScore team ID. PandaScore opponent-list order does not assign sides. If another capability has accepted a same-game team-to-side association, a converter may use that accepted result. `game.detail` does not query PandaScore or guess an association from names. A direct Valve-ID lookup can still return the OpenDota game record's own side-keyed team facts. If the two source identities cannot be associated clearly, keep them separate. Do not create a permanent cross-source Team map.

The exact source timestamp is an internal conversion dependency. The public field is `match_date`; implementation must preserve access to the original validated `start_time` until any dependent converter has finished. The raw timestamp is not an Artifact side channel.

### 2. `draft`

**Responsibility:** ordered pick and ban facts.

| Target field | Type | Source and rule |
|---|---|---|
| `picks_bans` | list or `null` | Source `picks_bans`, retaining source array order |
| `order` | integer or `null` | Source `order` |
| `action` | `"ban"`, `"pick"`, or `null` | `is_pick=true` maps to `pick`; `false` maps to `ban`; absent or unknown remains `null` |
| `hero_id` | integer or `null` | Source Valve hero ID |
| `side` | `"radiant"`, `"dire"`, or `null` | Within `picks_bans` only, source `team=0` maps to `radiant` and `team=1` maps to `dire`; other values remain `null` |

This `team` mapping is local to the pick/ban array. It does not define the meaning of `team` in objectives or other event records. Do not infer draft phase, action time, or timing from `timings`.

### 3. `players`

**Responsibility:** preserve per-player identity, final statistics, and source-aligned minute observations.

Each player has three parts: `identity`, `final_stats`, and `minute_timeline`. Keep player records in source array order.

`identity` contains `account_id`, `player_slot`, and `hero_id` as nullable source IDs, plus source-provided `name` and `personaname` as nullable strings. It also contains `side` (`"radiant"`, `"dire"`, or `null`): strictly map `players[].isRadiant=true` to `radiant` and `false` to `dire`; missing or unknown values remain `null`. `account_id` is the cross-game account identifier when supplied. `player_slot` associates rows within this game; it is not a position from one to five. Names are labels, never identity proof. `hero_variant` is outside the core contract; do not interpret zero as a particular facet.

`final_stats` contains these confirmed final scoreboard, farming/economy, and combat statistics. Every source path is relative to that player's OpenDota record:

| Target fields | Type of each field | Source |
|---|---|---|
| `kills`, `deaths`, `assists` | integer or `null` | Same-name source fields |
| `level` | integer or `null` | `level` |
| `last_hits`, `denies` | integer or `null` | Same-name source fields |
| `net_worth` | number or `null` | `net_worth` |
| `hero_damage`, `tower_damage`, `hero_healing` | number or `null` | Same-name source fields |

These are final values, not values copied from the last minute sample. Assists and level have final values only; hero damage, tower damage, and hero healing also stay here rather than entering the first-version minute timeline. Missing source values are `null`; explicit zeros remain zero.

Additional early candidates still need a retention decision: wallet/spend/rate fields (`gold`, `gold_spent`, `gold_per_min`, `xp_per_min`); `stuns`; ward/resource counts (`obs_placed`, `sen_placed`, `camps_stacked`, `creeps_stacked`, `rune_pickups`); unit-category kill counts (`neutral_kills`, `lane_kills`, `ancient_kills`, `tower_kills`, `roshan_kills`, `courier_kills`, `observer_kills`, `sentry_kills`); and `buyback_count`, `actions_per_min`, `pings`, `life_state_dead`, `leaver_status`. They are not included in the confirmed minimum merely because an experimental DTO retained them. In particular, a source wallet value must never be replaced by cumulative `gold_t`.

`minute_timeline` is a list of records with these eight fields:

| Field | Type | Source and rule |
|---|---|---|
| `time_seconds` | integer or `null` | Source `times` entry, in game seconds |
| `net_worth` | number or `null` | Same-index `networth_t` value |
| `earned_gold` | number or `null` | Same-index `gold_t` value; this is cumulative gold, not wallet balance |
| `experience` | number or `null` | Same-index `xp_t` value |
| `last_hits` | number or `null` | Same-index `lh_t` value |
| `denies` | number or `null` | Same-index `dn_t` value |
| `kills` | integer or `null` | Count that player's valid kill-log records with event time less than or equal to this node's time |
| `deaths` | integer or `null` | Count that player's valid death-log records with event time less than or equal to this node's time |

The six direct metrics use the same index from `times` and their corresponding player arrays. Do not align arrays from different players by position without verifying their time values. Do not interpolate gaps or append final statistics to the last minute node. Kill and death accumulation includes valid source events before time zero. If a required event log is absent, its curve is unavailable (`null` at the affected nodes), not an invented zero curve. Do not add minute assists or levels.

### 4. `economy`

**Responsibility:** team-level advantage facts and their time basis. Player minute metrics stay under `players.minute_timeline`.

The source `radiant_gold_adv` remains named as the source's gold-advantage fact; it is not renamed to net-worth difference. `gold_t` is cumulative earned gold and must not be described as wallet balance. A calculated team net-worth difference is not part of this contract. Adding one later would require a stated source and summation formula.

| Target field | Type | Source and rule |
|---|---|---|
| `radiant_gold_adv` | nullable-number array or `null` | Preserve source samples; an invalid or unknown individual value remains `null` with a coverage gap. |
| `radiant_xp_adv` | nullable-number array or `null` | Preserve source samples with the same missing-value rule. |
| `time_seconds` | integer array or `null` | Reuse a player's `times` axis only after verifying all player axes agree and both team arrays have matching lengths and index correspondence. |

Do not assume every player array shares the same axis or that an advantage array can be aligned merely because lengths match. When correspondence cannot be established, leave the affected axis or series unavailable and report only a material promised-data gap or conflict.

The offline projector requires strictly increasing integer player axes; each metric must match its own player's axis length. A mismatched metric becomes unknown for those nodes without truncating other metrics. Invalid event times make that cumulative curve unavailable rather than silently undercounting. For team advantages, all provided player axes must agree, start at zero, and follow the source's minute buckets (`0, 60, ...`); both team arrays must also match that axis length. Otherwise keep the source advantage arrays with `time_seconds=null` and a coverage reason. The minute-bucket semantics are documented by the [OpenDota API schema](https://api.opendota.com/api); no team net-worth difference is added.

The first-version team fields are the two source advantage arrays and their verified time axis listed above. Validate availability and correspondence for each response; additional economy fields require a separate decision.

### 5. `builds`

**Responsibility:** final loadout, purchases, ability-upgrade order, and neutral-item history.

Each player build is associated by `player_slot` and contains:

| Subsection | Target fields and source |
|---|---|
| `final_loadout` | `inventory` has six slots from `item_0` through `item_5`; `backpack` has three slots from `backpack_0` through `backpack_2`. Each slot is an integer item ID or `null`; preserve explicit zero values and positions. Retain `item_neutral` and `item_neutral2` as nullable source item IDs without assigning unverified meanings. Retain `aghanims_scepter`, `aghanims_shard`, and `moonshard` as nullable numeric final-state source values, without interpreting their values as equipment timing or converting them to booleans. |
| `purchase_events` | Ordered `purchase_log` records with `time_seconds` (number or `null`), `item_key` (string or `null`), and optional `charges` (number or `null`). |
| `ability_upgrade_sequence` | Source `ability_upgrades_arr`: integer Valve ability IDs in source upgrade order. Retain talent entries supplied by the source. |
| `neutral_item_history` | Source `neutral_item_history` records: `time_seconds` (number or `null`) from `time`, `item_key` (string or `null`) from `item_neutral`, and `enhancement_key` (string or `null`) from `item_neutral_enhancement`. Retain source order and partial records. The action represented by a record remains unverified. |

Keep component purchases, intermediate items, and completed purchases as separate source records. Do not infer a missing completed item, create purchase parent/child links, sum purchase prices as total spend, reconstruct minute inventories, or claim that a purchase means delivery or usability. Ability sequence order carries no inferred time or hero level. Do not call neutral-item history “item switching” until that meaning is verified. Permanent buffs are excluded from the first version. The exact meaning and final names of the two neutral slots remain pending; do not describe them as two confirmed equipped items.

### 6. `events`

**Responsibility:** the first-version event categories below, retaining precise source time and source attribution.

| Category | Source boundary |
|---|---|
| `hero_deaths` | Organize one event from each validated death record. Do not count the corresponding kill log as a second death. |
| `buybacks` | Source buyback records; do not duplicate purchases from `builds`. |
| `building_destructions` | Verified building-destruction objective records. |
| `roshan_kills` | Verified Roshan-kill objective records. |
| `aegis_pickups` | Verified Aegis-pickup objective records. |
| `first_blood` | Preserve the available first-blood source records and any disagreement. |
| `other_objectives` | Preserve other recognized objective source records, including unknown source codes without guessing their meaning. |

Use exact source event time in seconds, including negative values. Retain each category's source order; the separate category arrays do not imply a global event order. Equal-time records have no inferred ordering. Fill a killer hero ID only when its source unit maps exactly to a Valve hero; otherwise retain the source unit key and leave the hero ID unknown. Do not assign an event to a player or side from an unverified `team` or `killer` encoding.

For every event category, preserve an explicit empty source list as `[]` and represent a missing source list as `null`. Each `hero_deaths` record is built from one player's `deaths_log` entry:

| Target field | Type | Source and rule |
|---|---|---|
| `time_seconds` | number or `null` | `deaths_log[].time` |
| `victim_player_slot` | integer or `null` | The owning player's `player_slot` |
| `killer_player_slot` | integer or `null` | Fill only when source evidence explicitly identifies the corresponding player; otherwise `null` |
| `killer_unit_key` | string or `null` | `deaths_log[].key` |
| `killer_hero_id` | integer or `null` | Exact Valve internal-name mapping of the killer unit; otherwise `null` |
| `gold_lost` | number or `null` | `deaths_log[].gold_lost` |
| `gold_fed` | number or `null` | `deaths_log[].gold_fed` |
| `time_dead_seconds` | number or `null` | `deaths_log[].time_dead` |

Do not infer a killer player from similar names or nearby event times. Missing optional death fields remain `null` and do not require individual coverage warnings. Other event-row fields stay source-specific; their exact names and types must be verified before they are added.

Conflicting first-blood sources remain separate values in `coverage.conflicts`; do not adjudicate them. Preserve end-of-game timestamps even when they exceed `duration_seconds` by one second. The data contract does not add an anomaly warning or a frontend endpoint-display rule. Eye wards, runes, and pauses are outside the first-version event categories. `MINIBOSS_KILL` and unverified objective actor/team fields remain untranslated until their source semantics are confirmed.

The projector classifies only exact observed source codes: `building_kill`, `CHAT_MESSAGE_ROSHAN_KILL`, `CHAT_MESSAGE_AEGIS`, and `CHAT_MESSAGE_FIRSTBLOOD`. Other codes, including `CHAT_MESSAGE_MINIBOSS_KILL`, remain in `other_objectives` without a guessed label. Additional implemented event fields are:

| Event data | Fields and direct source mappings |
|---|---|
| Buyback | `time_seconds` from `time`; `player_slot` from the owning player; `source_slot` and `source_player_slot` preserve log `slot` and `player_slot` independently. Conflicting owner/source slots are retained and reported. |
| Objectives | `time_seconds` from `time`; `source_type` from `type`; `source_key` from `key`; `source_unit_key` from `unit`; `source_slot`, `source_player_slot`, `source_victim_player_slot`, `source_team`, `source_killer`, and `source_value` from the corresponding source fields. Opaque fields retain scalar values (string, number, boolean, or `null`) without decoding their semantics. |
| Objective players | `player_slot` and `victim_player_slot` are populated only from explicit same-name source fields matching one unique player slot in this record. A bare `slot`, `team`, or `killer` never supplies a player identity. |
| First blood | Nullable `reported_time_seconds` from top-level `first_blood_time` and nullable `objective_events` containing the first-blood objective rows. Conflicts point to exact source `objectives[i].time`; neither view overwrites the other. |

Hero IDs use an optional injected exact internal-name-to-ID catalog index. A killer player slot additionally requires one unique source player with that hero ID and slot. Unknown catalog keys, repeated hero IDs, or repeated slots leave the player unknown. No fuzzy matching is used. Missing one player's event log adds a coverage gap while preserving other players' known events; all unavailable logs yield `null`, and explicitly empty logs yield `[]`. Each category retains source player/log order without claiming a global time order.

### 7. `interactions`

**Responsibility:** three per-player views of hero targets: `kills_by_target`, `damage_by_target`, and `healing_by_target`.

The structure is `interactions.players[]`; each player entry contains `player_slot` (integer or `null`) and the three target lists. Each target record contains `target_unit_key` (string), `target_hero_id` (integer or `null`), and `value` (number). Resolve `target_hero_id` only by an exact Valve catalog internal-name match. Keep the source unit key for a hero entry when it has no exact mapping. Do not use fuzzy name similarity or assign an unresolved target to a player.

The offline projector accepts an optional exact catalog index; without it source target keys and amounts remain available with null hero IDs. It never calls fuzzy search or a remote provider. A malformed hero amount makes only that target map unavailable and adds a coverage reason, preserving the player's other maps and final statistics.

| Target list | Direct source | Target scope |
|---|---|---|
| `kills_by_target` | `players[].killed` | Hero entries only; `value` is the source kill count |
| `damage_by_target` | `players[].damage` | Hero entries only; `value` is the source damage amount |
| `healing_by_target` | `players[].healing` | Hero entries only, including self-healing; `value` is the source healing amount |

Retain source map order when producing each list. For these source maps, hero entries use the `npc_dota_hero_` unit-key namespace; exclude creep, neutral, building, ward, and other non-hero entries. An unresolved hero unit key remains visible with a null hero ID. Do not aggregate nested `damage_targets`, expose ability/item breakdowns, or recompute last hits and denies from these maps. Final and minute last-hit/deny statistics already belong to `players`.

An absent source map is `null`; an explicitly empty source map is an empty list. Do not synthesize zeros for unobserved pairs. Do not add contribution ratings, assist inference, counter analysis, or deeper interaction tables. If an interaction count differs from another source view, preserve both and record a material conflict instead of rewriting either value.

### 8. `coverage`

**Responsibility:** compactly identify promised data that is missing and source facts that materially disagree.

The only fields are:

| Field | Type | Meaning |
|---|---|---|
| `missing` | list of `{path: string, reason: string}` | `path` identifies unavailable promised DTO data; `reason` briefly states the source gap, invalid input, or unalignable series that prevents providing it. |
| `conflicts` | list of `{paths: string[], values: (string \| number \| boolean \| null)[]}` | Source paths and observed scalar values correspond by index and preserve a material disagreement without selecting the correct value. |

For example, missing kill logs may produce `{"path": "players[1].minute_timeline.kills", "reason": "Source kill log unavailable"}`. Existing arrays whose time axes cannot be aligned can likewise explain an unavailable DTO path; `missing` is not limited to absent source keys. A first-blood conflict can retain `{"paths": ["first_blood_time", "objectives.first_blood.time"], "values": [0, -25]}`. These source-path labels describe evidence; they do not expose a raw-response retrieval route.

Do not list features this version never promises. Do not warn for every optional event attribute. Do not add confidence or quality scores or long diagnostic prose. Missing data in a non-core section does not erase other usable sections. Invalid game identity or another root contract failure returns an error, never a successful DTO.

Conflict paths and values must have corresponding lengths and identify at least two source observations. The projector uses exact source array indices where available. Missing optional event attributes do not generate per-event warnings; missing logs or event times that affect a promised view do.

## Illustrative sample fragments

The values below were checked against one saved OpenDota response for game `9040460429`. They demonstrate mappings and source limits; they are not a guarantee that every game has these fields.

The source start time converts to the Beijing calendar date shown. The formal duration is 2,904 seconds; `radiant_win=false` maps to a Dire win. The source score is 17–33.

    match = {
      "match_date": "2026-10-12",
      "duration_seconds": 2904,
      "game_winner": "dire",
      "score": {"radiant": 17, "dire": 33}
    }

The first source pick/ban row is a ban by source team code 0:

    {"order": 0, "action": "ban", "hero_id": 59, "side": "radiant"}

For the player with account ID `321580662`, the source player slot is 1 and the hero ID is 1. At game time 600 seconds the saved arrays contain net worth 3,440, cumulative gold 2,930, experience 2,383, 39 last hits, and 2 denies. The source logs give one kill and zero deaths through that time:

    {
      "time_seconds": 600,
      "net_worth": 3440,
      "earned_gold": 2930,
      "experience": 2383,
      "last_hits": 39,
      "denies": 2,
      "kills": 1,
      "deaths": 0
    }

The same saved player's final values include K/D/A 3/6/4, level 25, 605 last hits, 3 denies, and net worth 26,064. Source hero damage is 14,456, tower damage 686, and hero healing 0. These demonstrate the confirmed `final_stats` fields; they do not approve the additional candidates listed above.

The source purchase log includes component keys `faerie_fire` and `slippers` at -89 seconds, `power_treads` at 388 seconds, and `manta` at 1,478 seconds. They remain separate records; the example does not assert a recipe relationship.

A saved death record for this player is at 815 seconds and carries the source killer unit key `npc_dota_hero_pangolier`. The interaction map records one kill against `npc_dota_hero_monkey_king`; the exact local Valve catalog maps that unit key to hero ID 114.

The source `first_blood_time` is 0, while an objective record is marked `CHAT_MESSAGE_FIRSTBLOOD` at -25 seconds. Keep both source values and report the conflict. Do not select one as the correct time.

This contract does not promise a DTO byte-size target. The old 105 KB and 215 KB experimental DTOs contain fields excluded or still unapproved here; they are not templates for the final schema.

## Pending verification and implementation prerequisites

| Kind | Item |
|---|---|
| Source semantics | The meanings of the two neutral-item slots and the action represented by neutral-item history; unverified objective codes, actor/team encodings including `MINIBOSS_KILL`, and any category-specific time semantics not already mapped above |
| Additional field decisions | Only the additional `final_stats` candidates listed above, competition fields, and team fields beyond `source_team_id` and `name`; the confirmed minimum is not pending approval |
| Implemented internal record split to preserve | The resolver consumes complete `OpenDotaGameRecord` values independently of the public `GameDetailResult` constructed by `GameDetailService`. Keep exact source timestamps, side-specific team IDs, identity-validation inputs, and accepted per-game associations available internally when adding the DTO projection. |
| Log boundary | Verify that missing and explicitly empty event logs remain distinct, and that cumulative kills/deaths include valid pre-zero records without inventing a zero curve when logs are missing |
| Implemented resolver boundary to preserve | `esports.game.resolve` retains complete reads internally and publishes only the resolution evidence owned by the cross-source contract in `DATA.md`. Its Artifact cannot retrieve candidate detail bodies or full source collections. Preserve this separation when changing the still-raw `game.detail` output. |
| Non-blocking separation | Static names and images remain separate catalog/display facts; they do not complete missing historical match facts. |

Keep these statuses separate: the confirmed field structures and mappings above are settled; additional candidate inclusion and unknown source semantics remain open; the internal record split and resolver public-evidence boundary are implemented and must be preserved; DTO log handling and alignment remain implementation/validation work. Do not reopen settled fields or turn unresolved semantics into default values.

## Ownership and acceptance

The data boundary and migration notes live in [`../DATA.md`](../DATA.md). Tool behavior is summarized in [`../TOOLS.md`](../TOOLS.md), layer ownership in [`../ARCHITECTURE.md`](../ARCHITECTURE.md), deterministic acceptance in [`../EVALS.md`](../EVALS.md), and implementation order in [`../ROADMAP.md`](../ROADMAP.md).

Passing those future checks would establish the documented projection and its failure behavior. It would not establish frontend behavior, live OpenDota availability, or analytical conclusions outside this contract.
