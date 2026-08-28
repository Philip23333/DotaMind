# Data

## Domain model

vNext uses a small provider-neutral esports navigation domain:

```text
League -> Series -> Tournament -> Match -> Game
```

PandaScore is the current primary source for that navigation and event context.
OpenDota becomes authoritative only after a concrete Game has been resolved to a
canonical Valve match ID.

Team and professional Player are additional navigation entities where the model
needs cross-capability locators.

A Domain Ref is a locator, not a generic ID wrapper. Use it only when another
capability may need to receive the same entity again. Examples include
`SeriesRef`, `MatchRef`, `GameRef`, `TeamRef`, and `PlayerRef` where those tool
contracts require them.

Provider-private IDs remain internal to provider/domain resolution. A single
provider entity must have exactly one deterministic Domain Ref construction rule;
different services must not invent separate hash recipes for the same entity.

## Provider roles

Current roles are intentionally narrow:

- PandaScore: esports navigation and readable event context
- OpenDota: resolved Valve-match detail and recorded game facts
- committed Valve catalog: static hero/item/ability reference facts

The current game chain is:

```text
PandaScore Game
  -> cross-source resolution
  -> valve_match_id
  -> OpenDota game detail
```

OpenDota does not currently define which Series, Tournament, or PandaScore Match
a Game belongs to.

## Identity boundary

Provider-private resource IDs do not enter canonical Artifacts or model-facing
navigation contracts. Numeric coincidence never merges namespaces.

Canonical Valve/Dota-native identities may cross the Artifact boundary as plain
facts, including:

- Valve match ID
- Valve team ID
- Steam account ID
- hero ID
- item ID
- ability ID

These IDs do not require an additional construction-layer Ref merely because
they identify a Dota entity.

## Static catalog facts

All supported Dota game data sources use Valve-defined hero/item/ability
identity. The committed local catalog provides the stable mapping from those
native IDs to static entity facts such as canonical English/Chinese names.

The target architecture keeps catalog facts separate from dynamic game
Artifacts:

```text
Dynamic Game Artifact
  -> hero_id / item_id / ability_id

Static Catalog
  -> ID <-> name/localization/reference facts
```

The model accesses the static catalog through small local capabilities:
`catalog.search` for text -> IDs and `catalog.lookup` for bounded batch ID ->
static facts.

Artifact production should not duplicate catalog names into every dynamic game
record by default.

## Artifact data contract

An Artifact is a provider-neutral JSON-like document stored outside model
context. It exists so a large complete result can be retained while the model
receives only a bounded view plus a locator.

The target GameSummary document combines:

- readable PandaScore event context: League, Series, Tournament, Match, game
  position
- canonical Valve game identity and recorded OpenDota game facts
- Valve-native hero/item/ability/team/player IDs as scalar facts

It excludes:

- PandaScore/OpenDota private resource IDs
- raw provider payloads
- storage/cache metadata as gameplay facts
- construction-layer Ref wrappers
- duplicated static catalog names as a requirement
- DotaMind-derived gameplay analytics

Conceptual target shape:

```text
GameSummaryArtifact
  artifact_type
  schema_version
  event
    league
    series
    tournament
    match
    game_position
  game
    valve_match_id
    start_time
    duration_seconds
    winner
    game_mode_id
    lobby_type_id
  teams
    radiant { valve_team_id, name, score }
    dire    { valve_team_id, name, score }
  players[]
    steam_account_id
    registered_name
    persona_name
    side
    player_slot
    hero_id
    stats
    economy
    items
      inventory[] { slot, item_id }
      backpack[] { slot, item_id }
      neutral_items[] { slot, item_id }
    purchase_history[] { time_seconds, item_id }
    ability_upgrades[] { ability_id, level, time_seconds }
  draft
    picks[] { order, side, hero_id }
    bans[]  { order, side, hero_id }
```

Missing scalar source facts remain `null`; missing collections remain `[]`;
fixed positional structures may retain empty slots where source semantics make
position meaningful.

## Historical GameSummary schemas

Schema versions 3, 4, and 5 are frozen historical contracts.

- v3 established the earlier canonical game structure.
- v4 added catalog-enriched English/Chinese hero, item, and ability names.
- v5 retained v4 game facts and added readable PandaScore event context.

They must not be silently changed.

The simplified Artifact representation should be introduced as a new schema
version, currently expected to be v6. Its material contract change is that
Valve-native IDs remain directly observable while static catalog translation
moves to catalog tools instead of Artifact construction.

## Ref cleanup target

The current construction layer contains types such as:

- `HeroRef`
- `ItemRef`
- `AbilityUpgradeRef`
- `ItemSlotRef`
- `PurchaseEventRef`
- `DraftEventRef`
- construction-only Team/Player native refs

Most of these are value/event structures rather than locators. The migration
should replace them with ordinary typed values where typing is useful and remove
the `Ref` abstraction where no cross-capability locator exists.

This cleanup must follow a proven v6 production path rather than mutate the old
v4/v5 implementation in place.

## Artifact identity and storage

`ArtifactRef` is the locator for stored canonical documents. GameSummary
identity is based on canonical Valve match ID plus schema version, not on
PandaScore IDs or catalog names.

Redis Artifact storage remains a retention boundary rather than a source of
truth or freshness policy. A missing/expired Artifact does not invalidate the
underlying canonical Game identity.

## Artifact scope

`ArtifactScopeRef -> ArtifactRef[]` is a generic corpus-membership contract.
Known navigation ancestry may register a successfully stored Game Artifact under
League/Series/Tournament/Match scopes.

Scope does not infer membership from Artifact content and does not claim corpus
completeness. Scoped search is materialized-only.

Because scope keys reuse Domain navigation identity, the existing SeriesRef
construction inconsistency must be corrected before scoped corpus behavior is
considered reliable.

## Provenance and uncertainty

Tool-facing domain results should preserve source, fetch time where useful,
identity/resolution status, warnings, truncation, and coverage limits.

Artifact schema should stay focused on the canonical fact document. Do not add a
large quality-metadata framework preemptively; add source-backed metadata only
when a concrete retrieval or product consumer needs it.

Cross-source resolution remains explicit. Inference may be recorded as
inference but must never be presented as a native provider field.

## Data design test

For every proposed field or type, ask:

1. Is this a source-backed fact the model may need to observe?
2. Is it dynamic game/event data or static catalog data?
3. Does it need a locator between calls, or is it simply document content?
4. Does putting it in Artifact reduce model-context pressure or merely duplicate
   another fact space?

If a value is only static ID -> name translation, prefer the catalog capability.
If it is only nested game content, prefer a plain value structure over a Ref.
