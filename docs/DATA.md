# Data

## Direction

vNext keeps provider facts source-backed.  It does not require every esports or
game-data source to fit one DotaMind business DTO.

The esports discovery capability envelope stays deliberately small:

```text
source
kind
artifact_ref
facts
```

- `source` identifies the provider;
- `kind` is DotaMind's esports capability vocabulary; each provider maps its
  source entities into it;
- `artifact_ref` addresses the complete stored document;
- `facts` is a bounded observation of that document.

The envelope preserves provenance and lets capabilities compose.  It is not a
canonical League, Series, Match, Team, or Player model. The removed unified
`esports.search` contract must not be rebuilt as the new schema.

## Esports discovery vocabulary

PandaScore has a richer source hierarchy, including games.  The future
discovery capability must decide its own model-facing vocabulary from the
current endpoint allowlist; `game` is not a discovery kind: recorded game
detail is obtained through `game.detail` after a canonical Valve game ID is
available.

Preserved source semantics for the redesign:

- exact Team identity derives from the complete PandaScore Team corpus (never a
  partial corpus), with a TTL-bounded identity index for repeated constraints;
- dedicated PandaScore lifecycle endpoints select the lifecycle; the Provider
  must not reject their entities by a second status filter (Team-to-Matches is
  the local-filtering exception);
- `truncated` remains explicit when a bounded scan cannot prove completeness;
- capability-level text discovery runs over complete provider business facts,
  not as an alias for PandaScore `search[name]`; provider-native name search may
  be used only when it cannot exclude a document that would match the wider
  contract.

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

The model receives the complete response inline when it is small. For a large
logical tool response it receives a generic bounded observation and a temporary
session ref, then inspects that one response with `artifact.read` or
`artifact.grep`. A provider-private ID may be evidence inside a response; it is
never a supported tool input.

Large `esports.search` responses store the complete source-shaped logical page
at the Artifact root (`resource`, `scope`, `rows`, `has_more`), not under query
or result envelopes. Preview pointers therefore use paths such as
`rows.0.matches`.

## Identity

Provider identity and Dota identity are different.

- Provider-private IDs identify a record only inside that provider and stay
  behind the Adapter/Provider boundary.
- Valve-native facts, including `valve_game_id`, `hero_id`, `item_id`, and
  `ability_id`, are canonical Dota facts and may be visible directly.

For a PandaScore Match, each retained game is enriched with:

```text
valve_game_id: int | null
resolution: resolved | not_found | ambiguous | …
```

The existing deterministic resolver establishes this relationship.  It does not
invent a DotaMind-wide replacement ID when resolution is unavailable.
For one discovery invocation, the resolver shares its OpenDota evidence across
selected Matches while preserving the same per-game deterministic status or
`unavailable` outcome in each stored source document.

## Recorded-game detail documents

`game.detail` uses canonical `valve_game_id` directly. Its complete logical
response contains the validated OpenDota-shaped facts; it is externalized only
when large with a fresh `artifact:tool:*` reference. The source model validates
only the returned `match_id` identity and retains allowed unknown top-level and
nested business facts; it does not turn the response into a GameSummary DTO.

The immediate capability result exposes the canonical Valve ID and a bounded
observation. Generic Artifact retrieval exposes the complete document later.

## Provider roles

- PandaScore implements esports discovery and source documents for the future
  discovery seam; its HTTP client and endpoint allowlist are preserved.
- The PandaScore-to-Valve resolver establishes concrete recorded-game identity
  when its evidence supports it.
- OpenDota implements detailed recorded-game facts for a canonical
  `valve_game_id`.
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
