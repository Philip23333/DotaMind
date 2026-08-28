# Artifact System

## Status

This document owns the vNext target contract for artifacts, artifact storage,
and generic artifact exploration. The current code still contains the heavier
`GameConstructionContext` / construction-Ref / catalog-enrichment pipeline; that
implementation is transitional. Where older architecture text describes that
pipeline as the target, this document supersedes it.

The simplification is intentionally based on the original reason artifacts were
introduced: large tool results must not be copied wholesale into model context.

## Why Artifact exists

An Artifact exists to externalize a complete, potentially large tool result
outside model context while keeping that result searchable and readable by the
model.

The core flow is:

```text
Tool / application capability
  -> collect complete source-backed facts
  -> light canonical normalization
  -> store JSON-like document
  -> return ArtifactRef plus a bounded result

Model
  -> artifact.grep when breadth discovery is useful
  -> artifact.read when deeper evidence is useful
```

Artifact is not a second domain model, an object graph, or a requirement to
create a typed reference for every Dota concept inside a game.

## Three fact spaces

DotaMind keeps three fact spaces deliberately separate.

### 1. Esports navigation facts

PandaScore is the current navigation and event-context source:

```text
League -> Series -> Tournament -> Match -> Game
```

Navigation refs exist only where the model must carry a locator between calls,
for example `SeriesRef`, `MatchRef`, or `GameRef`. Provider-private PandaScore
IDs remain below the domain boundary.

### 2. Game facts

After a PandaScore Game is resolved to a canonical Valve match ID, OpenDota is
the current game-detail source. The Game Artifact stores recorded game facts as
canonical JSON-like data.

Valve-native identities remain ordinary scalar facts in the document:

- `valve_match_id`
- `valve_team_id`
- `steam_account_id`
- `hero_id`
- `item_id`
- `ability_id`

They do not require construction-layer `HeroRef`, `ItemRef`, `AbilityUpgradeRef`,
`ItemSlotRef`, `PurchaseEventRef`, or `DraftEventRef` wrappers.

### 3. Static Dota catalog facts

The committed Valve catalog owns the stable mapping between Valve-native IDs
and static entity facts such as names and localization.

Artifact production should not duplicate those static facts into every game
document by default. The model receives small catalog capabilities instead:

- `catalog.search`: user-facing name/alias -> candidate Valve-native IDs
- `catalog.lookup`: batch Valve-native IDs -> static catalog facts

Catalog lookup is deterministic, local, bounded, and independent from Artifact
production.

## Artifact definition

A canonical Artifact is a stable, provider-neutral, JSON-like document that
preserves the complete facts needed for later model exploration without placing
the full payload in context by default.

A Game Artifact should look conceptually like:

```text
GameSummaryArtifact
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
    radiant
      valve_team_id
      name
      score
    dire
      valve_team_id
      name
      score
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
    bans[] { order, side, hero_id }
```

Readable PandaScore event context may be embedded because it tells the model
what game the document represents. PandaScore resource IDs and DotaMind
navigation refs do not enter the Artifact.

## Ref rule

A `Ref` is a locator, not a generic wrapper around an ID or event structure.

Create a Ref only when another capability may need to receive it later to
locate the same object. Typical retained refs are:

- `SeriesRef`, `MatchRef`, `GameRef` and other necessary navigation locators
- `TeamRef` and `PlayerRef` where cross-capability navigation requires them
- `ArtifactRef`

Do not create a Ref merely because a value has an identity field. A hero ID,
item ID, ability ID, inventory slot, purchase event, draft event, or ability
upgrade inside an Artifact is content, not a locator.

Provider entity -> canonical navigation Ref construction must have one owner and
one deterministic rule. Different services must not invent their own hash
recipes for the same source entity.

## ArtifactRef

`ArtifactRef` is the stable locator for a stored Artifact. For GameSummary it is
derived from canonical Valve game identity plus schema version, for example:

```text
game_summary:6:8960577698
```

Artifact identity is independent from PandaScore IDs and from catalog names.

## Production target

The target production path is deliberately short:

```text
PandaScore navigation
  -> resolve concrete Game
  -> Valve match_id

OpenDota game detail
  + already-known readable PandaScore event context
  -> thin canonical normalization
  -> GameSummaryArtifact
  -> ArtifactStore.put
  -> ArtifactRef
```

The normalization layer may rename fields, preserve missing-data semantics,
normalize side/status values, validate canonical Valve identity, and combine
source-backed PandaScore event context with OpenDota game facts. It should not
build a parallel graph of construction refs or translate every Valve-native ID
through the catalog.

A capability that obtains a large result may store the complete Artifact before
returning success. The model receives a bounded tool result and a locator rather
than the complete document. A separate model-facing `artifact.produce` tool is
not required for ordinary match-detail flow.

## Retrieval and discovery

Artifacts form a structured corpus outside model context.

- `artifact.search` is exact Artifact availability lookup where useful.
- `artifact.grep` is schema-neutral breadth discovery over serialized scalar
  content and returns `ArtifactRef`, structural path, and bounded preview.
- `artifact.read` is schema-neutral bounded depth retrieval by `ArtifactRef` and
  structural path.

Search and read do not fetch providers or create missing Artifacts. The model
chooses when they are useful; they are not a mandatory workflow.

The search implementation may later move from scanning to a generic index, but
that index must remain schema-neutral. Do not add one search adapter per Artifact
type or scenario-specific tools such as `artifact.find_player_hero_games`.

## Scope

`ArtifactScopeStore` remains a generic corpus-membership mechanism:

```text
ArtifactScopeRef -> ArtifactRef[]
```

Search does not know whether a scope represents a League, Series, Tournament,
Match, temporary collection, or another future grouping.

Known PandaScore navigation ancestry may register an Artifact after the Artifact
write succeeds. Membership is never inferred by parsing Artifact content.
Scoped search covers only currently materialized Artifacts and must preserve
`materialized_only` semantics.

Because scope identity depends on navigation refs, provider entity -> Domain Ref
construction must be consistent before those refs are trusted as scope keys.

## Catalog capabilities

The target catalog surface is intentionally small.

`catalog.search` resolves human-facing text to static Dota catalog candidates.
Example inputs include `Earth Spirit`, `土猫`, or an item name. It may accept a
bounded type filter such as hero/item/ability.

`catalog.lookup` accepts bounded batches of Valve-native IDs, for example:

```json
{
  "heroes": [107],
  "items": [50, 63],
  "abilities": [5601, 5602]
}
```

and returns static catalog facts such as canonical English and Chinese names.
It performs no provider call and no gameplay interpretation.

This keeps responsibilities orthogonal:

```text
Artifact = dynamic recorded game facts
Catalog  = static Valve ID -> entity facts
Model    = combines both when useful
```

## Schema evolution

GameSummary schema versions 3, 4, and 5 remain frozen historical contracts.
They are not silently mutated.

The simplified representation should be introduced as a new schema version
(currently expected to be v6) because removing duplicated catalog names and
construction-driven shapes changes the Artifact contract materially.

The v6 design should be source-backed and intentionally minimal. Do not add new
coverage, provenance, completeness, timeline, analytics, or indexing fields
unless an observed consumer requires them and the source semantics are verified.

## Migration route

The current code should move to the simplified target in small commits.

### Commit A — stabilize navigation identity

Fix the existing canonical navigation identity defect before relying on scope:

- one PandaScore entity -> one Domain Ref construction rule
- eliminate the current divergent SeriesRef recipes
- keep the change limited to navigation identity and reverse mapping
- do not introduce a generic identity framework

### Commit B — add minimal catalog tools

Expose the existing local catalog through small model-facing capabilities:

- `catalog.search`
- `catalog.lookup` with bounded batch inputs

Do not change Artifact schema in this commit.

### Commit C — define simplified GameSummary v6

Add a new frozen schema contract that:

- preserves readable PandaScore event context
- preserves OpenDota/Valve game facts
- stores Valve-native hero/item/ability IDs directly
- removes duplicated catalog-localized names from dynamic game facts
- contains no provider-private IDs and no construction refs

Schema and tests only.

### Commit D — replace heavy construction with thin normalization

Create the smallest mapping from verified provider models plus event context to
v6. Avoid a second domain object graph. Plain typed event/value structures are
allowed where they protect field semantics, but they are content models rather
than `Ref` types.

Do not delete the old v4/v5 path until v6 production is proven.

### Commit E — switch production to v6

Change GameSummary production to:

```text
Valve match_id
  -> OpenDota fetch
  -> thin normalization + PandaScore event context
  -> v6 document
  -> ArtifactStore
  -> ArtifactRef
```

Keep automatic production on the successful match-detail path. Keep
`artifact.grep` and `artifact.read` contracts generic and unchanged except for
schema-version compatibility where required.

### Commit F — delete obsolete construction machinery

After v6 fixture and product-path tests pass, remove code that exists only for
the old heavy pipeline, including construction-only Ref wrappers, catalog
resolvers used solely to enrich dynamic Artifacts, and builders or contexts no
longer on the production path.

Delete rather than preserve compatibility shims when no retained consumer uses
them.

### Commit G — real model acceptance

Validate representative questions through the actual tool surface. One required
case is a tournament-scoped player/hero question where the model must compose:

```text
navigation
-> catalog.search(name -> hero_id)
-> artifact.grep / artifact.read
-> catalog.lookup(item_id / ability_id -> names)
-> answer
```

The acceptance target is not a fixed call sequence. It is that the available
small capabilities are sufficient and the runtime does not encode the scenario.

## Non-goals

The simplification does not add:

- one Ref type per Dota value
- an Artifact object graph or entity registry
- provider-private IDs in Artifacts
- catalog-name duplication as a requirement for dynamic game documents
- semantic/vector search
- scenario-specific Artifact search helpers
- automatic provider fetch from `artifact.grep` or `artifact.read`
- a model-facing produce tool for normal match-detail production
- provisional Ref hierarchies or a generalized identity framework

## Acceptance

The migration is complete when:

1. a large resolved match result can be stored without entering model context in
   full;
2. the resulting canonical Game document is understandable through generic
   `grep/read` plus the small catalog capabilities;
3. Artifact production no longer requires the construction-Ref/catalog-
   enrichment graph;
4. provider-private IDs remain below the Artifact boundary;
5. Valve-native IDs remain directly observable facts;
6. navigation refs remain few, stable, and reusable as locators;
7. real model evals can compose navigation, Artifact, and catalog capabilities
   without scenario-specific orchestration.
