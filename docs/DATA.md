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

Optional web search is different from the closed esports DTOs: `web.search`
uses the discovered Tavily input schema and preserves returned source material
instead of mapping it into a cross-provider business model. The result records
the service and remote tool identity, retrieval time, structured content when
available, and ordered content blocks. Parsed JSON from a text block is
additional to—not a replacement for—the original text. Credentials and
transport headers never enter the result. Unsupported binary content is not
embedded, and a resource link is not fetched automatically. The generic
Artifact layer remains the only storage path for oversized results.

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

## Hero guide data contract (confirmed plan; not implemented)

The guide cache is a persistent source-data store owned by the guide capability;
it is not the temporary session Artifact store. For a requested `(hero_id,
position)`, the query DTO is a view containing `pub_guides[]` and
`pro_examples[]`. It retains provenance and whatever sample count, patch/version,
statistics window, source update time, and local retrieval time the source
actually provides. Missing source fields remain absent/unknown rather than being
filled with defaults. Pub and Pro refresh status and timestamps are independent.

Pub is the primary guide source. The parser may project available source build
facts such as starting items, item progression and alternatives, skill sequence,
talents, and neutral-item statistics into guide entries. Candidate item builds
and skill sequences remain independently sourced; the DTO does not pair them or
claim that separate arrays describe one combined build. Pro data contributes
only practical examples taken from `recent_matches`; its aggregate build
statistics are not converted into a recommended route. No fixed number of Pub
guides or Pro examples is manufactured.

The source skill sequence is retained at its supplied length and order. The
current Sven Pub sample contains ten skill IDs, and the Pro response exposes a
ten-entry `abilities.skill_order`; neither representation proves a mapping to
every hero level. Equipment, skill, facet, and neutral-item identifiers remain
source values unless a separate exact catalog capability resolves them.

For item timing, the DTO groups available progression facts around the
30-minute boundary. Where the source supplies `avg_minute`, expose it as the
source's average-minute statistic; do not label it a median or calculate a
median from grouped values. If that statistic is absent, leave the time unknown.
The source response does not by itself establish a universal definition for
`pr`, `pick_rate`, nested `win_rate`, `avg_minute`, or `std_minute`. Preserve
values with their source path and associated counts; do not compare rates across
different paths or infer causal item impact.

For each refresh partition, retain the exact original response bytes and the
complete parsed result, including unknown source fields and heterogeneous or
null values. The DTO is a query view, not a replacement for those source
records. Publish a successfully fetched and parsed replacement atomically. On
fetch or parse failure, retain the last successful value and record the failed
attempt separately. A valid empty response is a successful, explicit empty
state, distinct from missing data and failure.

### D2PT source and statistic boundary

The one-time Sven probe verified one non-empty JSON row from each tested
endpoint. The Pub row declared a 14-day configured window and patch label
`7.41f`; the Pro row returned 80 aggregate matches and five `recent_matches`,
without an explicit patch or full statistics window. These observations are
sample facts, not universal parser guarantees. See
[`reference/d2pt.md`](reference/d2pt.md) for the tested shapes, values, and
semantic limitations.

## Steam player and single-game observations

Player capability contracts use a Steam32 account ID (unsigned 32-bit) as
their lookup identity. It is not a PandaScore professional-player ID, and a
numeric value alone cannot prove which identity system supplied it. No
automatic cross-source identity association is implied. The implemented
`player.profile` and `player.recent_games` results identify `stratz` as their
source; `game.detail` identifies `opendota` and uses a Valve single-game ID.
Recent-game rows expose the source `MatchType.id` as
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
`game.detail` registers only when `DOTAMIND_OPENDOTA_ENABLED` is true. It
preserves the full validated OpenDota object, including unknown JSON extensions,
null values, zeroes, and booleans. The returned positive `match_id` must equal
the requested Valve ID; known fields are type-checked when present. Anonymous
player rows and absent optional or parsed fields are valid. Missing process
data does not prove an event did not occur, and the lookup does not trigger
replay parsing. Tests use HTTP mocks. The earlier live cross-source check of
`8960882635` is a single-match observation, not live verification of this new
client.

## Account-to-game evidence and local catalog labels

The user-facing path composes existing observations: a Steam32 ID selects a
STRATZ recent-games result; a chosen `valve_game_id` selects one OpenDota game;
the requested player's row is identified only by exact `account_id`. The
conversation history and generic Artifact references retain the list and large
detail response for follow-ups such as “the second game”; there is no separate
match-keyed memory store, forced profile lookup, or automatic detail fetch for
all listed games. If the earlier list cannot be recovered, the agent must ask
instead of guessing which match an ordinal refers to.

`catalog.lookup` reads the bundled Valve hero/item snapshot by exact IDs and
returns display names with snapshot-version metadata. These labels remain
separate from provider match facts and do not rewrite OpenDota's `data`. Unknown
IDs remain visible as unknown. Match statistics support only the conclusions
they encode; missing timeline, purchase, or identity data remains unknown and
must not be interpreted as proof that an event did not happen.
