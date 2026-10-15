# Game Detail Data Contract

## Status, purpose, and boundaries

This document is the sole detailed data contract for `game.detail`.

- **Current implementation:** `game.detail` returns the governed eight-section DTO with bilingual entity/unit objects, normalized event types, scalar coverage evidence, and one Catalog/unit-mapping version per result.
- **Accepted target:** `data` is an explicit eight-section DotaMind DTO containing source facts, necessary deterministic transformations, and locally resolved English/Chinese entity names.
- **Implementation status:** local unit lookup, entity enrichment, event conversion, the public Service switch, and generic tool/Artifact reads are implemented and verified with deterministic tests. Live provider availability and real-model behavior remain separate acceptance work.
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
| `catalog_version` | object | The existing local entity-name resolver's snapshot metadata: `source`, `patch`, `generated_at`, and `schema_version`; one pinned snapshot per detail operation |
| `unit_mapping_version` | string | Version of the validated, independently maintained unit mapping used for this result; not a game patch or a request timestamp |
| `data` | `GameDetailData` | The eight governed sections below |

The eight sections in `data` are `match`, `draft`, `players`, `economy`, `builds`, `events`, `interactions`, and `coverage`. Each section appears once. Section fields use `null` for missing or unknown source facts; source-declared empty collections remain empty collections. Catalog and unit-mapping versions occur once in the outer result, not on every entity or timeline node. These versions attribute static labels and mapping rules; they do not claim historical match-patch mechanics.

OpenDota `match_id` must be a positive integer equal to the requested `valve_game_id` before a successful result can be returned. The source identity check remains at the provider boundary. The DTO does not repeat `provider`, `retrieved_at`, or `valve_game_id` inside `data.match`.

The result and its Artifact contain the complete governed DTO. They contain no `raw` field and expose no model-facing handle that retrieves the original OpenDota object. Generic Artifact read and grep continue to read the stored DTO without provider-specific behavior.

The internal/public type split is implemented: the OpenDota adapter returns `OpenDotaGameRecord` with native `match_id`, provider, retrieval time, and complete source data. The resolver consumes that record directly. `GameDetailService` separately constructs the public `GameDetailResult` by projecting that record with pinned local label resources. The eight-section projection belongs at this Service boundary. Internal records are not public retrieval handles, and future DTO conversion must leave the resolver's source values intact.

## Global data rules

| Situation | Contract |
|---|---|
| Source field is missing, null, or explicitly unknown | Emit `null`; do not substitute zero |
| Source explicitly provides an empty array or object | Preserve `[]` or `{}` |
| Source explicitly provides `0` or `false` | Preserve the value except for the documented empty item-slot mapping below |
| Field rename or enum mapping | Record the source path and exact mapping below; leave unrecognized values unknown |
| Deterministic accumulation | State the formula, input facts, ordering, and missing-input behavior |
| Source facts disagree | Preserve the values and record a material conflict; do not select a winner |
| Time values | Keep calendar date, exact match seconds, minute samples, and final statistics distinct |
| Static names | Add English/Chinese names at explicit entity fields before public output, with separate catalog/mapping provenance; do not infer historical mechanics |
| Images and presentation | Outside this data change; do not add image fetching or a new display-reference contract |
| Semantics not verified | Mark them pending; do not assign a business meaning |

Counts, ordering, and field mappings are data transformations, not performance judgments. Each still needs a reproducible rule.

## Entity names, units, and exact mapping

The Service coordinates source projection and local enrichment before public output validation and generic Artifact handling. It uses one captured entity Catalog and one captured unit mapping for the whole result. It reuses the code-internal `EntityNameResolver` for explicit hero/item/ability IDs. OpenDota field extraction and exact internal-key conversion remain source-boundary responsibilities; the shared resolver does not scan arbitrary JSON, invoke `catalog.lookup`, make network requests, or perform fuzzy matching. The resolver's complete internal source record is unchanged.

### Hero, item, and ability objects

At explicitly typed `hero`, `item`, or `ability` fields, use a closed object with `id` (integer), `name_zh` (string or `null`), and `name_en` (string or `null`). The containing field establishes the ID namespace. IDs remain canonical facts; names are static labels. Do not repeat a sibling `hero_id`/`item_id`/`ability_id` merely to duplicate the same identity.

- A source ID that has no Catalog entry remains in the entity object with null names and a mapping gap. A missing individual language remains `null`; never translate or substitute the other language.
- A source internal key is converted only by an exact internal-name index. Hero unit keys match the complete `npc_dota_hero_*` name. OpenDota item keys such as `manta` match the Catalog's complete `item_manta` internal name under that explicit prefix rule. No human-name alias or fuzzy similarity supplies an identity.
- If a key cannot be converted to an ID, the entity field is `null`; preserve the source scalar and exact source path only in `coverage.missing`. Successfully converted source keys do not remain duplicated in public business fields.
- A source item ID of zero denotes an empty loadout slot and becomes `null`; an unknown nonzero ID remains an entity with that ID and null names. This is an explicit slot mapping, not the global missing/zero rule. Missing source slots also become `null` but have a source-gap record, so they remain distinguishable from known empty slots.
- Entity labels occur at the owning player, draft, build, or event record. Minute nodes do not repeat hero labels.

For example, a purchase at 1,478 seconds can contain `"item": {"id": 147, "name_zh": "幻影斧", "name_en": "Manta Style"}`. Item ID 147 and both names are verified local Catalog values.

### Event unit objects

An event participant can be a hero, lane creep, tower, or another unit. Do not force every `npc_dota_*` key into a hero object. The closed `Unit` object contains:

| Field | Type | Rule |
|---|---|---|
| `kind` | fixed enum below or `null` | Exact verified unit mapping; unknown classification remains null |
| `name_zh`, `name_en` | string or `null` | Source-backed static bilingual unit names |
| `hero_id` | integer or `null` | Exact Valve hero ID for a hero unit only; do not invent IDs for other units |
| `side` | `radiant`, `dire`, or `null` | Verified explicit unit-side encoding or an unambiguous same-game association; never a generic unit definition's default team |
| `lane` | `top`, `mid`, `bot`, or `null` | Only a verified explicit lane in the unit mapping |
| `tier` | integer or `null` | Verified tower tier only; do not infer a summoned unit's level from a name suffix |

The first-version `kind` enum is `hero`, `lane_creep`, `siege_creep`, `neutral_creep`, `tower`, `barracks`, `ancient`, `building`, `fountain`, `courier`, `ward`, `roshan`, `tormentor`, `summoned_unit`, `spell_unit`, or `roshans_banner`. A mapped type can remain available when one localized name is missing. An entirely unmapped key or source `dota_unknown` produces a null unit and a field-specific coverage entry. Preserve other event facts.

Generic unit defaults do not establish a courier's side, a ward's owner, a dominated neutral's controlling side, or a summon controller. A unit key identifies a unit type rather than a physical instance; a shared tier-four tower key cannot identify the left or right tower. Human-readable names stay as verified labels; use `side`, `lane`, and `tier` for known distinctions rather than fabricating a localized compound name.

Non-hero mappings live in a separate versioned static resource exposed through Catalog's local query boundary. Hero/item/ability records keep their current Catalog ownership. This does not add a sixth file to the existing five-file Catalog publication protocol or introduce remote lookup on a detail request. Initial unit resources are explicitly maintained and validated; automated import, refresh cadence, and changes to Catalog publication are outside this migration.

The implemented code-internal `UnitCatalog` loads [`unit_mapping.json`](../../apps/api/app/data/units/unit_mapping.json) explicitly and offers exact `lookup(internal_name)` over 117 verified non-hero records. It returns an immutable record or `None` for an unmatched string; invalid query types raise `ValueError`, while missing/corrupt/unreadable resources propagate their errors. The snapshot keeps fixed source revisions and hashes. `version` is `sha256:` plus the hash of canonical validated snapshot JSON, independent of whitespace and request time; labels, attributes, or provenance changes produce a new version. One loaded instance retains its snapshot without reopening files during lookup. It is injected into `game.detail` composition and remains independent of the entity-Catalog publication protocol.

Verified samples, source revisions, observed unit categories, and the mapping review table are owned by [`../reference/opendota-unit-identifiers.md`](../reference/opendota-unit-identifiers.md). The sample is evidence for explicit mappings, not an exhaustive future-unit registry.

## Section contracts

Every section below states its responsibility, target fields and types, source, transformation, and missing-data behavior. First-version scope is closed below. Unverified source meanings remain explicit limitations rather than blockers requiring speculative defaults.

### 1. `match`

**Responsibility:** identify the recorded game context and its result.

| Target field | Type | Source and rule |
|---|---|---|
| `match_date` | `YYYY-MM-DD` string or `null` | Convert source `start_time` from Unix seconds using `Asia/Shanghai`. If unavailable or invalid, emit `null`. |
| `duration_seconds` | integer or `null` | Source `duration`, representing formal game duration. Do not add `pre_game_duration` or expose a second pre-game duration. |
| `game_winner` | `"radiant"`, `"dire"`, or `null` | Strict mapping: `radiant_win=true` gives `radiant`; `false` gives `dire`; absent or unknown gives `null`. |
| `score` | object or `null` | Preserve source `radiant_score` and `dire_score` under those side keys. |
| `competition` | `null` | Deliberately unpopulated in this version. A future PandaScore-context decision may define it separately; do not copy an OpenDota League body, mix ID namespaces, or report this scope exclusion as a per-game source gap. |
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
| `hero` | entity object or `null` | Source `hero_id` plus exact local Catalog English/Chinese names |
| `side` | `"radiant"`, `"dire"`, or `null` | Within `picks_bans` only, source `team=0` maps to `radiant` and `team=1` maps to `dire`; other values remain `null` |

This `team` mapping is local to the pick/ban array. It does not define the meaning of `team` in objectives or other event records. Do not infer draft phase, action time, or timing from `timings`.

### 3. `players`

**Responsibility:** preserve per-player identity, final statistics, and source-aligned minute observations.

Each player has three parts: `identity`, `final_stats`, and `minute_timeline`. Keep player records in source array order.

`identity` contains `account_id` and `player_slot` as nullable source IDs, a nullable `hero` entity object from source `hero_id`, plus source-provided `name` and `personaname` as nullable strings. It also contains `side` (`"radiant"`, `"dire"`, or `null`): strictly map `players[].isRadiant=true` to `radiant` and `false` to `dire`; missing or unknown values remain `null`. `account_id` is the cross-game account identifier when supplied. `player_slot` associates rows within this game; it is not a position from one to five. Names are labels, never identity proof. `hero_variant` is outside the core contract; do not interpret zero as a particular facet.

`final_stats` contains these confirmed final scoreboard, farming/economy, and combat statistics. Every source path is relative to that player's OpenDota record:

| Target fields | Type of each field | Source |
|---|---|---|
| `kills`, `deaths`, `assists` | integer or `null` | Same-name source fields |
| `level` | integer or `null` | `level` |
| `last_hits`, `denies` | integer or `null` | Same-name source fields |
| `net_worth` | number or `null` | `net_worth` |
| `hero_damage`, `tower_damage`, `hero_healing` | number or `null` | Same-name source fields |

These are final values, not values copied from the last minute sample. Assists and level have final values only; hero damage, tower damage, and hero healing also stay here rather than entering the first-version minute timeline. Missing source values are `null`; explicit zeros remain zero.

This version contains exactly the ten final-stat fields above. Wallet/spend/rate fields, `stuns`, ward/resource counts, unit-category kill counts, `buyback_count`, `actions_per_min`, `pings`, `life_state_dead`, and `leaver_status` are excluded, not unresolved first-version decisions. A later concrete consumer may justify an extension. A source wallet value must never be replaced by cumulative `gold_t`.

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
| `final_loadout` | `inventory` has six slots from `item_0` through `item_5`; `backpack` has three slots from `backpack_0` through `backpack_2`. Each position contains an item entity or `null`; preserve positions and apply the explicit zero/unknown slot rules above. `item_neutral` and `item_neutral2` likewise contain nullable item entities without assigning unverified meanings to the two source slots. Retain `aghanims_scepter`, `aghanims_shard`, and `moonshard` as nullable numeric final-state source values, without interpreting them as equipment timing or converting them to booleans. |
| `purchase_events` | Ordered `purchase_log` records with `time_seconds` (number or `null`), `item` (entity object or `null`) from exact conversion of source `key`, and optional `charges` (number or `null`). |
| `ability_upgrade_sequence` | Ability entity objects from `ability_upgrades_arr`, in exact source upgrade order with repeats and talent entries retained. Unknown source IDs remain present with null names. |
| `neutral_item_history` | Source records with `time_seconds` from `time`, `item` from exact conversion of `item_neutral`, and `enhancement` from exact conversion of `item_neutral_enhancement`; each entity is nullable. Retain source order and partial records. The action represented by a record remains unverified. |

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
| `other_objectives` | Preserve courier/Tormentor events and other objective records; unknown codes use a null type with scalar evidence in coverage. |

Use exact source event time in seconds, including negative values. Retain each category's source order; the separate category arrays do not imply a global event order. Equal-time records have no inferred ordering. Resolve event units explicitly using the local hero and non-hero mapping. Unknown units become field-specific coverage gaps rather than raw keys in business records. Do not assign an event to a player or side from an unverified `team` or `killer` encoding.

For every event category, preserve an explicit empty source list as `[]` and represent a missing source list as `null`. Each `hero_deaths` record is built from one player's `deaths_log` entry:

| Target field | Type | Source and rule |
|---|---|---|
| `time_seconds` | number or `null` | `deaths_log[].time` |
| `victim_player_slot` | integer or `null` | The owning player's `player_slot` |
| `killer_player_slot` | integer or `null` | Fill only when source evidence explicitly identifies the corresponding player; otherwise `null` |
| `killer_unit` | unit object or `null` | Exact conversion of `deaths_log[].key`; distinguishes heroes, towers, creeps, and other verified units |
| `gold_lost` | number or `null` | `deaths_log[].gold_lost` |
| `gold_fed` | number or `null` | `deaths_log[].gold_fed` |
| `time_dead_seconds` | number or `null` | `deaths_log[].time_dead` |

Do not infer a killer player from similar names or nearby event times. Missing optional death fields remain `null` and do not require individual coverage warnings. Other event-row fields stay source-specific; their exact names and types must be verified before they are added.

Conflicting first-blood sources remain separate values in `coverage.conflicts`; do not adjudicate them. Preserve end-of-game timestamps even when they exceed `duration_seconds` by one second. The data contract does not add an anomaly warning or a frontend endpoint-display rule. Eye wards, runes, and pauses are outside the first-version event categories. Mapping unit names does not add ward events or non-hero interaction tables.

The projector uses the following exact business `type` mapping and resolves bilingual event units before public output:

| Source `objectives[].type` | Business `type` | Category |
|---|---|---|
| `building_kill` | `building_destruction` | `building_destructions` |
| `CHAT_MESSAGE_ROSHAN_KILL` | `roshan_kill` | `roshan_kills` |
| `CHAT_MESSAGE_AEGIS` | `aegis_pickup` | `aegis_pickups` |
| `CHAT_MESSAGE_FIRSTBLOOD` | `first_blood` | `first_blood.objective_events` |
| `CHAT_MESSAGE_COURIER_LOST` | `courier_death` | `other_objectives` |
| `CHAT_MESSAGE_MINIBOSS_KILL` | `tormentor_kill` | `other_objectives` |
| Unrecognized or missing type | `null` | `other_objectives`; keep the event's known time and other facts, with the present unmapped code in coverage |

Normalized objective types are the six fixed strings above or `null`. No free-form model classification is used. Event type normalization is separate from unit-name lookup. The unit `npc_dota_miniboss` has verified client names 痛苦魔方 / Tormentor; the corresponding objective type is now an accepted mapping, not an unresolved first-version category.

Additional target event fields are:

| Event data | Fields and direct source mappings |
|---|---|
| Buyback | `time_seconds` from `time`; `player_slot` from the owning player. A disagreeing explicit source `player_slot` remains evidence in `coverage.conflicts`. Unverified present `slot` codes are retained only as field-specific coverage evidence, not decoded into a player. |
| Objectives | `time_seconds` from `time`; normalized `type` from the table above; `target_unit` from `key` only when it is an exact mapped unit identifier; `actor_unit` from exact unit conversion of `unit`. Do not copy `source_type`, `source_key`, or `source_unit_key` into business fields. |
| Other source codes | Present unverified `slot`, `team`, `killer`, `value`, or non-unit `key` values remain scalar evidence in coverage with exact source paths. They do not become business identities or inferred rewards. Missing optional values require no warning. |
| Objective players | `player_slot` and `victim_player_slot` are populated only from explicit same-name source fields matching one unique player slot in this record. A bare `slot`, `team`, or `killer` never supplies a player identity. |
| First blood | Nullable `reported_time_seconds` from top-level `first_blood_time` and nullable `objective_events` containing the first-blood objective rows. Conflicts point to exact source `objectives[i].time`; neither view overwrites the other. |

The Service supplies one pinned local entity resolver and unit resource to the projector. A killer player slot additionally requires one unique source player with that hero ID and slot. Unknown catalog keys, repeated hero IDs, or repeated slots leave the player unknown. A recognized summon type does not identify its controller. No fuzzy matching is used. Missing one player's event log adds a coverage gap while preserving other players' known events; all unavailable logs yield `null`, and explicitly empty logs yield `[]`. Each category retains source player/log order without claiming a global time order.

### 7. `interactions`

**Responsibility:** three per-player views of hero targets: `kills_by_target`, `damage_by_target`, and `healing_by_target`.

The structure is `interactions.players[]`; each player entry contains `player_slot` (integer or `null`) and the three target lists. Each target record contains `target_hero` (hero entity object or `null`) and `value` (number). Resolve it only by an exact Valve catalog internal-name match. An unconvertible hero key leaves the entity null and retains that key in coverage; the known numeric amount and row remain. Do not expose `target_unit_key`, use fuzzy name similarity, or assign an unresolved target to a player.

The projector uses local bilingual entity objects as specified above, without remote lookups. A malformed hero amount makes only that target map unavailable and adds a coverage reason, preserving the player's other maps and final statistics.

| Target list | Direct source | Target scope |
|---|---|---|
| `kills_by_target` | `players[].killed` | Hero entries only; `value` is the source kill count |
| `damage_by_target` | `players[].damage` | Hero entries only; `value` is the source damage amount |
| `healing_by_target` | `players[].healing` | Hero entries only, including self-healing; `value` is the source healing amount |

Retain source map order when producing each list. For these source maps, hero entries use the `npc_dota_hero_` unit-key namespace; exclude creep, neutral, building, ward, and other non-hero entries. An unresolved hero row remains with a null `target_hero` and field-specific coverage evidence. Non-hero unit mapping does not expand this hero-only scope. Do not aggregate nested `damage_targets`, expose ability/item breakdowns, or recompute last hits and denies from these maps. Final and minute last-hit/deny statistics already belong to `players`.

An absent source map is `null`; an explicitly empty source map is an empty list. Do not synthesize zeros for unobserved pairs. Do not add contribution ratings, assist inference, counter analysis, or deeper interaction tables. If an interaction count differs from another source view, preserve both and record a material conflict instead of rewriting either value.

### 8. `coverage`

**Responsibility:** compactly identify promised data that is missing, retain source scalars that cannot be reliably converted, and preserve material source disagreements.

The only fields are:

| Field | Type | Meaning |
|---|---|---|
| `missing` | list of `{path: string, reason: string, source_path?: string, source_value?: scalar}` | `path` identifies the affected DTO field or containing record; `reason` states the source gap or failed conversion. For a present unmapped ID, key, code, or unavailable localized name, include its exact `source_path` and original scalar `source_value`. Do not copy source objects or arrays. |
| `conflicts` | list of `{paths: string[], values: (string \| number \| boolean \| null)[]}` | Source paths and observed scalar values correspond by index and preserve a material disagreement without selecting the correct value. |

A scalar is a string, finite number, boolean, or null. Optional source-evidence fields are omitted when there is no corresponding present source value; do not fabricate a source value for an absent key.

For example, missing kill logs may produce `{"path": "players[1].minute_timeline.kills", "reason": "Source kill log unavailable"}`. Existing arrays whose time axes cannot be aligned can likewise explain an unavailable DTO path; `missing` is not limited to absent source keys. The saved sample's first-blood conflict can retain `{"paths": ["first_blood_time", "objectives[0].time"], "values": [0, -25]}`. These source-path labels describe evidence; they do not expose a raw-response retrieval route.

For example, an unmapped neutral item can produce `{"path":"builds.players[6].neutral_item_history[1].item","reason":"Catalog key not found","source_path":"players[6].neutral_item_history[1].item_neutral","source_value":"guardian_shell"}`. Source and DTO indices must come from the actual row; this illustrates the shape, not a claim about that sample's exact indices. An unknown building-event actor sets only `actor_unit=null`, leaving its target building and time intact.

Do not list features this version never promises, such as competition fields or extra final stats. Do not warn for every absent optional event attribute. Present source encodings that cannot be interpreted use the scalar mapping-gap rule; successfully converted keys are not copied again. Deduplicate identical gap entries without losing their affected paths. Do not add confidence or quality scores, long diagnostic prose, raw objects, or a raw-response retrieval handle. Missing data in a non-core section does not erase other usable sections. Invalid game identity or another root contract failure returns an error, never a successful DTO. Unexpected resolver/storage/programming failures are not silently converted into per-key misses.

Conflict paths and values must have corresponding lengths and identify at least two source observations. The projector uses exact source array indices where available. Missing optional event attributes do not generate per-event warnings; missing logs or event times that affect a promised view do.

## Illustrative sample fragments

The match values below were checked against one saved OpenDota response for game `9040460429`. Bilingual labels come from the local catalog rather than the match response. These fragments illustrate the implemented contract; they do not guarantee that every game has these fields.

The source start time converts to the Beijing calendar date shown. The formal duration is 2,904 seconds; `radiant_win=false` maps to a Dire win. The source score is 17–33.

    match = {
      "match_date": "2026-10-12",
      "duration_seconds": 2904,
      "game_winner": "dire",
      "score": {"radiant": 17, "dire": 33}
    }

The first source pick/ban row is a ban by source team code 0:

    {"order": 0, "action": "ban", "hero": {"id": 59, "name_zh": "哈斯卡", "name_en": "Huskar"}, "side": "radiant"}

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

The same saved player's final values include K/D/A 3/6/4, level 25, 605 last hits, 3 denies, and net worth 26,064. Source hero damage is 14,456, tower damage 686, and hero healing 0. These demonstrate all ten approved `final_stats` fields; additional statistics are outside this version.

The source purchase log includes component keys `faerie_fire` and `slippers` at -89 seconds, `power_treads` at 388 seconds, and `manta` at 1,478 seconds. Convert each key into its own bilingual item entity while preserving those separate records; do not assert a recipe relationship. The last becomes `{"time_seconds":1478,"item":{"id":147,"name_zh":"幻影斧","name_en":"Manta Style"},"charges":null}`.

A saved death record for this player is at 815 seconds and carries source `npc_dota_hero_pangolier`, which supplies the bilingual hero `killer_unit`. The interaction map records one kill against `npc_dota_hero_monkey_king`; its target becomes `{"id":114,"name_zh":"齐天大圣","name_en":"Monkey King"}`. Source keys are conversion inputs, not duplicated public fields.

The source `first_blood_time` is 0, while an objective record is marked `CHAT_MESSAGE_FIRSTBLOOD` at -25 seconds. Keep both source values and report the conflict. Do not select one as the correct time.

This contract does not promise a DTO byte-size target. The old 105 KB and 215 KB experimental DTOs contain fields excluded or still unapproved here; they are not templates for the final schema.

## Closed scope, verification limits, and implementation prerequisites

| Kind | Item |
|---|---|
| Deliberate scope exclusions | `competition=null`, exactly ten final-stat fields, and only `source_team_id`/`name` for teams are settled for this version. Future extensions do not block implementation. |
| Source-semantic limits | The meanings of the two neutral-item slots and actions in neutral-item history remain unverified. Unverified actor/team/reward encodings are retained only as scalar coverage evidence. The six objective types above, including Tormentor, are accepted mappings; new codes require verification. |
| Mapping gaps | `dota_unknown` is explicit source uncertainty. Sampled `guardian_shell` has no exact record in the checked local Catalog; keep that field unknown with scalar evidence until a verified mapping is added. Neither blocks other match facts. |
| Implemented enrichment | Bilingual entity/unit objects, event conversion, snapshot provenance, and scalar mapping-gap fields are implemented and tested together with public tool/Artifact output. Unknown names/keys remain explicit. |
| Implemented internal record split to preserve | The resolver consumes complete `OpenDotaGameRecord` values independently of the public `GameDetailResult` constructed by `GameDetailService`. Keep exact source timestamps, side-specific team IDs, identity-validation inputs, and accepted per-game associations available internally when adding the DTO projection. |
| Log boundary | Verify that missing and explicitly empty event logs remain distinct, and that cumulative kills/deaths include valid pre-zero records without inventing a zero curve when logs are missing |
| Implemented resolver boundary to preserve | `esports.game.resolve` retains complete reads internally and publishes only the resolution evidence owned by the cross-source contract in `DATA.md`. Its Artifact cannot retrieve candidate detail bodies or full source collections. Preserve this separation when extending the governed `game.detail` DTO. |
| Non-blocking separation | Static names are locally materialized with their own provenance. They do not complete missing historical match facts. Images, frontend behavior, automated unit-data refresh, and deployment remain outside this change. |

The first-version data scope and naming policy are settled. Source-semantic limits and newly encountered keys are handled by explicit unknown values and coverage, not speculative defaults or another field-approval round. Preserve the implemented internal record split and resolver public-evidence boundary. Local enrichment and the public switch have deterministic tool/Artifact acceptance. Live-provider and real-model behavior remain unverified.

## Ownership and acceptance

The data boundary and migration notes live in [`../DATA.md`](../DATA.md). Tool behavior is summarized in [`../TOOLS.md`](../TOOLS.md), layer ownership in [`../ARCHITECTURE.md`](../ARCHITECTURE.md), deterministic acceptance in [`../EVALS.md`](../EVALS.md), and implementation order in [`../ROADMAP.md`](../ROADMAP.md).

Deterministic checks establish the documented projection and its tested failure behavior. They do not establish frontend behavior, live OpenDota availability, or analytical conclusions outside this contract.
