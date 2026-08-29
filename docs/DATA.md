# Data

## Data model direction

vNext does not require one universal DotaMind business schema for every source.
The target is source-backed capabilities with a thin composition envelope and
explicit provenance.

PandaScore, OpenDota, the local Valve catalog, and future providers may expose
different source vocabularies. DotaMind normalizes only what is necessary for a
stable capability contract, canonical Valve identity, bounds, errors, and large
result externalization.

## Source vocabularies

PandaScore currently exposes the esports hierarchy:

```text
League -> Series -> Tournament -> Match -> Game
```

This hierarchy is useful source knowledge, but it is a PandaScore vocabulary.
DotaMind should not require every future esports provider to map its own event
model into these five canonical entity classes.

Likewise, an OpenDota recorded-game response does not need to be transformed
into the same detailed DTO as a future game-data provider before either source
can participate in `game.detail`.

## Capability result envelope

Cross-capability composition needs only a small common envelope where useful:

```text
source
kind
locator
facts
```

- `source`: explicit provider/source attribution;
- `kind`: source-defined object kind;
- `locator`: opaque provider-scoped `SourceLocator` when the object must be
  referenced again;
- `facts`: bounded validated source-backed data that may remain source-shaped.

The envelope is not a canonical entity model. It exists to preserve provenance,
reusability, and generic composition.

## SourceLocator

A `SourceLocator` means "the same object in the same source".

Conceptually:

```text
SourceLocator
  source = pandascore
  kind = series
  value = opaque token
```

The token may internally resolve to a PandaScore/private provider ID, but the
raw provider ID is not exposed as agent language.

A provider-scoped locator does not claim cross-source identity. Two source
records with similar names are not the same entity merely because their text
matches.

This target makes most DotaMind `LeagueRef`, `SeriesRef`, `TournamentRef`,
`MatchRef`, and provider-backed `GameRef` normalization unnecessary. Those
current refs are migration-era contracts, not a requirement for the new
capability layer.

## Canonical Valve-native identity

Valve-defined identity is different from provider-private identity. It is the
shared Dota coordinate system used across game-data sources and the local
catalog.

Canonical Valve/Dota-native facts may be model-visible directly, including:

- `valve_match_id`
- Valve team ID
- Steam account ID
- `hero_id`
- `item_id`
- `ability_id`

These values do not need opaque DotaMind wrappers merely because they are IDs.

The PandaScore-to-Valve match resolver remains valuable because it establishes a
real cross-source Dota identity (`valve_match_id`) rather than inventing a
DotaMind identity namespace.

## Provider-private identifiers

Raw provider-private IDs remain below the model-facing boundary.

When an object needs to be revisited, convert the private ID into an opaque
`SourceLocator`. When it does not need to be revisited, omit the private ID from
the bounded model-facing facts.

Do not hash provider IDs into object-specific canonical refs merely to hide the
number; a provider-scoped locator is sufficient unless true cross-source
identity has been established.

## Source-shaped does not mean raw

Provider facts are still validated and sanitized before they become tool or
Artifact content.

Provider implementations own:

- upstream schema validation;
- source-specific null/missing semantics;
- bounded collections;
- transport/provider error handling;
- removal of transport-only fields;
- hiding raw provider-private IDs;
- explicit source attribution.

DotaMind should not add a second normalization layer whose only purpose is to
rename every provider field into a universal esports/game DTO.

## Provider roles today

Current roles are intentionally narrow:

- PandaScore implements esports discovery/navigation facts.
- The existing deterministic resolver maps a concrete PandaScore Game to a Valve
  match ID when evidence is sufficient.
- OpenDota implements detailed recorded-game facts for a resolved Valve match.
- The committed Valve catalog implements static hero/item/ability reference
  facts.

The current useful chain remains:

```text
PandaScore source object
  -> SourceLocator
  -> deterministic source-to-Valve resolution when needed
  -> valve_match_id
  -> OpenDota recorded-game facts
```

The model-facing tool boundary changes; the verified cross-source evidence rules
do not need to be discarded.

## Static catalog facts

All supported Dota game-data sources can share Valve-defined hero/item/ability
identity. The local catalog maps those IDs to static names/localization/reference
facts.

Keep static catalog data separate from dynamic game data:

```text
recorded game source
  -> hero_id / item_id / ability_id

local Valve catalog
  -> ID <-> static entity facts
```

The model uses `catalog.search` and batch `catalog.lookup` when it needs the
mapping. Do not require game-detail normalization to duplicate static names into
every stored result.

## Artifact data contract

Artifact is a stored source-backed document outside model context. Its primary
purpose is large-result externalization, not cross-provider canonical modeling.

A target document needs only the stable outer contract required for generic
storage and search, conceptually:

```text
Artifact document
  source
  kind
  canonical_ids?   # only truly shared IDs such as valve_match_id
  facts            # validated source-shaped document
```

For an OpenDota game-detail Artifact, `facts` may remain close to the verified
OpenDota source model instead of being rebuilt as a universal GameSummary object.
A future detail provider may store a different fact shape under the same generic
Artifact substrate.

Provider-private IDs are still excluded or encapsulated as opaque locators.
Valve-native IDs remain directly observable.

## Relationship between esports and game facts

PandaScore event context and OpenDota game detail are separate fact spaces.
DotaMind does not need to duplicate the entire PandaScore hierarchy inside every
OpenDota Artifact.

Their relationship can be retained through:

- the source locator used to find the game;
- the resolved `valve_match_id`;
- the bounded `game.detail` result;
- generic Artifact scope/membership if useful.

Only materialize cross-source context inside a stored document when a concrete
consumer requires it.

## Historical GameSummary schemas

GameSummary schema versions 3, 4, and 5 are frozen historical contracts. They
proved several useful ideas: deterministic ArtifactRef identity, bounded
external storage, generic read, and later generic grep.

They also accumulated a heavier provider-neutral construction path and catalog
enrichment that are no longer the target.

Do not silently mutate v3/v4/v5. Do not assume the replacement must be
`GameSummaryArtifactV6`. First prove the new `esports.search` and `game.detail`
capability boundaries and then define the minimum stable source-backed Artifact
contract actually needed.

## Artifact scope

`ArtifactScopeRef -> ArtifactRef[]` remains a generic membership concept.

The target scope key does not need to be a canonical DotaMind Series/Match Ref.
A capability may register a stored Artifact under an opaque source locator or
another explicit collection while `ArtifactScopeStore` stays unaware of source
semantics.

Current League/Series/Tournament/Match scope registrations are transitional and
should not drive further universal identity modeling.

## Provenance and uncertainty

Source attribution is first-class. Provider failures, ambiguity, incomplete
coverage, truncation, and cross-source resolution status must remain explicit.

If several sources later implement one capability, do not erase disagreement by
normalizing them into one answer in deterministic code. Return attributable
facts and let model reasoning compare them unless the product requires a
specific deterministic merge rule.

## Data design test

For every proposed schema or normalization step, ask:

1. Is this needed for a broad capability contract, or only to make two providers
   look artificially similar?
2. Is this a true canonical Valve/Dota identity or only a provider-scoped object?
3. Does the model need to locate this object again? If yes, is an opaque
   `SourceLocator` sufficient?
4. Is this dynamic source data or static catalog data?
5. Does storing/normalizing it reduce model-context pressure or merely create
   another application-owned representation?

Prefer source attribution and generic access over a universal object model when
the latter has no demonstrated consumer.
