# Data

## Direction

The current vNext model-facing path uses validated, closed capability outputs.
It does not require every data source to fit one universal DotaMind business
DTO, and generic Artifact externalization does not automatically retain raw
provider documents.

## Tool-response documents and observations

An Artifact stores the complete validated logical output of one tool, after the
tool registry has applied that tool's public output model. It is not an
automatic archive of the raw provider response: provider fields survive only
when the capability output preserves them. Credentials, authorization headers,
request tokens, and transport metadata are outside this model-facing output.

The model receives a complete response inline when it is small. A large logical
response is stored once and represented by a bounded observation plus a fresh
opaque reference. The reference is a continuation handle for that exact
document, not a domain identity.

## Identity

Canonical Dota facts such as game, hero, item, and ability identifiers may be
visible when a capability explicitly defines them. Source-private identifiers
remain evidence inside tool-response documents unless a future closed capability
declares a stable input. Names and relationships must come from collected
evidence; model knowledge is not an identity resolver.

## Artifact retrieval

`artifact.read` and `artifact.grep` are schema-neutral observation primitives.
They accept one exact temporary reference (or a future explicitly allowlisted
manual reference), never search a corpus, and never fetch a provider. If a
bounded preview supplies `_artifact_path`, use that path directly with
`artifact.read(mode="read")`.

## Provider boundary

Provider implementations own transport, source validation, source filtering,
pagination, and source-specific enrichment below a capability contract. Each
capability's public output model determines which validated facts and
normalizations reach the tool result. The generic Artifact layer preserves that
result exactly, but cannot recover fields omitted before output validation.

## Data design test

For each new field or normalization step, ask:

1. Is it required for a stable capability contract rather than artificial
   provider convergence?
2. Is it canonical Dota identity, provider-private detail, or a stored document
   observation?
3. Can generic Artifact retrieval preserve it without a new navigation object?
4. Does the change preserve missing-data, ambiguity, and source attribution?

Prefer complete logical tool responses plus bounded observations over a
universal object graph. If complete provider-source fidelity is required, it
must be added explicitly at the capability boundary before generic Artifact
externalization.

## Steam player and single-game observations

Player capability contracts use a Steam32 account ID (unsigned 32-bit) as
their lookup identity. It is not a PandaScore professional-player ID, and a
numeric value alone cannot prove which identity system supplied it. No
automatic cross-source identity association is implied. The implemented
`player.profile` and `player.recent_games` results identify `stratz` as their
source; `game.detail` identifies `opendota` and uses a Valve single-game ID,
but remains contract-only. Recent-game rows expose the source `MatchType.id` as
`valve_game_id` so it can be passed to the detail input. A one-match live
cross-check (`8960882635`) found matching STRATZ and OpenDota IDs, start time,
and duration; it is evidence for that sample, not a general integration
guarantee.

Profile `found=false` means the source response had no usable profile object;
it does not prove that the account does not exist or has never played Dota 2.
An empty recent-game list is valid, and a short list is not evidence that all
history was returned. Recent games request `take=limit`, explicit `DESC` date
ordering, and `playerList=SINGLE`; local sorting is applied only after that
provider-selected sample is received. The target player's Steam32 ID is checked
in both the outer player and returned player row. An empty player-row list keeps
the match record but provides no basis for that player's performance. Null
statistics remain null; zero and false remain distinct. Profile and match
business data are retained as JSON objects so unknown returned source fields,
nested arrays, nulls, zeroes, and booleans survive validation. This JSON
container does not itself validate every provider-specific business meaning.
Both STRATZ tools register only when a token is configured. A live query for
one participant returned 20 rows with nonincreasing raw timestamps under
`orderBy=DESC`, and each row contained only the requested account. Match
`8960882635` predates the oldest row in that bounded sample and was not
returned. This verifies one account/query sample, not general provider
availability or universal ordering behavior.
