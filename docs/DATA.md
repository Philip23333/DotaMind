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

Code-internal `EntityNameResolver` resolves an explicitly supplied batch of hero,
item, or ability IDs against the injected local `DotaCatalogRepository`. The
business capability locates ID fields and retains the original IDs and source
data; the shared component does not scan or infer fields. It adds Valve catalog
names as local enrichment with the catalog snapshot version. A missing ID
remains in the result with `unknown` status and empty names, without failing the
business result. The resolver is not a model tool. `hero.guide` uses it after
section projection and preserves original IDs, source labels, and source fields.
Names are added to the query result and generic Artifact output; they are not
written into Redis snapshots. Old snapshots remain readable because enrichment
DTO fields have defaults. `game.detail` has not yet integrated the resolver.

The Valve catalog sync also retains positive ability IDs from the bilingual
ability list when hero detail responses do not define them, including records
whose internal names use `special_bonus_`. Hero detail records remain
authoritative for duplicate IDs; supplemental records have no inferred hero
association. These supplements retain their validated ID/internal name and
renderable bilingual display names; they do not extend hero ability lists,
talent trees, or the existing talent-value candidate set. Missing or unresolved
localized display names stay empty, while malformed identity and other required
source errors still fail synchronization. Ability ID zero remains excluded.
Image downloads are best effort: failures are
reported, successful and previously available files remain usable, and the
catalog snapshot can still be published. Chat visual metadata is created only
when the corresponding local image file exists; catalog name lookup does not
depend on images.

## Shared data storage and update target

The current entity catalog is loaded from files bundled with the API code.
`hero.guide` currently reads Redis snapshots, and its operator refresh CLI writes
those snapshots. The persistent catalog and guide stores are implemented, as
are manual initialization and Redis-import commands, but neither command has
been run against an operational data root or Redis cache. The API read path and
regular refresh path remain unchanged. The conceptual data areas are `catalog`,
`patches`, `images`, and `guides`.

### Catalog snapshot publication

The entity catalog keeps its existing five JSON documents and their field
structures:

```text
manifest.json
dota2_heroes.json
dota2_abilities.json
dota2_items.json
sync_audit.json
```

The standalone `CatalogSnapshotStore` is implemented. Given a caller-supplied
data root and source directory, it copies these five files byte-for-byte into
`catalog/snapshots/<revision>/`, validates the copied models, catalog relations,
and sync audit, then atomically replaces `catalog/current.json`. The pointer's
UUID-hex revision is independent of the Dota patch and catalog schema versions.
Failed publication leaves the current pointer unchanged; successful snapshot
directories are retained. The store loads the pointed revision into a
`DotaCatalogRepository`, and the manual `init-catalog` command can initialize it
under a caller-supplied data root. It is not connected to API reads or a unified
updater, and no operational data root has been initialized. API hot reload
remains pending. Offline tests do not establish power-loss recovery.

The eventual updater must validate the complete set before changing the current
reference. Replacing each JSON file atomically does not make the five-file set an
atomic publication. A failed write or validation must leave the current
successful snapshot and its version unchanged.

Images are separate best-effort resources. A failed download keeps an existing
image when present, and a missing image does not block catalog publication.
Missing resources can be filled independently without fetching every entity
again. Readers generate image metadata only for files that exist. Patch records
are stored by patch version and do not share the catalog snapshot number.

### Guide partition storage and migration (components implemented; actual migration pending)

The standalone `FileHeroGuideCache(data_root)` preserves the current partition
keys: Pub by hero and position, Pro by hero. Files live at
`guides/pub/<hero_id>/<position>.json` and `guides/pro/<hero_id>.json`. Each
schema-version-1 file contains the partition identity and a complete
`GuideCacheEntry`; `GuideCacheSnapshot.raw_body` uses the existing Base64 JSON
encoding. The entry retains exact response bytes, parsed source rows, DTO
projection, retrieval time, most recent attempt time, and failure/status
information. A valid empty snapshot remains distinct from a missing partition.
A failed attempt retains the last successful snapshot. Per-partition writes use
a same-directory temporary file and `os.replace`; reads do not write, files have
no TTL, and this component is not connected to API composition.

The callable `migrate_redis_guides()` validates the complete hero list before
I/O, reads Pub positions 1 through 5 and then Pro through the existing Redis
cache API, imports complete non-missing entries, and reads each imported or
already-present file back for value equality. Identical files are safe to skip;
conflicting or corrupt targets stop the migration. The report counts checked,
missing, imported, and already-present partitions. Tests use a fake Redis and
temporary files. No real Redis migration has been run. The API, existing refresh
CLI, and timer still use Redis. The new `migrate-guides` operator command calls
this component using the hero list from the current file-backed catalog; it
reads `DOTAMIND_REDIS_URL` from the environment.

Run `python -m app.vnext.data_updates init-catalog` before
`python -m app.vnext.data_updates migrate-guides`. Both accept `--data-dir` as
an absolute persistent root, falling back to `DOTAMIND_DATA_DIR`; an unset or
invalid path fails instead of defaulting to the repository or working
directory. `init-catalog` accepts an optional local `--source-dir` and defaults
to the bundled catalog. It copies only the five catalog JSON files, excluding
images and patch records. A valid current pointer is left untouched, including
when the requested source directory is absent, and a damaged pointer is
reported rather than overwritten.

Migration uses the current published catalog's hero list, does not scan Redis
keys or request provider data, and writes only to the configured data root.
Identical target partitions are verified and skipped; conflicts stop with the
files and Redis entries preserved. Run the command in the same API container as
the Redis refresh CLI because their shared refresh lock is container-local.
The API and recurring refresh path have not switched to files.

The existing 36-hour stale rule remains query semantics; it is not a file TTL or
deletion rule. Local-name enrichment remains at query time and is not written
back into source guide snapshots. A future migration run must verify raw bytes,
source rows, DTOs, times, and states before any API switch. Do not rely on
indefinite dual writes, and do not delete the old Redis guide data before
migration acceptance. This migration does not change session, Run State, or
Artifact storage.

### Update cadence and version gates

| Condition | Target behavior |
|---|---|
| Official latest patch equals the patch of the current successful catalog | Skip the full entity fetch by default. |
| Official latest patch differs | Fetch, validate, and publish a new complete catalog snapshot. |
| Patch-version check fails | Record an update failure; never interpret it as “unchanged.” |
| A new catalog cannot be published | Keep the old success; retry the new version on the next run. |
| Same-patch catalog is missing or corrupt, or an explicit forced refresh is requested | Allow the catalog to be regenerated. |
| Images are missing | Fill missing images independently where possible; do not refetch all entities. |
| Guide partitions | Update daily, independently of the entity-patch gate. |

Skipping a full fetch for the same patch is DotaMind's update policy. It is not a
Valve guarantee that entity content cannot change within one patch. Keep these
values distinct in stored data and observations: the official latest patch, the
patch of the last successfully published catalog, the catalog snapshot number,
each guide source's scope and retrieval/attempt times, and the image-resource
version. The sampled Valve endpoints and their limits are recorded in
[`reference/valve-datafeed.md`](reference/valve-datafeed.md).

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

## Hero guide data contract (DTO, HTTP client, parsers, cache, and refresh executor implemented)

The internal contract is defined in `app.vnext.capabilities.hero.guide`. A
synchronous D2PT HTTP client now fetches the heroes list, Pub builds, and Pro
builds. It preserves the exact response bytes and parsed JSON array and performs
transport and minimal source-shape checks. Pure Pub and Pro parsers project
source rows into the existing guide DTOs without changing the response. A
Redis cache stores source snapshots and is wired to the application's existing
Redis connection. HeroGuideService exposes cache-only queries through the
conditionally registered hero.guide tool. An internal serial refresher connects
the D2PT client, parsers, and cache. An operator-only CLI runs it on demand, and
the repository systemd service/timer template describes daily scheduling. Host
installation is separate; a historical WSL setup used its own WSL-path unit and
enabled timer. The CLI is not a public endpoint or model tool.
The input selects one `(hero_id, position)` pair, with a strict positive integer hero ID,
a strict integer position from 1 through 5, and `section` equal to `all`,
`items`, `skills`, or `pro_examples` (default `all`). It does not accept a hero
name, provider selector, URL, or refresh request.

The HTTP client uses the fixed D2PT base URL, the verified `User-Agent`,
`Referer`, and `Accept: application/json` headers, and Python's standard
`urllib.request` transport. It makes one bounded request per method without
automatic retry. Responses are limited to 8 MiB, must have HTTP status 200, and
must decode as UTF-8 JSON arrays of objects with minimally valid identity and
container fields. Content-Type is retained as metadata and does not determine
whether a body is JSON. The offline client tests inject a fake opener; they do
not verify live provider access.

`HeroGuideResult` contains `hero_id`, `position`, `section`, independent
`pub_metadata` and `pro_metadata`, `pub_guides[]`, `pro_examples[]`, and optional
known totals. Each `GuideSourceMetadata` identifies D2PT and Pub/Pro sample
type, and represents `available`, `empty`, or `missing` plus stale state,
retrieval/attempt timestamps, source update text, last error, and an open source
scope object. Retrieval and attempt datetimes require timezones. The source
`updated_at` remains an unparsed string without inferred timezone. The DTO does
not calculate staleness or synthesize the current time.

The contract's concrete shape is:

| Model | Fields |
|---|---|
| `HeroGuideInput` | `hero_id`, `position`, `section` |
| `GuideSourceMetadata` | `provider`, `sample_type`, `availability`, `stale`, `retrieved_at`, `source_updated_at`, `last_attempt_at`, `last_error`, `scope` |
| `GuideItem` | `item_id`, `quantity`, `name` |
| `StartingItemOption` | `items`, `statistics`, `source_path` |
| `ItemTiming` | `kind`, `minute`, `source_path` |
| `GuideItemObservation` | `item_id`, `name`, `phase`, `timing`, `statistics`, `source_path` |
| `SkillSequenceOption` | `ability_ids`, `statistics`, `source_path` |
| `TalentObservation` | `level`, `data`, `source_path` |
| `PubGuide` | `build_id`, `facet_id`, `source_updated_at`, `scope`, `statistics`, `starting_options`, `item_progression`, `situational_items`, `skill_sequences`, `talents` |
| `ProItemEvent` | `item_id`, `minute`, `source_fields` |
| `ProAbilityEvent` | `ability_id`, `time_seconds`, `hero_level`, `source_fields` |
| `ProMatchExample` | `source_match_id`, `account_id`, `hero_id`, `position`, `position_basis`, `date`, `started_at_unix`, `player_name`, `team_name`, `opponent_name`, `won`, `duration_seconds`, `item_timeline`, `ability_timeline`, `talent_choices`, `source_path` |
| `HeroGuideResult` | `hero_id`, `position`, `section`, `pub_metadata`, `pro_metadata`, `pub_guides`, `pro_examples`, `pub_guides_total`, `pro_examples_total` |

`GuideSection` is `all | items | skills | pro_examples`; `HeroPosition` is a
strict integer from 1 through 5. All DTO models reject extra fields. Numeric
identifiers use strict integers, open JSON objects use recursive JSON values,
and non-finite numbers are rejected even inside those objects. List/object
fields default to fresh empty collections; optional totals default to `None`.

`ProAbilityEvent.ability_id` is a non-negative strict integer: zero is retained
as the source value, but it is not mapped to an ability name or interpreted as
a specific kind of level-up event. Pub `SkillSequenceOption.ability_ids` remain
strictly positive IDs; this Pro event rule does not relax other identifier
fields.

`PubGuide` holds source build/facet IDs, per-build metadata, open statistics,
starting-item options, item progression, situational items, skill-sequence
options, and talent observations. Each open source JSON object preserves unknown
fields, nested null, zero, false, and finite values outside a 0-to-1 range; NaN
and infinity are rejected. `source_path` records where a value was found in the
raw response. It is neither an ArtifactRef nor an upstream navigation handle.
Candidate starting-item options and skill sequences remain independent and are
never cross-paired. The DTO does not encode neutral-item statistics or complete
six-slot summaries.

Skill sequences preserve source order, duplicates, and supplied length; they
are not expanded into hero-level plans. Item timing is represented as a
source-attributed `average` or `median` value without calculating either. The
current parser maps Pub `avg_minute` into average timing and applies the
30-minute display phase boundary documented above. The
raw response does not establish universal definitions for `pr`, `pick_rate`,
nested `win_rate`, `avg_minute`, or `std_minute`; preserve source paths and
associated counts, and do not compare unrelated paths or infer causal item
impact.

`ProMatchExample` represents a concrete recent-match example with a source match
ID, optional account/player/team fields, optional position and explicit
`position_basis`, and ordered item/ability/talent events. `source_match_id` does
not claim cross-source Valve identity verification. Pro aggregate statistics
are not turned into a recommended route, and no field links a Pro example to a
Pub build.

### Implemented source projections

`parse_pub_builds(rows, hero_id, position)` validates each root row's hero,
position, and `build_data`, then returns one `PubGuide` per source row in source
order. `build_id` and `facet_id` are optional non-negative strict integers;
`updated_at` remains a string and `data_scope` is copied as an open object.
Statistics use separate `root` and `build_data` namespaces and include only
source-present `num_matches`, `num_wins`, `pick_rate`, and `win_rate` keys, with
values unchanged. Missing or null candidate arrays become empty lists. A
malformed row or candidate fails the complete parse with `D2PTParseError` and a
generated source path; rows are not silently skipped.

Pub `starting_items_new` entries are `[item_ids, statistics]`. Repeated IDs are
merged into a quantity within that option only, retaining first-seen order;
separate options remain separate. `anchor_items` maps to `item_progression` and
`items_mid_late` maps to `situational_items`; both preserve each complete source
row as statistics. Only `avg_minute` is mapped as an average timing. The DTO
phase is `mid` at or before 30 minutes, `late` after 30, and `unknown` when the
field is missing or null. These are DotaMind projection choices, not claims that
the source fields have universal statistical semantics. `abilities_new` keeps
each supplied ordered sequence and its statistics; it is not expanded into a
hero-level plan. Pub talents retain their complete source rows.

`parse_pro_examples(rows, hero_id)` reads only each root row's
`recent_matches`; Pro aggregate build, item, and ability fields do not produce
recommendations. Each recent match becomes an example with ordered item,
ability, and talent observations. Root position supplies the fallback. A unique
draft row matching both account ID and hero ID supplies position when the match
has an account ID; without one, matching uses hero ID. A missing, ambiguous, or
invalid draft position falls back to the root position. The selected position's
basis is recorded as `draft` or `build`. Other heroes in the draft are valid
match context.

Both parsers reject bool-as-number, non-finite times, wrong non-null optional
field types, and malformed nested arrays as a whole. Open DTO dictionaries are
deep copies. Unknown provider fields that have no DTO field remain in the
original `D2PTResponse`; parsing is a projection, not source retention.

Three additional real Pro response fixtures captured for parser diagnosis
contained integer `ability_id=0` events. The earlier positive-only Pro event
constraint rejected those complete responses; the current Pro parser preserves
their non-negative IDs and event order without assigning a name or game
meaning. This regression evidence covers only those three samples; it does not
establish general parser coverage. A later local full-refresh record is separate
deployment evidence, documented in [`EVALS.md`](EVALS.md).

`RedisHeroGuideCache` is an independent storage component that receives an
already fetched and parsed `GuideCacheSnapshot`; it does not call the client or
parsers. Each snapshot contains the sample type, hero and Pub position where
applicable, timezone-aware retrieval time, content type, exact raw response
bytes, complete parsed source rows, and the corresponding DTO projection. The
raw bytes are stored as Base64 inside snapshot JSON and restored byte-for-byte.
Pub snapshots are keyed by hero and position; Pro snapshots are keyed by hero
and replace that hero's complete set of examples across positions. The query
Service filters Pro examples to the requested position.

Each Redis hash stores `snapshot`, `last_attempt_at`, and `last_error`. Successful
publication sets all three with one `HSET`, replacing the old snapshot; a valid
empty response remains a successful non-null snapshot. A failed attempt writes
only its timestamp and stable error code, retaining any last successful
snapshot. Reads use one `HGETALL`; an empty hash means never attempted, while a
first failure has status fields but no snapshot. The cache sets no TTL and does
not calculate freshness, staleness, or current/update timestamps. Cache errors
are surfaced as fixed safe exceptions; malformed stored data is not treated as
a miss or deleted automatically.

The cache accepts an injected async Redis client and does not create or close
connections. Offline tests use a small fake Redis; they do not verify live Redis,
container configuration, AOF recovery, or restart persistence. Deployed
persistence relies on Redis AOF and its configured persistent volume.

`HeroGuideRefresher.refresh_all()` performs only the fetch/parse/publish pass. It
uses the validated hero-list order, requests Pub positions 1 through 5 followed
by one Pro response per hero, and does not read the cache or skip fresh
partitions. Synchronous client calls run one at a time through
`asyncio.to_thread()`. After a response or `D2PTError`, it waits exactly one
second before parsing, publishing, recording a partition failure, or issuing the
next request. A successful parse publishes the response's original bytes, source
rows, retrieval time, and DTOs together; a valid empty array is published as a
successful empty snapshot. A fetch or parse failure records only the stable error
code and attempt time, leaving old snapshot data to the cache's failure-retention
behavior. Cache write errors abort the pass; cancellation and unexpected
programming errors propagate. Cancelling an awaited `to_thread()` call does not
forcibly stop an urllib request already running in its worker thread.

The refresher returns an in-memory report with status, timing, hero/request and
publication counts, empty-response counts, and ordered partition failures. It
does not retain exception text or provider response payloads in the report. The
executor is not wired to application startup or an HTTP endpoint. The CLI reads
`DOTAMIND_REDIS_URL` from its process environment, acquires a non-blocking `flock`
at `/tmp/dotamind-hero-guide-refresh.lock` before creating resources, pings Redis,
executes one refresh, emits one JSON result, and closes Redis before releasing the
lock. Success, partial, failed, skipped, and cancelled results use fixed exit
codes; exception details and credentials are not printed. The lock coordinates
processes sharing one API container's `/tmp` only, not multiple API containers.
On SIGINT/SIGTERM the CLI cancels the refresh coroutine, then waits for the
default executor before closing Redis; cancellation does not forcibly stop an
urllib request already running in its worker thread. The repository templates
invoke this CLI daily at 03:00 Asia/Shanghai; their production paths do not
describe local WSL installation state. A historical WSL record says its separate
timer was enabled and a local full refresh populated guide data. This does not
establish a successful scheduled firing, another deployment's cache contents, or
the planned shared-file migration and API hot reload.

The cache is connected to a read-only `HeroGuideService`, which the model-facing
`hero.guide` tool exposes when the application injects the cache. The Service
reads Pub and Pro once each for every section query. It filters Pro examples by
both exact hero ID and exact requested position, retaining source order and
duplicates while excluding unknown positions. It does not infer positions again
or use Pro aggregates to build recommendations.

Availability is based on the full cached candidates before section projection:
no snapshot is `missing`; a successful snapshot with no matching candidates is
`empty`; otherwise it is `available`. A Pro hero snapshot containing examples
for other positions can therefore be `empty` for the requested position. A
snapshot is stale when its age is at least 36 hours or its latest refresh
attempt failed. A future retrieval time alone is not stale. Successful empty
snapshots can age and become stale. Source update labels, patch labels, or
statistics windows do not affect freshness. A read error marks only that source
missing with `cache_unavailable` or `cache_invalid_data`, without carrying
unconfirmed timestamps; the other source can still be returned. If both reads
fail, the tool returns a fixed `tool_execution_error` with only those two error
codes.

`source_updated_at` is exposed only when every root source row has the same
non-empty string `updated_at`; it is not parsed or inferred. `scope.records`
preserves each root row's source path and any present `position`, `updated_at`,
and `data_scope` values, including nulls. It does not claim that Pro hero-level
scope belongs only to the requested position.

Section projection occurs after candidate matching. `all` returns both source
projections; `items` retains Pub build metadata, statistics, and item fields but
clears skill sequences and talents; `skills` retains Pub metadata, statistics,
sequences, and talents but clears item fields; `pro_examples` returns only the
matching Pro examples. Empty projected Pub rows are retained. Totals count
hero-position candidates before projection; a missing or unreadable partition
has a null total, while a successful empty partition has total zero. Application
startup has not been wired to fetch or refresh data, so currently empty Redis
keys yield normal missing-source results unless an operator runs the CLI. These
query rules do not establish
live Redis persistence, all-hero coverage, or real-model answer quality.

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
