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
`player.profile` result identifies `stratz` as its source; `player.recent_games`
is a contract-only STRATZ capability. `game.detail` identifies `opendota` and
uses a Valve single-game ID, but remains contract-only. That ID is designed to
pass from a future recent-game row into the detail input.

Profile `found=false` means the source response had no usable profile object;
it does not prove that the account does not exist or has never played Dota 2.
An empty recent-game list is valid, and a short list is not evidence that all
history was returned. Recent ordering must be verified against provider
semantics by a future adapter. Profile and game business data are retained as
JSON objects so currently unknown source fields, nested arrays, `null`, zero,
and boolean values survive validation. This JSON container does not itself
validate provider-specific business meaning. `player.profile` is registered
only when a STRATZ token is configured. Its query and field availability have
not yet been verified against the live API; the other two capabilities are not
registered.
