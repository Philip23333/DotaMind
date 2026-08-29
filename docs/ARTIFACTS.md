# Artifact System

## Status

This document owns the vNext target contract for large-result externalization,
Artifact storage, and generic Artifact exploration.

The current code still contains the heavier `GameConstructionContext` /
construction-Ref / catalog-enrichment pipeline and a provider-neutral
`GameSummaryArtifact` production path. Those are transitional. The target no
longer requires different detail providers to fit one universal GameSummary
schema before their data can be stored or explored.

## Why Artifact exists

Artifact exists for one primary reason:

> complete tool/provider results can be too large to place directly in model
> context.

The target flow is:

```text
model-facing capability
  -> provider implementation obtains complete validated source document
  -> store the document outside context
  -> return generic bounded observation + ArtifactRef

model
  -> artifact.grep for breadth
  -> artifact.read for depth
```

Artifact is therefore a document-storage/retrieval boundary, not a second Dota
business model.

## Source-backed document model

A stored Artifact should have only the stable outer structure required for
retention, provenance, identity, and generic exploration.

Conceptually:

```text
Artifact
  source
  kind
  canonical_ids?
  facts
```

- `source` identifies the source implementation such as `pandascore` or
  `opendota`;
- `kind` identifies the source/document kind;
- `canonical_ids` contains only genuinely shared identities when useful, such as
  `valve_match_id`;
- `facts` is the complete validated provider-shaped business document.

The complete Artifact is not the same thing as model-facing `facts` returned by
a capability. A capability derives a generic bounded observation from this
source document and returns that observation together with the `ArtifactRef`.
The observation is structural and provider-blind; it is not a hand-authored
`MatchPreview`/`SeriesPreview` DTO.

"Source-shaped" does not mean raw transport payload. Headers, credentials,
pagination envelopes, transport-only metadata, invalid types, and unbounded
transport data remain below the provider boundary. Additional provider business
fields should be retained when validation can safely carry them.

Provider-private IDs may remain inside a stored source document as source-local
evidence. They are omitted from bounded capability observations and are not a
supported cross-tool identity language; the model navigates provider objects
with `SourceLocator`.

## No universal detail schema requirement

The Artifact Store and `artifact.grep/read` do not need OpenDota and a future
game-detail provider to expose the same fields.

Prefer:

```text
PandaScore fixture
  -> source-backed Artifact A

OpenDota detail
  -> source-backed Artifact B

Future detail source
  -> source-backed Artifact C

artifact.grep/read
  -> works on all JSON-like documents
```

over:

```text
provider A ----\
provider B ----- -> UnifiedGameOrMatchDTO -> Artifact
provider C ----/
```

A shared business schema should be introduced only when a concrete deterministic
consumer actually requires one.

## Capability relationship

Artifact production is subordinate to the capability that obtained the result.

Current target examples:

```text
esports.search
  -> PandaScore implementation
  -> validated PandaScore source object
  -> source_document Artifact
  -> bounded structural observation + SourceLocator + ArtifactRef

game.detail
  -> resolve valve_match_id when needed
  -> OpenDota implementation
  -> large complete detail stored as Artifact
  -> bounded result + ArtifactRef
```

The model does not need a normal `artifact.produce` tool. Production happens as
part of a capability's successful data path when externalization is useful.

## SourceLocator and ArtifactRef

`SourceLocator` and `ArtifactRef` solve different problems.

```text
SourceLocator
  = revisit/navigate one object inside one provider/source

ArtifactRef
  = revisit one stored document inside DotaMind's Artifact corpus
```

A source locator is provider-scoped and opaque. An ArtifactRef is storage-scoped
and versioned according to the stored document contract.

A record may carry both. For example, an `esports.search` match record can use
its `SourceLocator` to navigate to games and its `ArtifactRef` to inspect the
complete PandaScore fixture with generic read/grep.

Neither needs to become a canonical DotaMind League/Series/Match identity.

## Bounded observation policy

`esports.search` does not define a separate preview schema for each PandaScore
object. It derives a generic observation from the stored source document.

The initial policy is intentionally simple:

- omit provider-private identity keys from the model-facing observation;
- retain bounded top-level scalar values;
- represent nested objects and collections structurally (for example object
  field count or collection item count);
- bound top-level field count and long strings;
- keep the complete source document behind `ArtifactRef`.

If later evidence requires a different generic bound, change the bounding policy
rather than adding `MatchPreview`, `SeriesPreview`, or scenario-specific fields.

## Canonical Valve identities

Valve-native identities may cross source boundaries directly:

- `valve_match_id`
- Valve team ID
- Steam account ID
- `hero_id`
- `item_id`
- `ability_id`

These are Dota-native facts, not DotaMind wrappers.

A Game-detail Artifact may preserve them directly inside `facts` or the small
`canonical_ids` envelope. They do not require `HeroRef`, `ItemRef`,
`AbilityUpgradeRef`, `ItemSlotRef`, `PurchaseEventRef`, or `DraftEventRef` merely
to enter the document.

## Static catalog separation

Static Valve ID -> entity translation is a separate fact space.

```text
dynamic source-backed Artifact
  -> hero_id / item_id / ability_id

local Valve catalog
  -> catalog.search
  -> catalog.lookup
  -> names/localization/reference facts
```

Do not require Artifact production to duplicate catalog names into every stored
game result.

## Relationship between PandaScore and OpenDota

PandaScore esports/event facts and OpenDota recorded-game facts do not need to be
merged into one universal Artifact.

The target relationship can be expressed through:

```text
PandaScore SourceLocator + PandaScore source-document ArtifactRef
  -> deterministic source-to-Valve resolution when game detail is needed
  -> valve_match_id
  -> OpenDota detail Artifact
```

Readable PandaScore hierarchy/context is copied into an OpenDota detail Artifact
only if a concrete consumer demonstrates that storing the duplication is
valuable.

## Artifact exploration

Artifacts form a generic JSON-like corpus outside model context.

### `artifact.search`

Exact availability lookup where useful. It never fetches providers or creates a
missing Artifact. The current exact-search surface remains GameSummary/Valve-ID
oriented during migration; an ArtifactRef returned directly by another
capability does not need to pass through `artifact.search`.

### `artifact.grep`

Schema-neutral breadth discovery over serialized scalar content. It returns:

```text
ArtifactRef
structural path
bounded preview
```

It does not know source-specific or gameplay-specific dimensions.

### `artifact.read`

Bounded depth retrieval by exact ArtifactRef plus structural path. It does not
interpret provider semantics. A source-document Artifact keeps complete provider
facts under its `facts` field.

Search/read are independent observation primitives; no fixed grep-then-read
workflow is required.

## Scope

`ArtifactScopeStore` remains a generic membership mechanism:

```text
ArtifactScopeRef -> ArtifactRef[]
```

Scope must not depend on a universal esports ontology.

A capability may register an Artifact under an already-known opaque
`SourceLocator`-derived scope or another explicit collection. The scope store
itself does not know whether the locator represents a PandaScore Series, Match,
future-provider event, or another grouping.

The current League/Series/Tournament/Match Ref registrations are transitional.
Do not expand that hierarchy as the target solution.

## Historical GameSummary artifacts

GameSummary schema versions 3, 4, and 5 remain frozen historical contracts.
They proved useful infrastructure:

- large result storage outside model context;
- deterministic ArtifactRef identity;
- memory/Redis retention;
- bounded `artifact.read`;
- generic `artifact.grep`;
- basic scope membership.

They also accumulated a heavier provider-neutral construction graph and catalog
enrichment that are no longer required by the target architecture.

Do not silently mutate v3/v4/v5.

The replacement does **not** need to be called `GameSummaryArtifactV6`. Source
backed `source_document` artifacts are the generic substrate; game-detail
migration can use the same principle without defining another universal schema.

## Migration route

### Commit A — introduce source-backed capability contracts

Define the minimum shared contracts needed by the new tool layer:

- `SourceLocator`;
- thin source-attributed result envelope;
- target `esports.search` contract;
- no generic provider registry/framework yet.

### Commit B — migrate esports discovery to `esports.search`

Cover current use cases of `series.search`, `series.list_matches`, and
`matches.search` using `within: SourceLocator` for continued source-local
navigation. After focused and real-model acceptance, remove obsolete
ontology-shaped registrations.

The PandaScore implementation externalizes each discovered source object as a
`source_document` Artifact and derives model-facing `facts` generically from that
same document. Do not restore manually selected Match/Series preview DTOs.

### Commit C — introduce `game.detail`

Create the model-facing detail capability using existing deterministic
PandaScore-to-Valve resolution and the OpenDota detail implementation.

Accept a source locator and/or canonical `valve_match_id` according to the
smallest contract required by evals. Return bounded source-attributed facts and
externalize the complete large detail result as an Artifact.

After acceptance, retire `matches.get_detail` as the model-facing detail tool.

### Commit D — add minimal Catalog capabilities

Expose the local Valve catalog through `catalog.search` and bounded batch
`catalog.lookup`. Keep catalog mapping outside dynamic Artifact production.

### Commit E — simplify remaining Artifact production

Replace the old construction-Ref/catalog-enrichment graph with direct storage of
validated source-backed detail documents plus only necessary stable envelope
metadata and true canonical Valve IDs.

### Commit F — remove obsolete normalization machinery

Delete construction-only Ref types, builders, resolvers, canonical navigation
DTOs, and compatibility code that no accepted capability still uses.

### Commit G — real model acceptance and second-source readiness

Validate representative questions through the small capability surface. A future
second provider should be addable as another implementation of `esports.search`
or `game.detail` without first changing every source record into a universal DTO.

## Non-goals

The target does not add:

- one model-facing tool per provider endpoint;
- one tool per League/Series/Tournament/Match type;
- a provider-neutral esports ontology as a prerequisite for search;
- a universal game-detail DTO as a prerequisite for storage;
- provider-private raw IDs as capability navigation inputs;
- one Ref type per nested Dota value;
- catalog-name duplication as a requirement for stored game data;
- provider-specific Artifact grep/read adapters;
- semantic/vector search before demonstrated need;
- automatic provider fetch from Artifact search/read;
- a provider plugin/routing framework before a second implementation exists.

## Acceptance

The migration is complete when:

1. the model uses a small capability surface rather than PandaScore ontology
   tools;
2. PandaScore can satisfy esports search without becoming a universal Domain
   hierarchy;
3. discovered PandaScore source objects retain complete validated source
   documents outside model context and expose only generic bounded observations;
4. OpenDota can satisfy game detail without being normalized into a synthetic
   cross-provider DTO;
5. large provider results remain generically grep/read-able;
6. source attribution and provider failures stay explicit;
7. Valve-native IDs remain directly observable and Catalog remains separate;
8. a second provider can join an existing capability with source-attributed
   documents instead of forcing a rewrite of every source schema.
