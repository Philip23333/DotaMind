# Game Detail Data Contract

## Status, purpose, and boundaries

This document is the sole detailed data contract for `game.detail`.

- **Public contract:** `game.detail` exposes only the six-module `report` with bilingual labels, time labels, normalized facts, source-specific coverage, and pinned label versions. The eight-section `GameDetailData` is internal projection input, never a public result member, Artifact body or alternate retrieval route.
- **Accepted target / implementation:** the eight-section DTO, bilingual labels, STRATZ-first/fixed-OpenDota boundary and program-built report are implemented. The [report contract](game_detail_report.md) owns report views and the separate image-only heatmap capability. Heatmap infrastructure is implemented; verified production map assets/calibration remain unavailable for the sampled version, so it does not publish substitute images.
- **Verification scope:** three live games verify the governed detail/report path; unverified STRATZ minute arrays, precise terminal income and historical encodings retain explicit limits. Deterministic, live-source and real-model checks are separated in [EVALS](../EVALS.md).
- **Use:** minute-by-minute state review and final-game statistics.
- **Outside this contract:** performance ratings, role inference, lane-win judgments, teamfight classification, review recommendations, counterfactuals, simulated inventory states, and continuous map replay.

This describes data and tool behavior. It does not define a frontend page or visual layout. Tables labelled implemented describe the current schema, not exclusions from the newly accepted report target below.

### Report-driven extensions (implemented)

The report contract owns the default minute/final/interaction/event views and
heatmap lifecycle; this document remains the field/type/source owner for the
eight-section DTO. Its extensions include:

- Final `cumulative_gold_earned = floor(goldPerMinute * durationSeconds / 60)`
  from STRATZ, with formula/input provenance, plus explicit final
  `gold_per_minute` and `experience_per_minute`. Missing inputs yield null.
  This is the same derived convention verified in OpenDota, not an exact
  end-frame earned-income measurement; it does not qualify the existing final
  `earned_gold_net_worth_gap` gate. No minute net worth returns.
- Explicit timed level, permanent-upgrade, ability/talent and support facts for
  report construction; keep inventories/purchases/upgrade events owned by builds
  rather than duplicating full lists inside minute nodes. Default reports show
  level in place of raw XP; the existing XP facts remain available for queries.
  Minute assists stay unknown until complete attribution is established.
- Source-backed received-hero-damage facts and same-game target identities for
  the interaction matrix; unreported pairs remain null. Keep the matrix and
  final `heroDamage` in their independently attributed scopes.
- Final death-gold-loss aggregation from uniquely linked normalized deaths.
  A missing death or amount prevents a complete total; a known subtotal can
  remain explicitly partial. It is distinct from the earned-income/net-worth gap.
- Prefer the now-verified STRATZ per-bucket kill sums for team score, explicit
  buff events for consumed Scepter/Shard/Moon Shard, and validated zero-based
  ability ranks. Do not infer held Scepter from consumed status. Unknown ability
  IDs and unverified mappings stay unknown. OpenDota continues supplying minute
  earned income, initially farming/XP, neutral enhancement, missing ward groups,
  and whole Roshan/Aegis/building categories. No model-operated fallback.

The source evidence is [the revalidated reference](../reference/stratz-game-detail.md).
The internal governed mappings are described below. Public organization and paths
are owned by [the report contract](game_detail_report.md); internal DTO paths in
this document describe projection inputs, not model-facing retrieval paths.
Heatmaps have a separately accepted transient-position exception: only images
and a small index persist, never source coordinates in the DTO or Artifact.

## Input, envelope, and identity

The model-facing input remains:

    game.detail(valve_game_id)

The public result has one provenance envelope:

| Field | Type | Meaning |
|---|---|---|
| `valve_game_id` | positive integer | Requested canonical Valve single-game identity |
| `provider` | `"stratz"` | Primary source; does not attribute every nested fact to STRATZ |
| `retrieved_at` | timezone-aware timestamp | Retrieval time of the primary validated record |
| `sources` | provider-keyed object | Each successful read has its own `retrieved_at`; keys are `stratz` and, when read successfully, `opendota`. Coverage and event provenance refer to these keys. No credentials, raw bodies, or retrieval handles. |
| `catalog_version` | object | The existing local entity-name resolver's snapshot metadata: `source`, `patch`, `generated_at`, and `schema_version`; one pinned snapshot per detail operation |
| `unit_mapping_version` | string | Version of the validated, independently maintained unit mapping used for this result; not a game patch or a request timestamp |
| `report` | required `GameReport` | The sole public game-fact structure: six modules, precise histories, coverage and limitations. Exact fields are owned by [the report contract](game_detail_report.md). No `data`, raw source body or internal DTO handle. |

The eight internal DTO sections are `match`, `draft`, `players`, `economy`, `builds`, `events`, `interactions`, and `coverage`. They are consumed by report construction inside the capability. Fields use `null` for missing or unknown source facts; source-declared empty collections remain empty collections. Catalog and unit-mapping versions occur once in the outer public result, not on every entity or timeline node. These versions attribute static labels and mapping rules; they do not claim historical match-patch mechanics.

STRATZ `match.id` and each supplemental OpenDota `match_id` must independently
equal the requested positive `valve_game_id` before their facts can enter the DTO.
Do not join players by array position: validate same-game account/slot/hero facts,
and leave an ambiguous association unavailable. The DTO does not repeat outer
identity metadata inside `data.match`.

The result and its single Artifact contain the complete public report only.
They contain neither the internal DTO nor a `raw` field or a handle retrieving
either. Generic Artifact read, grep and query operate on the stored report without
provider-specific behavior. Precise histories move to the corresponding report
module; coverage has one public copy and its affected-field paths target report.

The OpenDota adapter retains complete `OpenDotaGameRecord` values for the identity
resolver and supplemental projection. The STRATZ adapter independently validates
`StratzGameRecord`. `GameDetailService` constructs the public result from the
primary record and selected supplemental groups, pinning label resources first.
Internal records are not public retrieval handles; the resolver still receives
its unchanged OpenDota source values.

The resolver may return a selected Valve ID with `selection_basis="unique_candidate"`
and identity warnings. Those warnings do not prohibit this detail lookup; they
describe uncertainty about the esports association, not the identity of the
requested Valve record. `game.detail` still validates the source ID exactly and
does not re-query PandaScore, repeat cross-source matching, invent a team-to-side
association, or copy resolution warnings into source match facts. The model keeps
material association uncertainty from the separate resolution result.

## Source policy and capability ownership (implemented)

`GameDetailService` owns a fixed source plan below the existing capability seam:

```text
game.detail(valve_game_id)
  → validated STRATZ record + one reusable OpenDota supplemental record
  → source-specific extraction and verified associations
  → eight-section projection + pinned local labels + coverage
  → generic Artifact storage and bounded observation
```

The plan is fixed per data group/event category, not chosen by the model or by a
dynamic provider score. Retain complete validated responses internally before
projection. Reuse source reads within the request; a missing field does not start
another model task, a replay download, or a remote parse job. This does not change
the identity resolver: it continues to consume complete internal OpenDota records
and publish only resolution evidence. No provider tool namespace or router
framework is required.

| Group | Initial source policy |
|---|---|
| Match identity/result, draft, player identity/final statistics | STRATZ; `match.score` sums each side's nonnegative integer kill buckets. Explicit OpenDota final side score supplements only an unavailable side. |
| Player cumulative earned gold; team earned-gold/experience advantage | OpenDota `gold_t`, `radiant_gold_adv`, `radiant_xp_adv` with their verified axes |
| Player minute experience/farming | STRATZ only after field-specific bucket validation; OpenDota `xp_t/lh_t/dn_t` with `times` is the explicit initial supplemental group while that verification is pending |
| Deaths | Verified STRATZ death construction described below; explicit OpenDota death/kill evidence may supplement only with its scope recorded |
| Final equipment, timed inventory observations, purchases, timed ability upgrades, buybacks | STRATZ source facts under the build/event rules below; OpenDota supplies retained neutral-history/final auxiliary fields without a verified STRATZ mapping; no reconstruction from purchases |
| Tormentor | STRATZ explicit `chatEvents.type=117`; no inferred killer/reward |
| Courier and remaining objective records | OpenDota explicit objectives; exclude categories already selected elsewhere, including Tormentor, to avoid cross-source duplication |
| Roshan kills, Aegis pickups, specific building destructions | OpenDota explicit objective records, selected by whole category; do not stitch partial STRATZ messages into a supposedly complete list |
| First blood | Preserve STRATZ reported time and explicit message facts separately; record disagreement |
| Hero interactions | Verified explicit STRATZ target-damage facts; confirmed normalized deaths for kill counts; OpenDota direct hero maps for unsupported damage/healing groups |
| Level, consumed upgrades, known ability ranks | STRATZ explicit level/buff/ability events; no use of `levelObtained` as hero level. Unknown IDs stay unknown. |
| Support | STRATZ item uses/purchases and ward categories; a missing whole STRATZ ward category uses associated OpenDota placement logs and explicit placement/kill counters. Ward expiry logs are never ward kills. |

A null STRATZ `data.match` returns `provider_error` with the message
`STRATZ returned no record for the requested Valve game ID` and the requested
`valve_game_id` in error details. This describes only that lookup, not a
provider-wide outage or proof that a target esports game lacks data. Positive
IDs are not classified as PandaScore or Valve IDs by their digit count.

A STRATZ transport/root-schema/identity failure returns the existing structured
error; there is no silent whole-record failover. An OpenDota identity mismatch or
malformed root record likewise fails validation. A supplemental read's ordinary
unavailability (not found, timeout, rate limit, or provider error) leaves only its
dependent groups unavailable, with a safe source-failure reason in coverage;
it never becomes an empty event list. Cancellation, unexpected programming errors,
and local resource/storage failures keep their normal error behavior. No failed
read is entered as a successful `sources` entry.

The implemented tool registers when `DOTAMIND_STRATZ_TOKEN` is configured.
`DOTAMIND_OPENDOTA_ENABLED=true` enables supplements and continues to govern the
resolver's OpenDota access. STRATZ's default timeout is 30 seconds, configurable
through `DOTAMIND_STRATZ_TIMEOUT_SECONDS`; explicit environment values still win.
No new provider-selection flag is added.

One narrowly supported partial GraphQL response is an error whose path identifies
an existing player's optional `playbackData` subtree. The adapter validates the
remaining primary record and retains only safe field-issue paths, not error
messages. Coverage records the unavailable playback fields; fixed supplemental
groups still work. Root, identity, unknown/unscoped errors, and transport failures
remain errors. Other STRATZ clients retain their default rejection of GraphQL
errors. Do not relabel this partial response as complete replay coverage.

The [STRATZ source reference](../reference/stratz-game-detail.md) records verified
sample facts and remaining semantic gates. It is not an exhaustive API schema.

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
| Images and presentation | The current DTO adds no image fetching/display protocol. The accepted report target separately permits image-only heatmaps under [its contract](game_detail_report.md); raw positions never enter this DTO. Frontend layout remains separate. |
| Semantics not verified | Mark them pending; do not assign a business meaning |

Counts, ordering, and field mappings are data transformations, not performance judgments. Each still needs a reproducible rule.

### Game-relative time labels

The capability DTO constructs display labels from validated seconds before public
tool output and Artifact storage. Labels use signed `MM:SS[.fraction]`: minutes
have at least two digits and accumulate beyond 59; seconds have two digits.
Preserve negative pre-game values and significant fractional seconds without
rounding or truncation. Remove insignificant trailing fractional zeros; numeric
negative zero displays as `00:00`. These are game-relative values or durations,
not calendar timestamps, and have no timezone conversion.

| Seconds field | Derived label field | Examples |
|---|---|---|
| `time_seconds` | `time_label` | `600` → `"10:00"`; `1010` → `"16:50"`; `-89` → `"-01:29"`; `1478.25` → `"24:38.25"` |
| `duration_seconds` | `duration_label` | `2904` → `"48:24"`; `3600` → `"60:00"` |
| `reported_time_seconds` | `reported_time_label` | `0` → `"00:00"` |
| `time_dead_seconds` | `time_dead_label` | `28.125` → `"00:28.125"` |
| Economy `minute_timeline[].time_seconds` | `minute_timeline[].time_label` | Bind each verified time and its advantage values in one record; `600` → `"10:00"` |

Each label is a string or `null`; a missing seconds value produces `null`, not
`00:00`. An unavailable team axis yields `economy.minute_timeline=null`; unaligned
advantage arrays are not exposed as a second public route. An explicitly empty,
verified axis and matching empty metrics yield `minute_timeline=[]`. Minute-node time is
a required integer, so an existing minute node always has a non-null label.
Do not introduce a `minute` field or infer timestamps from array positions.

The following core public timeline collections use records with their own
`time_seconds` and `time_label`; none expose parallel time/value arrays:

| Collection | Payload bound to each time |
|---|---|
| `players[].minute_timeline` | Earned gold, experience, last hits, denies, kills and known deaths |
| `economy.minute_timeline` | Radiant gold and experience advantage |
| `builds.players[].purchase_events` | Item and charges |
| `builds.players[].inventory_events` | Six inventory slots, three backpack slots and neutral slot |
| `builds.players[].ability_upgrade_events` | Ability and reported level |
| `builds.players[].neutral_item_history` | Neutral item and enhancement |
| `events.hero_deaths` | Victim, killer, gold attributes and time dead |
| `events.buybacks` | Player slot |
| `events.building_destructions` | Building, actor and source player slot |
| `events.roshan_kills` | Explicit Roshan kill fact |
| `events.aegis_pickups` | Pickup player slot |
| `events.first_blood.objective_events` | Explicit first-blood objective fact |
| `events.other_objectives` | Explicit courier, Tormentor or other objective fact |

`players[].level_events`, `players[].support.events`, and
`builds.players[].permanent_upgrade_events` also use the same time/label pair.
Minute timelines and report snapshots expose only their owning minute's
`time_seconds/time_label`. Level, inventory and neutral-item states do not carry
separate observation timestamps in minute views. Select only observations at or
before the minute boundary; retain exact original times in the event histories.

Time and payload correspondence is constructed and validated below the public
capability boundary. Item slots remain ordered lists inside one inventory
record; they are not a parallel time axis. Source provider arrays remain
internal. `first_blood.reported_time_seconds`/`reported_time_label`, match duration
and death duration are scalar time pairs, not separate timeline axes. Preserve
unknown event times as null and source-empty event lists as empty lists.

The original seconds remain unchanged and authoritative for matching, sorting,
and calculations. Labels are deterministic display values, not new source facts,
minute buckets, or proof that an event belongs to a player. The same formatter
serves all explicitly typed time fields, including purchases, neutral history,
deaths, buybacks, objectives, and first blood. Do not format arbitrary numbers,
calendar timestamps, or scalar evidence in `coverage`. Generic Artifact tools do
not add labels. A supplied non-null label inconsistent with its validated seconds
is invalid; DTO construction generates omitted labels from those seconds.

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

STRATZ NPC IDs have their own versioned namespace. Use a verified internal
versioned mapping tied to the game's `gameVersionId` to obtain an exact internal
unit name before local `UnitCatalog` lookup. A missing historical mapping is a
coverage gap, not a guessed hero ID. This contract adds no request-time static
Catalog/constant fetch. Hero/item/ability IDs also require namespace validation
before Catalog lookup.

## Section contracts (implemented schema)

The sections below define the public projection. Unverified source meanings
remain explicit limitations; a new source
mapping must pass its semantic gate before it supplies a strongly named field.

### 1. `match`

**Responsibility:** identify the recorded game context and its result.

| Target field | Type | Source and rule |
|---|---|---|
| `match_date` | `YYYY-MM-DD` string or `null` | Convert STRATZ `startDateTime` from validated Unix seconds using `Asia/Shanghai`. If unavailable or invalid, emit `null`. |
| `duration_seconds` | integer or `null` | STRATZ `durationSeconds`, representing formal game duration. Do not add a pre-game/BP duration. |
| `duration_label` | string or `null` | Program-formatted `duration_seconds` under the game-relative time-label rules above. |
| `game_winner` | `"radiant"`, `"dire"`, or `null` | Strict STRATZ `didRadiantWin` boolean mapping: true gives `radiant`, false gives `dire`, unknown gives `null`. |
| `score` | object or `null` | Sum STRATZ `radiantKills/direKills` integer nonnegative buckets by side; unavailable sides use explicit OpenDota `radiant_score/dire_score`. Do not use array length, last bucket or player kill totals. |
| `competition` | `null` | Deliberately unpopulated in this version. A future PandaScore-context decision may define it separately; do not copy an OpenDota League body, mix ID namespaces, or report this scope exclusion as a per-game source gap. |
| `teams` | side-keyed object or `null` | This game's STRATZ radiant/dire team identities, with source attribution in coverage. |

Each available side record contains `source_team_id` (integer or `null`) and
`name` (string or `null`). IDs come from STRATZ `radiantTeamId/direTeamId`;
names require validated matching `radiantTeam/direTeam` records. The sampled
detail query verified IDs, not team-name payloads; do not promise populated names
before that selection is validated. Missing records remain `null`. No team tags,
logos, or captain IDs are added.

The side keys associate facts within this game. STRATZ, OpenDota, and PandaScore
team IDs remain source-attributed identities; numeric equality does not establish
cross-source equality. PandaScore opponent order does not assign sides.
`game.detail` does not query PandaScore or repeat name matching. Reuse an accepted
same-game association where available; otherwise keep identities separate.
No permanent cross-source Team map is introduced.

The exact source timestamp is an internal dependency. Preserve validated
timestamps until internal consumers finish; the public field remains `match_date`.

### 2. `draft`

**Responsibility:** ordered pick and ban facts.

| Target field | Type | Source and rule |
|---|---|---|
| `picks_bans` | list or `null` | STRATZ `pickBans`, retaining source array order |
| `order` | integer or `null` | Source `order` |
| `action` | `"ban"`, `"pick"`, or `null` | Strict `isPick` boolean mapping |
| `hero` | entity object or `null` | Verified `heroId` for a pick and `bannedHeroId` for a ban; retain disagreements in coverage instead of guessing |
| `side` | `"radiant"`, `"dire"`, or `null` | Strict STRATZ `isRadiant` boolean mapping |

Do not transfer OpenDota draft `team=0/1` decoding to other event fields. Draft
timings, ratings, and predicted win rates remain excluded.

### 3. `players`

**Responsibility:** preserve per-player identity, final statistics, and source-aligned minute observations.

Each player has `identity`, `final_stats`, `minute_timeline`, `level_events` and
`support`. Keep player records in source array order. Level events contain
`time_seconds/time_label/level`; their absence does not infer initial state.

`identity` contains nullable `account_id` from STRATZ `steamAccountId`,
`player_slot` from validated `playerSlot`, and `hero` from `heroId`. Source-provided
`name` and `personaname` remain nullable; the sampled query did not verify their
STRATZ mappings. Strictly map `isRadiant` to `side` (`radiant`, `dire`, or `null`).
`player_slot` associates rows within this game, not positions one to five. The
sample uses 0–4 and 128–132; validate the encoding rather than equating slot with
array index. Names do not prove identity. Facet/role inference remains excluded.

`final_stats` contains the fields below. Paths are relative to the
STRATZ player unless another source is named:

| Target fields | Type of each field | Source |
|---|---|---|
| `kills`, `deaths`, `assists` | integer or `null` | Same-name source fields |
| `level` | integer or `null` | `level` |
| `last_hits`, `denies` | integer or `null` | `numLastHits`, `numDenies` |
| `gold_per_minute`, `experience_per_minute` | nonnegative integer or `null` | `goldPerMinute`, `experiencePerMinute` |
| `cumulative_gold_earned` | nonnegative integer or `null` | `floor(goldPerMinute * durationSeconds / 60)`; missing inputs yield null. Coverage records the formula/input paths; not an exact final counter. |
| `death_gold_lost` | nonnegative number or `null` | Sum explicit linked death amounts only when all source final deaths and amounts are covered; time may be unknown. |
| `known_death_gold_lost`, `death_gold_lost_count` | nonnegative number / integer or `null` | Known-amount subtotal and number of deaths with known amounts, including supported unknown-time deaths. Neither counts only timed deaths. Unavailable death source yields null. |
| `earned_gold_net_worth_gap` | number or `null` | Reliable cumulative earned gold minus net worth, at the same final instant; rules below |
| `hero_damage`, `tower_damage`, `hero_healing` | number or `null` | `heroDamage`, `towerDamage`, `heroHealing` |

These are final values, not values copied from the last minute sample. Assists
remain final-only until a complete minute mapping exists; minute level uses
explicit level events. Hero damage, tower damage and healing stay final values.
Missing source values are null; explicit zeros remain zero.

`earned_gold_net_worth_gap` is “累计金币与净值差”, not pure death gold loss.
Consumables, other expenditure, asset valuation, and differing observation bounds
can affect the difference. Do not label it `gold_lost`. A last whole-minute
`gold_t` sample cannot be subtracted from a later final `networth`, and GPM ×
duration is not a reliable exact same-instant replacement for this gap. The
accepted report may expose the GPM-derived final income separately with its
derivation, but exact terminal inputs for this gap remain unestablished: currently
emit `null` with one coverage limitation when these prerequisites are absent.
Do not clamp a negative difference or invent a causal breakdown.

Public `final_stats.net_worth` is removed, without an alias/raw escape hatch.
Original net-worth facts remain internal for validation and existing consumers.
Wallet/spend fields, unapproved extra scoreboard fields, ratings, and role judgments
remain excluded. Final death count remains the source total even when event
coverage is partial.

`minute_timeline` is a list of records with these fields:

| Field | Type | Source and rule |
|---|---|---|
| `time_seconds` | integer | Verified source sample boundary; initial supplemental series use OpenDota `times`. Invalid axes do not create nodes with unknown time. |
| `time_label` | string | Program-formatted `time_seconds`; for example `1200` → `"20:00"`. |
| `cumulative_gold_earned` | number or `null` | OpenDota `gold_t` at the verified `times` index: cumulative earned income, not wallet balance or remaining asset net worth |
| `cumulative_experience` | number or `null` | Initially OpenDota `xp_t`; STRATZ `stats.experiencePerMinute` may replace it only after interval/axis and prefix-sum semantics pass the gate below |
| `last_hits` | number or `null` | Same-index `lh_t` value |
| `denies` | number or `null` | Same-index `dn_t` value |
| `kills` | integer or `null` | Count confirmed player-attributed kill facts at or before this node; no raw STRATZ kill-event length counting |
| `known_deaths` | integer or `null` | Count `events.hero_deaths` rows for this victim with known time at or before the node; records with unknown time do not enter the curve |
| `assists` | `null` | Complete minute attribution is unverified; not zero or an inferred count. |
| `level` | integer or `null` | Latest unique explicit level observation at or before the minute; no future observation or final-level backfill. |

`last_hits` and `denies` initially use OpenDota `lh_t/dn_t` on their own `times`.
Do not presume STRATZ `lastHitsPerMinute/deniesPerMinute` are cumulative counters
before verifying their bucket semantics. No minute `net_worth`, replacement gap,
inferred assists or embedded equipment list is emitted. All public values sourced from `gold_t`
use `cumulative_gold_earned`; the earlier `earned_gold` alias is removed.

Do not align different series merely by array length, interpolate, or append final
statistics to a minute node. Include valid pre-zero events in cumulative counts.
An unavailable death source yields `known_deaths=null`; partial timed evidence
can produce a known-count curve with explicit partial coverage. Zero means zero
known timed deaths, not proof of zero total deaths. Preserve final totals and
coverage of unknown-time and unassociated facts independently.

`support` contains `events` and `totals`. Each event binds its time/label, bilingual
item, action and nonempty `source_paths`; each total binds the item/action, count,
`scope` (`source_total` or `known_events`) and source paths. Actions are `used`,
`ward_placed`, `ward_killed_by_player` and `purchase_record`. Ward kills are
attributed to the killing player, not the owner of the lost ward. A purchase
record is not a purchased-unit count. Missing item/action totals stay unknown;
combination-ward uses do not split into placements. Gem holding time is not derived.

### 4. `economy`

**Responsibility:** team-level advantage facts and their time basis. Player minute metrics stay under `players.minute_timeline`.

OpenDota `radiant_gold_adv` remains an explicitly attributed source gold-advantage
fact, not a net-worth difference. It must not receive STRATZ
`radiantNetworthLeads`, whose metric is different. No player or team minute
net-worth series is added through another name. The rename of `gold_t` applies
to its public player values; it does not rename an unrelated source field.

| Target field | Type | Source and rule |
|---|---|---|
| `minute_timeline` | record array or `null` | Programmatically bind the verified minute axis to its corresponding source samples. No parallel public time/value arrays remain. |
| `minute_timeline[].time_seconds` | required integer | Reuse player `times` only after verifying all player axes agree and follow `0,60,...`; validate each metric's length independently before binding. |
| `minute_timeline[].time_label` | required string | Format the same record's seconds with the shared formatter. |
| `minute_timeline[].radiant_gold_adv` | number or `null` | Original OpenDota gold-advantage sample, including its sign; invalid samples remain `null` with coverage. |
| `minute_timeline[].radiant_xp_adv` | number or `null` | Original OpenDota experience-advantage sample with the same rule; STRATZ substitution requires its own verified axis. |

Do not assume every player array shares the same axis or that an advantage array can be aligned merely because lengths match. When correspondence cannot be established, leave the affected axis or series unavailable and report only a material promised-data gap or conflict.

Require strictly increasing integer axes. A mismatched metric becomes `null` in
all minute records without truncating other metrics or fabricating its missing
tail. An invalid individual sample affects only its own value. OpenDota team
arrays retain the verified `0,60,...` alignment checks; an unavailable axis or no
alignable metrics yields `minute_timeline=null` with coverage. Source arrays stay
internal; do not expose unbound values, infer an axis from array length, silently
zip unequal arrays, or derive missing samples from final statistics. Unknown-time death facts do not invalidate
other timed death facts. For STRATZ, validate interval versus point semantics,
starting boundary, and terminal bucket independently for each series before
constructing a time axis. The sample has 64/65/66-length arrays; no universal
shift/truncation rule follows. Its 640 player XP prefix sums match OpenDota,
which is sample evidence for a candidate conversion, not all-array validation.

Query a minute by its `time_seconds`, for example
`expression="$.report.player_statistics.team_economy_timeline[?@.time_seconds == 60]"` with
`fields=["time_seconds", "time_label", "radiant_gold_adv", "radiant_xp_adv"]`.
The two advantage metrics preserve their original meanings. Additional economy
fields require a separate decision.

### 5. `builds`

**Responsibility:** final loadout, observed timed inventory, purchases, timed
ability upgrades, and source neutral-item history. These are separate views.

Each player build is associated by `player_slot` and contains:

| Subsection | Target fields and source |
|---|---|
| `final_loadout` | Six `inventory` slots from STRATZ `item0Id..item5Id`, three `backpack` slots from `backpack0Id..backpack2Id`, and `item_neutral` from `neutral0Id`. `item_neutral2` is the OpenDota enhancement supplement. Legacy numeric upgrade fields retain their OpenDota values; `has_consumed_scepter/has_shard/has_consumed_moon_shard` are explicit STRATZ buff-presence facts, supplemented by associated OpenDota 0/1 flags when unknown. Held Scepter is separate from consumed status. |
| `inventory_events` | Ordered STRATZ `playbackData.inventoryEvents`: `time_seconds`, derived `time_label`, six-position `inventory`, three-position `backpack`, and nullable `item_neutral`. Slots contain `{item: entity or null, charges: number or null}` from the corresponding `itemN/backPackN/neutral0` objects. A missing whole slot is null with coverage; a known empty slot has `item=null`. Preserve observed source snapshots, not inferred acquisition/removal actions. |
| `purchase_events` | Initially STRATZ `stats.itemPurchases`, in source order: `time_seconds` from `time`, derived `time_label`, `item` from `itemId`, nullable `charges` only if explicitly provided. Do not merge this list with `playbackData.purchaseEvents`; their differing counts do not establish the same semantics or completeness. |
| `ability_upgrade_events` | STRATZ `playbackData.abilityLearnEvents`: time/label, bilingual ability, `level=source.level+1` for known nonzero ability IDs and valid nonnegative ranks, plus nullable `is_talent/is_ultimate`. Unknown ability ID 0 has null identity/rank with scalar coverage evidence. `levelObtained` never supplies a hero level. |
| `neutral_item_history` | Retained OpenDota records: `time_seconds` from `time`, derived `time_label`, `item` from `item_neutral`, and `enhancement` from `item_neutral_enhancement`; entity values are nullable. Retain source order and partial records. The action remains unverified. |
| `permanent_upgrade_events` | Explicit STRATZ `stats.matchPlayerBuffEvent`: time/label, bilingual item, nullable `stack_count`, `upgrade=consumed_scepter/shard/consumed_moon_shard` for verified IDs 108/609/247. Absence alone does not prove inactive state. |

Keep component and completed purchases as separate source records. Do not infer
recipe links, missing completions, total spend, delivery, or usability. Inventory
observations come only from explicit timed snapshots, never purchase
reconstruction, and stay outside `players.minute_timeline`. Untimed
`inventoryReport` entries do not receive guessed minute timestamps. Additional
teleport fields are excluded. Neutral-history actions remain unverified; the
second neutral slot is an enhancement, not a second ordinary equipped item.

### 6. `events`

**Responsibility:** the first-version event categories below, retaining precise source time and source attribution.

| Category | Source boundary |
|---|---|
| `hero_deaths` | One normalized list of verified death facts, including unknown-time facts when supported; rules below |
| `buybacks` | Source buyback records; do not duplicate purchases from `builds`. |
| `building_destructions` | Verified building-destruction objective records. |
| `roshan_kills` | Verified Roshan-kill objective records. |
| `aegis_pickups` | Verified Aegis-pickup objective records. |
| `first_blood` | Preserve the available first-blood source records and any disagreement. |
| `other_objectives` | Preserve courier/Tormentor events and other objective records; unknown codes use a null type with scalar evidence in coverage. |

Use exact source event time in seconds, including negative values. Retain each category's source order; the separate category arrays do not imply a global event order. Equal-time records have no inferred ordering. Resolve event units explicitly using the local hero and non-hero mapping. Unknown units become field-specific coverage gaps rather than raw keys in business records. Do not assign an event to a player or side from an unverified `team` or `killer` encoding.

An empty source list is evidence of an empty response, not necessarily an empty
game category. Emit `[]` for a validated empty category with its actual coverage;
when no usable category source exists emit `null`. Do not interpret either as
proof of zero events unless completeness has been established. Every event has
`source_paths`, a nonempty list of `{source, path}` pairs referencing successful
entries in outer `sources` and exact paths in the internally retained responses.
These are provenance, not raw-response retrieval handles.

Each normalized `hero_deaths` row has:

| Target field | Type | Source and rule |
|---|---|---|
| `time_seconds` | number or `null` | Verified source death time; unknown time remains null |
| `time_label` | string or `null` | Program-formatted `time_seconds` |
| `victim_player_slot` | integer or `null` | Validated owning player's slot; not a source event's unverified target code |
| `killer_player_slot` | integer or `null` | Fill only when source evidence explicitly identifies the corresponding player; otherwise `null` |
| `killer_unit` | unit object or `null` | Verified actual unit identity only; a credited killer player is not automatically the attacking unit |
| `gold_lost` | number or `null` | Explicit linked death-gold amount after amount/sign semantics are validated; zero is valid and is not filtered out |
| `gold_fed` | number or `null` | Verified linked `goldFed` or OpenDota `gold_fed`; not final earned-gold/net-worth gap |
| `time_dead_seconds` | number or `null` | Verified linked `timeDead` or OpenDota `time_dead` |
| `time_dead_label` | string or `null` | Program-formatted `time_dead_seconds` |
| `source_paths` | provenance-pair array | Exact contributing source records; retain both paths only for a verified association |

The initial STRATZ construction uses the owning player's
`playbackData.goldEvents` with `reason="DEATH"` to retain death facts and times.
Only a unique same-owner-hero, same-time, one-to-one death record supplies
additional attributes; ambiguous associations retain null attributes and their
coverage reason. Three live games (203 facts across 30 players) matched final
per-player counts. Do not filter these facts by `isValidForStats`: it is false
for all sampled DEATH records. Do not join by gold amount or fill `gold_lost`
from its negation: it often differs from explicit `deathEvents.goldLost`.
Raw `stats/playbackData.deathEvents` and `killEvents` contain substantially more
records than final totals in the sample. Neither raw length, `timeDead>0`, nor
`goldFed>0` is a valid general death-selection rule. Do not drop zero-amount
DEATH records. Additional encodings and historical cases still require the
verification below; these samples do not prove universal completeness.

OpenDota `players[].deaths_log`, when present, supplies explicit death facts;
`kills_log` supplements victims without a selected usable death log through exact same-game hero
association. It misses non-player killers and is not a complete death log.
Select one death source for each victim before adding events; this fallback does
not merge duplicate direct-death and kill-log rows. Its known counts remain
partial even if they happen to equal the final total.
`killed_by` is an aggregate, not a timestamped event list. Keep useful aggregate
facts in coverage; do not fabricate individual timed events or attackers from a
count difference. A supported individual death with unknown time remains a row
with null time; a bare final count alone does not create synthetic rows.

Normalize once, then derive minute `known_deaths` and confirmed kill relations
from that list. Match across sources only with unambiguous event evidence;
equal seconds alone do not prove duplication. Preserve ambiguous facts and
conflicts without counting them twice as confirmed events. An unknown attacker
does not mean fountain, and a hero label does not identify a summon controller.
Missing optional row attributes remain null without repetitive per-row warnings.

Conflicting first-blood sources remain separate values in `coverage.conflicts`; do not adjudicate them. Preserve end-of-game timestamps even when they exceed `duration_seconds` by one second. The data contract does not add an anomaly warning or a frontend endpoint-display rule. Eye wards, runes, and pauses are outside the first-version event categories. Mapping unit names does not add ward events or non-hero interaction tables.

OpenDota supplemental objectives keep the following exact `type` mapping and
local bilingual units. STRATZ chat codes use only the individually verified
equivalent categories; code 117 is Tormentor, 9 Roshan, 8 Aegis, and 5 first blood.
Message actor/reward fields require separate verification:

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
| Buyback | STRATZ `playbackData.buyBackEvents[].time` and validated owning player's slot. Do not publish `cost` as a verified expense: all thirteen sampled costs are zero and the meaning/completeness remains unverified. |
| OpenDota objectives | `time_seconds` from `time`; normalized `type` from the table above; `target_unit` from `key` only when it is an exact mapped unit identifier; `actor_unit` from exact unit conversion of `unit`. Do not copy `source_type`, `source_key`, or `source_unit_key` into business fields. Apply only the selected source category, not every recognized row from both providers. |
| STRATZ messages | `time_seconds` from `chatEvents[].time`; `type` from a verified chat code. Target/actor/player fields stay null without separately verified payload semantics. Preserve unverified present scalar evidence in coverage. |
| Other source codes | Present unverified `slot`, `team`, `killer`, `value`, or non-unit `key` values remain scalar evidence in coverage with exact source paths. They do not become business identities or inferred rewards. Missing optional values require no warning. |
| Objective players | `player_slot` and `victim_player_slot` are populated only from explicit same-name source fields matching one unique player slot in this record. A bare `slot`, `team`, or `killer` never supplies a player identity. |
| Tormentor reward | Nullable `reward_player_slot/reward_item`; only a unique message hero, unique same-game player slot, unique same-time type-117 message and unique same-time explicit Shard buff supply the recipient. Include both source paths. Do not supply the killer from this relation. |
| First blood | Nullable `reported_time_seconds` from STRATZ `firstBloodTime`, derived `reported_time_label`, and nullable `objective_events` from explicit first-blood messages. Preserve exact source paths and material disagreements; neither overwrites the other. |

Buyback and objective records likewise include `time_label` derived only from
their own `time_seconds`. Conflicting first-blood views retain their own labels;
formatting does not resolve their disagreement.

The Service supplies pinned local entity/unit resources. A credited killer slot
requires verified event encoding and one unique matching same-game player.
STRATZ `attacker/target/fromHeroId/value` have field-specific meanings; do not
decode them all as hero IDs or player slots. Missing one player's usable evidence
does not erase other players' known events. Preserve source order within each
selected category without claiming a total ordering across providers.

### 7. `interactions`

**Responsibility:** per-player `kills_by_target`, `damage_by_target`,
`damage_received_by_source` and `healing_by_target`.

The structure is `interactions.players[]`; each player entry contains `player_slot`
(integer or `null`) and the three target lists. Each target record contains
`target_hero` (entity or `null`) and `value` (number). Resolve only a validated
Valve hero ID or an exact Catalog internal-name match. An unconvertible target
retains its known amount with a null entity and scalar coverage evidence.
Do not expose raw target keys, use fuzzy names, or guess a target player.

The projector uses local bilingual entity objects as specified above, without remote lookups. A malformed hero amount makes only that target map unavailable and adds a coverage reason, preserving the player's other maps and final statistics.

| Target list | Direct source | Target scope |
|---|---|---|
| `kills_by_target` | Confirmed normalized death events with validated credited killer and victim | Count confirmed hero pairs; partial event coverage remains partial, not a complete kill matrix |
| `damage_by_target` | STRATZ `stats.heroDamageReport.dealtTargets` after target namespace validation; initial supplement OpenDota `players[].damage` for unsupported target mappings | Hero entries only; preserve explicit amount |
| `damage_received_by_source` | STRATZ `stats.heroDamageReport.receivedTargets` | Each row is `{source_hero,value}`; identify the attacking hero rather than treating it as another target. Unverified identities stay unknown. |
| `healing_by_target` | OpenDota `players[].healing` until a verified STRATZ per-target healing source is available | Hero entries only, including self-healing; preserve explicit amount |

Retain source order for direct maps and first-confirmed-pair order for event
counts. For OpenDota maps, hero entries use `npc_dota_hero_`; for STRATZ, verify
the target encoding rather than treating every target number as a hero ID.
An unresolved known-hero row retains its amount with a null entity and coverage.
Exclude non-hero targets from this view. Do not add ratings, ability/item damage
breakdowns, inferred assists, or recompute last hits/denies here.

An absent source map is `null`; an explicitly empty source map is an empty list. Do not synthesize zeros for unobserved pairs. Do not add contribution ratings, assist inference, counter analysis, or deeper interaction tables. If an interaction count differs from another source view, preserve both and record a material conflict instead of rewriting either value.

### 8. `coverage`

**Responsibility:** compactly identify promised data that is missing, retain source scalars that cannot be reliably converted, and preserve material source disagreements.

The target expands the current `missing/conflicts` object with group provenance
and per-player death coverage:

| Field | Type | Meaning |
|---|---|---|
| `groups` | list of `{path, status, source_paths, reason?}` | DTO field group/event category; `status` is `available`, `partial`, or `unavailable`. `source_paths` contains `{source,path}` pairs referring to successful reads in `sources`. `available` describes the promised field scope, not every real-world fact. A failed supplemental read has no success reference and is explained by `reason`. |
| `death_counts` | per-player list described below | Separate final totals from located/unknown-time evidence and remaining coverage |
| `missing` | list of `{path: string, reason: string, source?: string, source_path?: string, source_value?: scalar}` | Affected DTO path and safe reason. `source` names the provider attempted, including a failed read; scalar evidence describes present unmapped codes/keys. No source objects/arrays. |
| `conflicts` | list of `{sources: string[], paths: string[], values: scalar[]}` | Provider, exact source path, and observed value correspond by index. Preserve disagreements without adjudication. |

A scalar is a string, finite number, boolean, or null. Optional source-evidence fields are omitted when there is no corresponding present source value; do not fabricate a source value for an absent key.

Each `death_counts` entry contains `player_slot`, `final_deaths`,
`known_time_deaths`, `unknown_time_deaths`, and `unaccounted_deaths`, all nullable
integers. Counts of known/unknown-time facts come from normalized rows, not raw
lists or invented residual events. `unaccounted_deaths` is final minus those two
counts only when all operands are known and the event association is unambiguous;
an excess or ambiguous association produces null and an explicit coverage reason,
never a negative gap or forced reconciliation. Preserve the observed counts;
do not fabricate source scalar paths for derived counts. Actual source-scalar
disagreements still use `conflicts`. Unknown source coverage is null, not zero.

For example, an unavailable death source explains
`players[1].minute_timeline.known_deaths`; a partial source explains its scope
without hiding a usable curve. Invalid time alignment can explain an unavailable
metric even if the source array exists. The STRATZ sample's first-blood conflict
retains values 56 and 79 with their respective source paths. These labels are
evidence, not a raw-response retrieval route.

For example, an unmapped neutral item can produce
`{"path":"builds.players[6].neutral_item_history[1].item","reason":"Catalog key not found","source":"opendota","source_path":"players[6].neutral_item_history[1].item_neutral","source_value":"guardian_shell"}`.
Indices must come from the actual row; this illustrates the shape. An unknown
building actor leaves the known target and time intact. Deliberately removed
minute net worth is not a missing-data entry.

Do not list features this version never promises, such as competition fields or extra final stats. Do not warn for every absent optional event attribute. Present source encodings that cannot be interpreted use the scalar mapping-gap rule; successfully converted keys are not copied again. Deduplicate identical gap entries without losing their affected paths. Do not add confidence or quality scores, long diagnostic prose, raw objects, or a raw-response retrieval handle. Missing data in a non-core section does not erase other usable sections. Invalid game identity or another root contract failure returns an error, never a successful DTO. Unexpected resolver/storage/programming failures are not silently converted into per-key misses.

Conflict source/path/value lists have equal lengths and at least two observations.
Use actual source indices. Do not turn `isStats`, aggregate missing counts, or an
unavailable non-core section into a whole-result failure or a claim that all
economy/experience facts are absent. Missing optional row attributes do not
generate repetitive warnings; missing promised logs/times do.

## Illustrative target fragments

The values below come from the saved OpenDota response for game `9040460429`.
They illustrate retained facts under the implemented names, not a complete result
or a claim that every source supplies them. Bilingual labels
come from the local Catalog.

The source start time converts to the Beijing calendar date shown. The formal duration is 2,904 seconds; `radiant_win=false` maps to a Dire win. The source score is 17–33.

    match = {
      "match_date": "2026-10-12",
      "duration_seconds": 2904,
      "duration_label": "48:24",
      "game_winner": "dire",
      "score": {"radiant": 17, "dire": 33}
    }

The first source pick/ban row is a ban by source team code 0:

    {"order": 0, "action": "ban", "hero": {"id": 59, "name_zh": "哈斯卡", "name_en": "Huskar"}, "side": "radiant"}

For account `321580662`, source slot 1 and hero ID 1, the 600-second sample has
cumulative income 2,930, cumulative experience 2,383, 39 last hits, and 2 denies.
The saved logs give one kill and zero located deaths through that time:

    {
      "time_seconds": 600,
      "time_label": "10:00",
      "cumulative_gold_earned": 2930,
      "cumulative_experience": 2383,
      "last_hits": 39,
      "denies": 2,
      "kills": 1,
      "known_deaths": 0
    }

That player's final values include K/D/A 3/6/4, level 25, 605 last hits,
3 denies, hero damage 14,456, tower damage 686, and healing 0. The target tenth
field `earned_gold_net_worth_gap` is null without reliable same-instant terminal
inputs; the original net-worth number is not exposed under another public path.

The source purchase log includes component keys `faerie_fire` and `slippers` at -89 seconds, `power_treads` at 388 seconds, and `manta` at 1,478 seconds. Convert each key into its own bilingual item entity while preserving those separate records; do not assert a recipe relationship. The last becomes `{"time_seconds":1478,"time_label":"24:38","item":{"id":147,"name_zh":"幻影斧","name_en":"Manta Style"},"charges":null}`.

A saved death record for this player is at 815 seconds and carries source `npc_dota_hero_pangolier`, which supplies the bilingual hero `killer_unit`. The interaction map records one kill against `npc_dota_hero_monkey_king`; its target becomes `{"id":114,"name_zh":"齐天大圣","name_en":"Monkey King"}`. Source keys are conversion inputs, not duplicated public fields.

Game `8960991322` demonstrates why source selection matters: STRATZ Tormentor
messages are at 1982 and 2839 seconds; explicit OpenDota Roshan kills are at
1795, 2452, and 3038. Five STRATZ `ROSHAN` gold-reason timestamps include both
categories and must not become five Roshan kills. STRATZ first-blood report 56
and explicit message 79 remain a conflict.

This contract does not promise a DTO byte-size target. The old 105 KB and 215 KB experimental DTOs contain fields excluded or still unapproved here; they are not templates for the final schema.

## Verification gates and implementation prerequisites

| Kind | Item |
|---|---|
| Current implementation scope | `competition=null`, the documented final-stat/rate/income/death-loss fields, no minute net worth, only `source_team_id`/`name` for teams, no ratings or inferred replay facts. Reports include state facts, support and interactions; image-only heatmaps are separate from frontend layout, replay parsing and a background League index. |
| Source-semantic limits | OpenDota's second neutral slot is the accepted enhancement supplement; STRATZ has no verified corresponding slot. Neutral-history actions remain unverified. New actor/team/reward encodings require evidence; the report target permits only its individually verified same-player/time Shard association for a Tormentor recipient. |
| Mapping gaps | `dota_unknown` is explicit source uncertainty. Sampled `guardian_shell` has no exact record in the checked local Catalog; keep that field unknown with scalar evidence until a verified mapping is added. Neither blocks other match facts. |
| Implemented enrichment | Bilingual entity/unit objects, event conversion, snapshot provenance, and scalar mapping-gap fields are implemented and tested together with public tool/Artifact output. Unknown names/keys remain explicit. |
| Implemented internal record split to preserve | The resolver consumes complete `OpenDotaGameRecord` values independently of the public `GameDetailResult` constructed by `GameDetailService`. Keep exact source timestamps, side-specific team IDs, identity-validation inputs, and accepted per-game associations available internally when adding the DTO projection. |
| Death-selection gate | Validate the candidate DEATH-gold/death-record association on additional real games: zero loss, neutral/fountain/creep killers, reincarnation, summons/illusions, repeated timestamps, and missing logs. Compare per-player normalized counts with final totals; retain partial/conflicting coverage rather than adjusting events to fit. |
| Time/metric gate | Verify each STRATZ point/interval series and bucket boundary; test negative, exact-minute, between-minute, and terminal times. Sample XP agreement alone does not validate farming, gold, or team arrays. |
| Income gate | Do not replace minute OpenDota cumulative income until STRATZ complete-income coverage is verified. The accepted final GPM/whole-duration formula is explicitly derived and source-attributed, not an exact terminal counter; same-instant inputs remain required for the final gap. |
| Payload/identity gate | Verify team names, new event actor/target namespaces, non-hero NPC constants by game version, and actual source errors. The revalidated zero-based skill ranks apply only to known nonzero abilities under their gate; unknown IDs/encodings remain gaps. |
| Public acceptance | Deterministic projection/Service/Artifact checks cover the schema, source table, partial GraphQL responses, source reuse, and errors. Three live complete reads and frozen-source model checks are distinct evidence in EVALS; neither guarantees all future provider requests. |
| Implemented resolver boundary to preserve | `esports.game.resolve` retains complete reads internally and publishes only the resolution evidence owned by the cross-source contract in `DATA.md`. Its Artifact cannot retrieve candidate detail bodies or full source collections. Preserve this separation when extending the governed `game.detail` DTO. |
| Non-blocking separation | Static names do not complete missing historical match facts. The accepted heatmap target runs separately and cannot invalidate detail on failure; frontend behavior, automated unit-data refresh and deployment are not implied by these documents. |

The source policy, economic names, and STRATZ-first public switch are implemented.
The sampled initial death rule and other
unverified mappings must pass their gates; an explicit limitation is preferable
to guessing. Preserve the implemented internal record split and resolver
public-evidence boundary throughout this migration.

## Ownership and acceptance

The data boundary and migration notes live in [`../DATA.md`](../DATA.md). Tool behavior is summarized in [`../TOOLS.md`](../TOOLS.md), layer ownership in [`../ARCHITECTURE.md`](../ARCHITECTURE.md), deterministic acceptance in [`../EVALS.md`](../EVALS.md), and implementation order in [`../ROADMAP.md`](../ROADMAP.md).

Deterministic checks establish the implemented boundaries. The reference records
live observations; model checks use fixed source snapshots. These do not establish
frontend behavior or universal analytical correctness.
