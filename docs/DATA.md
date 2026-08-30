# Data

## Direction

vNext keeps provider facts source-backed.  It does not require every esports or
game-data source to fit one DotaMind business DTO.

The stable capability envelope is deliberately small:

```text
source
kind
artifact_ref
facts
```

- `source` identifies the provider;
- `kind` is the provider-defined object type exposed by the capability;
- `artifact_ref` addresses the complete stored document;
- `facts` is a bounded observation of that document.

The envelope preserves provenance and lets capabilities compose.  It is not a
canonical League, Series, Match, Team, or Player model.

## Esports discovery vocabulary

PandaScore has a richer source hierarchy, including games.  The public
`esports.search` contract intentionally exposes only:

```text
league | series | tournament | match | team | player
```

`kind` is required.  `game` is not a discovery kind: recorded game detail is
obtained through `game.detail` after a canonical Valve match ID is available.

`teams` is a Match-only constraint.  It resolves each supplied team name to an
exact PandaScore team identity, then returns only matches containing every
resolved team.  It is not a replacement for `kind="team"`.

`time_scope` is available only for Series, Tournament, and Match.  Its values
are `upcoming`, `running`, and `past`; provider pages are scanned, filtering and
ordering are deterministic, and `truncated` remains explicit when the bounded
scan cannot prove completeness.

## Source document versus observation

An Artifact stores a complete validated, provider-shaped business document:

```text
SourceDocumentArtifact
  source
  kind
  facts       # complete validated provider document
```

The document excludes HTTP headers, credentials, request tokens, and pagination
envelopes.  It retains provider business fields, including newly added fields
that the source model allows but DotaMind does not yet consume.

The model normally receives only `facts`, a generic bounded observation.  It
can inspect the retained document later with `artifact.read` or
`artifact.grep`.  A provider-private ID may be evidence inside that document;
it is never a supported tool input.

## Identity

Provider identity and Dota identity are different.

- Provider-private IDs identify a record only inside that provider and stay
  behind the Adapter/Provider boundary.
- The source identity is used internally to produce a stable ArtifactRef for
  the same source object.  It is not model-facing navigation syntax.
- Valve-native facts, including `valve_match_id`, `hero_id`, `item_id`, and
  `ability_id`, are canonical Dota facts and may be visible directly.

For a PandaScore Match, each retained game is enriched with:

```text
valve_game_id: int | null
resolution: resolved | not_found | ambiguous | …
```

The existing deterministic resolver establishes this relationship.  It does not
invent a DotaMind-wide replacement ID when resolution is unavailable.

## Provider roles

- PandaScore implements esports discovery and source documents.
- The PandaScore-to-Valve resolver establishes concrete recorded-game identity
  when its evidence supports it.
- OpenDota implements detailed recorded-game facts for a resolved
  `valve_match_id`.
- The local Valve catalog provides static hero, item, and ability facts.

Keep static catalog facts separate from dynamic source documents.  Use
`catalog.search` and `catalog.lookup` when names or localization are needed;
do not copy them into every recorded-game Artifact.

## Data design test

For each new field or normalization step, ask:

1. Is it needed for a stable capability contract, rather than to make providers
   look artificially alike?
2. Is it a canonical Valve fact, a provider-private detail, or merely a stored
   document observation?
3. Can generic Artifact retrieval preserve the fact without a new navigation
   object or tool?
4. Does the change preserve missing-data, ambiguity, and provider attribution?

Prefer retained source documents plus bounded observations over a universal
object graph.
