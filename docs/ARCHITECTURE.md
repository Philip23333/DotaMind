# Architecture

## Status

The tool layer is in a clean-slate rebuild. The default LLM-facing registry
currently contains the generic Artifact tools and the closed
`esports.league.search`, `esports.series.search`,
`esports.series.teams`, `esports.tournament.search`,
`esports.match.search`, `esports.team.search`, and `esports.player.search`
capabilities. When game resolution is explicitly enabled with its required
PandaScore and OpenDota configuration, the registry also includes
`esports.game.resolve`. When explicitly enabled and discovered during application
startup, it also contains `web.search`, backed by Tavily's remote
`tavily_search` MCP tool.
Additional domain capabilities are introduced later as independent contracts.

## Principles

- The model chooses which broad capability observations to combine.
- Deterministic code owns validation, bounds, persistence, and stable errors.
- Provider adapters remain below capability contracts; the current Artifact
  path receives each capability's validated public output rather than raw
  provider transport payloads.
- Temporary Artifacts externalize complete large logical tool responses without
  becoming domain entities or a searchable corpus.
- A provider-private identifier is evidence, not a model-facing navigation
  language, unless a future capability explicitly defines that input.

## System boundary

```text
User
  -> Product Chat API
  -> Agent Runtime
  -> LLM
       <-> artifact.grep / artifact.read
             -> session Artifact store
       <-> esports.league.search
             -> league capability contract
             -> PandaScore adapter/client
             -> league observations
       <-> esports.series.search
             -> series capability contract
             -> PandaScore adapter/client
             -> series observations
       <-> esports.series.teams
             -> series participant-team capability contract
             -> PandaScore adapter/client
             -> series team observations
       <-> esports.tournament.search
             -> tournament capability contract
             -> PandaScore adapter/client
             -> tournament observations
       <-> esports.match.search
             -> match capability contract
             -> PandaScore adapter/client
             -> validated match observations
       <-> esports.team.search
             -> team capability contract
             -> PandaScore adapter/client
             -> team identity observations
       <-> esports.player.search
             -> player capability contract
             -> PandaScore adapter/client
             -> player identity/current-team observations
       <-> web.search (optional)
             -> discovered remote JSON Schema / local validation
             -> Tavily MCP adapter
             -> official MCP SDK Streamable HTTP session
             -> source-preserving search observations
       oversized tool result
             -> generic result processor
             -> complete validated logical tool response in a session Artifact
             -> bounded observation
```

Future domain capabilities follow this seam:

```text
Model
  -> semantic Tool / capability contract
  -> Capability Service
  -> Provider implementation
  -> Provider Adapter / transport
  -> complete validated capability result
       -> bounded observation when oversized
```

Code-internal capabilities may share the injected local `EntityNameResolver` to
map explicitly selected hero, item, and ability IDs to bundled Valve catalog
names. The business capability remains responsible for identifying which
fields contain those IDs and for preserving its source IDs and source data; the
resolver returns the explicit IDs alongside resolved names and does not inspect
arbitrary JSON, perform fuzzy matching, or register a model-facing tool. Its
names are attributed to the local Valve catalog snapshot; upstream facts retain
their source attribution. Unknown IDs remain present with empty names. The shared
component is integrated into `hero.guide` and the governed `game.detail` DTO. The latter keeps IDs but
replaces source internal-key business fields with exact entity objects and
retains unconvertible scalar evidence in coverage. This exception does not make
the shared resolver a source-JSON scanner.

The model-facing contract never exposes wire routes, credentials, pagination
syntax, or transport-private IDs. A single provider does not justify a router or
plugin framework.

### Game-detail data governance

`game.detail(valve_game_id)` binds to `GameDetailService`. The STRATZ adapter
validates and retains the primary record; the OpenDota adapter provides fixed
supplemental groups when enabled. Each validates the exact Valve identity.
The capability-owned projection combines only the selected data groups after
same-game player associations, then applies pinned local bilingual labels.
The owner is [the data contract](agent/game_detail_data.md).

The OpenDota `OpenDotaGameRecord` remains the resolver's complete internal record.
The Service and resolver share that adapter and request-scoped source reuse;
the public result type is independent. The STRATZ adapter retains its own
`StratzGameRecord`. No public Artifact can retrieve either raw source document.

The public envelope identifies STRATZ as primary and attributes successful reads
separately through `sources`. Group coverage and event paths distinguish actual
origins, partial observations, mapping gaps and conflicts. A validated primary
record can survive an explicitly scoped optional `playbackData` GraphQL error;
safe field paths record the limitation. Root/identity and unscoped errors fail.
Ordinary supplemental unavailability leaves dependent groups unknown; cancellation,
programming, local resource and storage errors keep their normal behavior.

The capability owns economic naming, normalized deaths, timed build observations,
and exact unit/entity conversion. Runtime and generic Artifact tools own no
provider selection or game semantics. Generic Artifact handling stores the complete
governed DTO and returns bounded observations. No dynamic routing framework,
model fallback workflow, new storage or replay parser is introduced.

One entity Catalog and one versioned local unit mapping are pinned per operation.
Exact ID/key conversion precedes public validation; missing names do not erase
known facts. Labels do not infer controllers or historical mechanics. Static
mapping gaps never become remote Catalog calls. Historical STRATZ NPC encodings
remain separate from Valve hero IDs.

[Source evidence](reference/stratz-game-detail.md) and [acceptance](EVALS.md)
distinguish deterministic checks, three live detail reads, and fixed-source model
questions. Unverified arrays and historical encodings remain explicit limits.
The accepted final GPM-derived income and known zero-based skill-rank mappings
have newer source evidence; enabling those target mappings still requires code
and tests. Exact terminal income for a precise net-worth gap remains unverified.
Frontend and a background League index are outside the implemented change.

The next accepted extension is [the default report and heatmap contract](agent/game_detail_report.md),
not yet implemented. The capability constructs deterministic report views from
its governed DTO; generic Runtime/Artifact tools do not become report builders.
Default reports bind player/time/metric facts before the model analyses them,
while complete governed detail remains inspectable for follow-ups.

Heatmaps run separately after an explicit request, without blocking ordinary
detail. One temporary STRATZ position read feeds a bounded background render;
only cumulative five-minute/final PNGs and a small provenance index persist.
The ordinary source-record and request-cache paths must never retain coordinates.
Do not route raw position results through generic Artifact handling or Trace.
Image failure preserves detail. Image lifecycle, authorization and entry/reference
interfaces require an explicit implementation decision; neither the session
Artifact store nor static entity display references supply them automatically.
This needs no universal job framework, provider router or model code executor.

The optional web-search integration is initialized asynchronously in the API
lifespan before Runtime construction. Synchronous/offline composition performs
no MCP I/O. Startup discovers and validates the exact remote search capability;
each later search opens and closes a separate authenticated MCP session. The
bearer credential is confined to the transport header, and discovery or request
failures do not disable the independent PandaScore services.

## Tool registry boundary

`ToolRegistry`, `ToolDefinition`, and `ToolExecutor` are generic runtime
primitives. The default builder lives in the composition root and explicitly
registers Artifact tools plus accepted domain capabilities. A generic result
processor is attached at registry composition time: it stores complete
oversized non-Artifact outputs and returns bounded observations, while each
Artifact retrieval tool opts out explicitly. Domain modules must not own the
application registry builder, and removed capabilities must not be kept as
aliases or hidden registrations.

Composition builds one registry and renders its ordered tool names into a short
`Enabled tools for this run` inventory (`none` for an empty registry). The same
registry instance is passed to Runtime. The inventory is appended to
`shared_instruction` alongside product identity and conditional web-search
guidance, so execution, primary answers, answer retries, and degraded answers
receive the same enabled-capability information. Only names are duplicated;
descriptions and argument schemas live in each stage's permitted tool declarations.
Earlier assistant capability claims do not override the current inventory.

Answer requests expose only read-only definitions marked `local_artifact_read`
or `pure_compute`; other tools default to denied. Runtime checks access again
before dispatch. `math.calculate` performs bounded local Decimal arithmetic and
shares the pure time formatter with GameDetail. It has no Provider/Artifact
dependency and does not write derived values into source documents.

Execution has ended, but local verification and calculation may continue under
stage deadlines, cancellation and context-capacity governance. The accepted target
removes total answer call and cumulative result-byte quotas, as implemented and
specified in [TOOLS.md](TOOLS.md). Current declarations and
stage instructions define permissions; the product inventory proves neither
cache availability nor lookup success. Ordinary history and Trace retain
verification calls/results, without a second registry, Provider retrieval or
task-state mutation. [TOOLS.md](TOOLS.md) owns the detailed contract.

The current esports boundaries are `esports.league.search`,
`esports.series.search`, `esports.tournament.search`,
`esports.series.teams`, `esports.match.search`, `esports.team.search`,
and `esports.player.search`. Each capability owns
semantic inputs and outputs, while its thin PandaScore adapter translates those
inputs into one provider request and normalizes validated facts. All six
adapters share one `PandaScoreClient` at composition time; provider routes and
query parameter names stay below the model-facing schemas.

The adapter tree is intentionally explicit:

```text
PandaScoreClient
  ├── LeagueAdapter
  ├── SeriesAdapter
  ├── TournamentAdapter
  ├── MatchAdapter
  ├── TeamAdapter
  └── PlayerAdapter
```

Provider-private `serie_id` is translated to semantic `series_id` only inside
PandaScore adapters.

## Artifact boundary

Artifacts are temporary, process-local, session-owned JSON-like documents. Each
oversized response receives a fresh opaque reference. `artifact.read` and
`artifact.grep` accept one exact reference and never fetch a provider or
perform business aggregation. The Artifact content is the complete validated
logical tool response; the bounded model observation is derived separately by
the generic result processor for ordinary tools. A stored ref is not
automatically restored into a later turn's dialogue context.

`artifact.query` adds conditional selection and direct-field projection of original
object records. It is implemented and registered, with deterministic checks.
Generic Artifact retrieval owns it, below the model-facing tool and independently
of Provider/game capabilities. It must not reshape stored documents or implement
gameplay logic. The full contract is owned by [ARTIFACTS.md](ARTIFACTS.md#structured-query).

### Shared tool-result admission

The same single-result policy must apply to execution and answering. Tools and
the ordinary-result processor own useful budget-fitting observations: externalize
ordinary capability results, page list reads/query/grep, or fail explicitly when
an indivisible value cannot fit. A common result exit checks the processed
model-visible content before history admission and returns a bounded error for
unexpected oversized output. It does not silently trim data or externalize
Artifact retrieval results into further Artifacts. Stage permissions can differ;
the same local tool call must not encounter a stage-specific byte ceiling.

Root `.env` owns the existing inline/externalization and observation byte settings,
with defaults of 12 KiB and 35 KiB respectively. Parse once, validate centrally,
and inject the same observation value into all producers and the final check;
remove independent fixed clamps, including query and answer checks. Keep answer
permissions and duplicate tracking when removing the answer-only size gate.
The accepted grep contract has one key/value search behavior, no `scope` or
`matched_on`, and whole-match pagination by actual returned count. The owner of
all byte/configuration and retrieval details is
[ARTIFACTS.md](ARTIFACTS.md#shared-tool-result-byte-budget).

Shared admission, configured read/query/grep processing and byte-aware grep paging
are implemented with deterministic tests, including smaller/larger budgets and
primary/degraded continuation. This controls individual results separately from
the answer watermark workflow; it does not change context capacity, permissions
or source-data retention. It does not imply deployment or model compliance.

## Request calendar anchor

Runtime captures one wall-clock timestamp at the start of each user request in
`Asia/Shanghai`, independent of the server's local timezone. Both execution and
answer prompts explicitly receive the Beijing calendar date, offset-aware ISO
datetime (for example `2026-10-17T23:59:59+08:00`) and timezone name. Relative
dates use this request-start anchor. Tool-loop continuations, compaction rebuilds,
overflow retries and degraded answers retain the same anchor, even across midnight.
The next user request captures a new anchor. It is request-local, not mutable
shared Runtime state, and is retained in request metadata and execution Trace.

This time is not a Provider update time or match timestamp. Source times retain
their own semantics. Monotonic deadlines continue to control execution budgets;
calendar injection does not extend them or change gameplay time formatting.

## Two-stage context governance

Execution and answering use the same configured context window and full-request
watermark rules. Occupancy is recomputed from each actual request, including
instructions, tool declarations, retained history/results and stage context, with
the existing output/compaction reservations. It is not cumulative token billing
and does not reset to zero at the stage boundary. Compaction may reduce occupancy.
An unset context window retains the existing disabled automatic-governance behavior.

Before every business model invocation in either stage, including each answer
tool-loop continuation and degraded answer, high or critical pressure triggers
the existing compaction workflow when its no-progress guard permits. Rebuild the
request from effective history, reassess capacity and apply the existing stage
failure/recovery/fallback path if it still cannot fit. Do not repeatedly summarize
unchanged history or create another summary engine or overflow allowance.

Primary/degraded entry and tool-loop continuations use one answer preflight;
execution uses the same full-request capacity rules and atomic compaction workflow.
Completed successful tools permit another compaction attempt; failed/duplicate
calls do not reset the no-progress guard, though their context is still measured.
Answer call/byte totals are diagnostic metrics, not cumulative admission quotas.
An expired deadline stops preflight before another capacity/compaction attempt.
This behavior is implemented with deterministic checks; live quality acceptance
remains separate.
Keep the configured per-result bound (default 35 KiB) and generic access checks;
its shared exit is defined above, separately from this implemented
context-capacity workflow. Request-local duplicate
tracking and diagnostics survive rebuilding; compaction/retry must not reset the
active deadline. Keep existing degraded-stage deadlines, cancellation and bounded
failure behavior. There is no promise of unlimited run time or perfect summary
fidelity. Stored Artifacts and append-only raw records remain unchanged and
available through existing retrieval; completed tools are not replayed.

The conclusion-handoff target below must also survive answer request rebuilding;
unifying capacity policy does not authorize dropping that conclusion or replacing
it with a summary. Detailed accounting remains owned by
[context_accounting.md](agent/context_accounting.md).

## Execution-to-answer conclusion handoff

This section owns the implemented conclusion handoff. Runtime records an execution
`FinalMessage` as `execution_final` in the raw journal and retains the model
response in Trace. A request-local copy supplies its ordinary text verbatim as
an assistant message in primary, rebuilt and degraded answer requests, without
appending the internal copy to effective conversation history. A separate system
annotation identifies its internal status and original `finish_reason`, including
possible truncation; absence is explicit. The conclusion text itself is never
promoted into system instructions. Deterministic acceptance is separate from
real-model accuracy evaluation.

The handoff passes the execution model's final ordinary text unchanged
to the answer model, alongside evidence. Reuse that existing response; do not
make an extra summary call, impose a model-authored schema, extract hidden
reasoning, or synthesize a conclusion from tool commentary/checkpoints. Preserve
known completion/truncation diagnostics rather than implying partial text was
complete. The logical answer input is:

```text
shared product instructions + answer instructions + current permissions/budget
effective conversation, retained tool results, summary and Artifact locators
current execution conclusion, when one exists (internal assistant content)
execution outcome, task completion and evidence gaps
```

AnswerContext observation lists are supplemental projections, not a complete
inventory of evidence. When effective history already carries tool results, the
projection avoids duplicating them. Empty supplemental lists must not be described
as proof that source observations or retrieval permissions are absent.

Insert the conclusion as clearly attributed internal assistant content in the
answer request, not as a system rule or a user-delivered final answer. No new
public DTO or model-facing tool is needed. Existing prompt obligations to check
numerical/summary claims against source observations and to use bounded local
verification remain; a conclusion is working analysis, not proof of its facts.
It neither replaces evidence nor changes the classification of successful tools,
verified identities, task completion or answer resolution.

| Execution outcome | Conclusion behavior |
| --- | --- |
| Execution ends after a model `FinalMessage` | Pass that response's ordinary text unchanged |
| Runtime ends immediately after a completed task plan | Mark that no model conclusion was generated; make no extra call |
| Timeout, correction exhaustion or another stop without a final conclusion | Retain actual stop reason and available evidence; do not manufacture text or reuse an older conclusion |
| Primary answer, overflow retry or degraded answer | Carry the same current-request conclusion whenever it exists; answer-stage drafts are not new execution conclusions |

Keep the conclusion in request-local handoff state through answer completion.
It must survive answer-request rebuilding and compaction recovery without being
silently dropped or replaced by a history summary. Include its actual bytes/
tokens in every request's capacity accounting. If the complete request cannot
fit, use existing recovery/degraded/fallback behavior; do not silently truncate
the conclusion or bypass capacity/deadline checks to deliver it.

Raw execution records remain available for diagnostics. The ephemeral handoff
copy is not appended to effective user-visible conversation history as a delivered
answer, is not eligible checkpoint/source evidence, and does not generate process
commentary or final-answer deltas. Later user turns retain the actual delivered
answer and ordinary history under existing rules, without automatically replaying
this internal copy. Storage/context lifecycle and product consequences are
summarized in [context governance](agent/context_governance_evidence_lifecycle.md)
and [product run state](agent/product_run_state.md).

## Hero guide data flow (file-backed queries and scheduled refresh active on WSL)

The synchronous D2PT client and pure Pub/Pro parsers produce complete guide
partitions. `HeroGuideRefresher` fetches the hero list once, then requests Pub
positions 1 through 5 and Pro once per hero in source order. Requests run
sequentially; after each response or D2PT error, it waits one second before
parsing, publishing, recording failure, or starting the next request. A fetch or
parse failure preserves that file partition's last successful snapshot; a file
write failure aborts the refresh. Cancellation and unexpected programming errors
propagate.

The supported steady-state update and query path is:

```text
daily systemd timer or operator refresh-all
  -> data-root update lock
  -> HeroGuideRefresher
  -> FileHeroGuideCache
  -> shared-data volume

API with DOTAMIND_DATA_DIR and a read-only shared-data mount
  -> FileHeroGuideCache reads each requested partition directly
  -> HeroGuideService -> hero/position filter and section projection
  -> local Valve catalog labels -> bounded tool result or Artifact
```

`FileHeroGuideCache` stores each complete Pub/Pro partition, including source
bytes, source rows, projected DTOs, retrieval time, and latest attempt/error
state. Writes use a same-directory temporary file and `os.replace`. Queries do
not cache file contents, write files, call D2PT, or start a refresh; the next
query sees a successfully replaced partition. With `DOTAMIND_DATA_DIR`, the API
registers `hero.guide` over that data root. Without it, the guide tool is absent;
there is no Redis fallback. Redis remains in use for unrelated stores such as
sessions, traces, and recent-series candidates.

`RedisHeroGuideCache` and `migrate-guides` remain only to import legacy Redis
guide snapshots into a file data root when a deployment requires it. The old
Redis guide refresh CLI and systemd timer templates have been removed. The
migration importer is not part of the daily job and does not make Redis a guide
query source.

Each file snapshot records retrieval time separately from latest attempt time
and error. The Guide Service marks a snapshot stale at an age of 36 hours or
after a failed refresh attempt. Missing, empty, and failed source states remain
distinct. The shared cross-session guide files remain separate from the
process-local session Artifact store: Artifacts hold oversized tool results and
are not the durable guide cache. The current WSL file refresh and API read
evidence are recorded in the evaluation and operations references; production
activation remains a separate deployment step.

## Shared data updates and API hot reload (WSL deployed; production migration and deployment pending)

The shared update task owns application-wide Valve entities, patch records,
images, and D2PT guide partitions. Its planned responsibilities are:

| Boundary | Target responsibility |
|---|---|
| Schedule and manual entry | The manual `refresh-all` command coordinates one refresh. The WSL 03:00 Asia/Shanghai timer is installed and enabled; the production timer remains a configured template only. |
| Fetch and processing | Reuse one bounded Valve Datafeed session for Catalog and patch records. Keep image downloads under a separate bound and D2PT requests serial with a one-second interval. |
| Publication | Publish the five-file entity catalog as one snapshot; publish guide partitions independently; process patch records and images separately. |
| Persistence | Compose declares a project-scoped `shared-data` volume. WSL loads `compose.data.yml`: the updater is writable and the API mount is read-only. Production has not activated this overlay. |
| Online reads | Load catalogs in the background and switch snapshots; read guides by partition. Queries never start a remote refresh. |

`CatalogSnapshotStore` copies the five catalog JSON files byte-for-byte into
immutable UUID-revision directories, validates the copied catalog and sync audit,
and atomically replaces `catalog/current.json` only after the complete revision
can be loaded by `DotaCatalogRepository`. A failed publication leaves the prior
pointer intact. It does not claim power-loss recovery.

`CatalogSnapshotLoader` loads and validates the pointed snapshot before starting
its poller. When `DOTAMIND_DATA_DIR` is configured as an absolute path, API startup
uses this loader and fails if its current snapshot is missing or invalid. The
loader checks only the pointer by default every 30 seconds; when the revision
changes, it loads the complete snapshot in a worker thread and switches one
in-memory `CatalogSnapshot` reference after validation. An unchanged revision
does not reload the five files. A failed check or load keeps the previous snapshot
available, and stopping waits for an in-flight refresh to finish. The check
interval is not a bound on validation or IO completion time.

The operator module `python -m app.vnext.data_updates` exposes `init-catalog`,
`migrate-guides`, `refresh-guides`, `refresh-catalog`, `refresh-patches`,
`refresh-images`, and `refresh-all`.
`init-catalog` publishes
the bundled or explicitly selected five-file catalog only when no valid current
snapshot exists. `migrate-guides` reads hero IDs from that repository and calls
the Redis-to-file importer. All five require an absolute data root from
`--data-dir` or `DOTAMIND_DATA_DIR`; migration reads `DOTAMIND_REDIS_URL` only
from the environment. A shared data-root lock protects commands that update the
same file root. File guide refresh does not require a catalog snapshot or Redis
URL; it acquires that lock before constructing D2PT and file-cache resources. The
file guide refresh command has offline fake-client tests and completed a real WSL
run for 127 heroes. The WSL data root was initialized from the bundled Catalog;
no Redis guide migration was
performed, and the old Docker Desktop data was left untouched. The API reads guide
files from this root. The old Redis guide timer is disabled on WSL, and the unified
03:00 timer is enabled but has not yet fired. The production path remains pending.
Do not schedule both guide refresh commands daily.

The existing Valve catalog, patch-record, and image sync implementation now lives
in `app.integrations.valve.game_data_sync`. The legacy
`scripts/sync_game_data.py` remains a thin entrypoint to that module. This is a
code relocation: request selection, normalization, worker bounds, image handling,
and the default bundled output paths are unchanged. Its `--patch` option still
does not fetch historical hero, item, or ability attributes; those details come
from the current Datafeed endpoints. Importing the application module performs no
sync work. An ordinary sync run creates one `ValveFetchSession` shared by patch
identification, Catalog construction, and patch-record generation. The session
reuses each successful or failed Datafeed method/parameter pair for that run and
limits concurrent calls across its explicit client methods. Its bound covers only
Valve Datafeed calls; the independent image CDN downloads are not included.
The standalone `refresh-images` command uses its own bounded image-download pool.
Catalog construction fetches and validates its six localized summary lists
before running two fixed coordination branches: heroes followed by abilities,
and items with recipe relations. Both branches share the run's session and
converge before the five-file bundle is validated. Detail requests may use the
existing per-phase worker pools; the session still applies the single Datafeed
concurrency ceiling. The separate `refresh-catalog` operation reads and fully
validates the current published snapshot, checks Valve's latest patch, and skips
the full entity build when the patches match unless `--force` is set. A needed
update builds and serializes the original five-file bundle in a temporary data-root
directory and publishes it through `CatalogSnapshotStore`; only the atomic pointer
switch makes it current. Invalid local pointers or snapshots are replaceable after
a successful build, while storage IO errors stop the operation. This command uses
the data-root lock and one bounded session, without Redis or the guide lock. On
the first WSL `refresh-all`, Valve still reported `7.41f`, so entity fetching was
skipped and revision `d0446e97add94e0fb29a30fdf4cc0905` remained current.
`refresh-patches`
independently checks Valve's latest patch and writes the legacy patch-record shape
to `patches/<patch_with_underscores>.json` using a same-directory temporary file
and atomic replacement. A valid existing record is skipped unless `--force` is
set; corrupt or missing records are rebuilt while other patch files are retained.
Its SHA-256 identifies saved content, independently of the Catalog revision and
patch number. The WSL run wrote 100 changes for `7.41f`. It does not require a Catalog, scan all history, or fetch historical
entity attributes. `refresh-images` reads one fully validated current Catalog
snapshot and stores selected Valve PNG bytes under content-hash filenames in
`images/assets/`, then atomically publishes a manifest. Matching local assets are
skipped; failed downloads preserve old manifest entries and do not block other
targets. It uses the data-root lock and a separate worker limit, without Redis,
Datafeed, or the guide lock. The first WSL run downloaded 1,338 of 1,488 targets;
150 ability images returned `download_failed`. Configured API presentation reads this
manifest per answer match and emits content-hash image URLs; the hash route serves
retained assets independently of the current manifest.

The manual `refresh-all` command acquires the data-root lock and holds it through
cancellation cleanup. It runs Catalog, patch records, and the serial file-guide
refresher concurrently. Catalog
and patch records share one Datafeed session and its `--workers` ceiling; images
start only after Catalog succeeds or skips, and use the independent
`--image-workers` ceiling. Catalog failure blocks images, while patch and guide
failures do not cancel other modules. Module reports keep their component fields;
the command returns a partial status when some modules fail or report partial
success. The first WSL run ended `partial`: Catalog skipped at patch `7.41f`, patch
notes updated with 100 changes, guides succeeded for 127 heroes with 763 requests,
and images had 150 ability-image failures after 1,338 downloads. The WSL API reads
the persistent volume read-only; a manual API-only recreation retained Catalog,
guide, and image reads. Its daily timer is enabled but has not fired. Production
migration, deployment, and scheduling remain pending.

```text
schedule -> updater -> persistent data
                         ↓
                 API hot reload / file reads
                         ↓
                 business Service -> tool result
```

With a configured data directory, composition and catalog consumers receive the
loader's current repository. `catalog.lookup` captures one repository per
invocation and `hero.guide` creates one resolver before its first cache read;
each operation keeps that reference for its full duration. The configured
snapshot backs the internal entity-name resolver and catalog query capability.
Publishing a Catalog never rewrites previously generated Artifacts. API processes
may detect a Catalog publication at different checks within the 30-second
interval; the design does not promise a simultaneous fleet-wide switch.

The current code also retains a server-side `DotaVisualEntityEnricher` that
matches answer text against catalog and team names and stores
`catalog_visual_entities` metadata. This is current implementation behavior, not
the accepted target for entity display. The normal `/transport` message body
remains canonical Markdown; the new design below replaces name-based association
with references explicitly included beside identified entities. Existing local
Catalog lookup, image-manifest reading, content-addressed image assets, and the
hash-serving route can be reused without bringing name matching into the new path.

### Explicit entity display (directory, capability injection, API, renderer, and model guidance implemented)

The target data flow is:

```text
Capability obtains an explicitly identified entity
  -> local display directory supplies its display_ref
  -> the reference follows that entity in the capability result or Artifact
  -> the model explicitly cites the returned reference in its final answer
  -> Product parses complete display references in batches
  -> frontend renders the latest name and any available local image
```

Capabilities attach references only at fields whose entity identity they already
know. They do not scan arbitrary JSON or infer an entity from a name, acronym, or
image filename. The display directory is shared across sessions and reuses the
existing Catalog and local image resources. The shared-data update task writes
display records and assets; chat requests read them only and never download or
refresh images. The API reads the shared directory through its read-only data
mount.

Provider adapters retain source transport and source facts; they do not choose
presentation. Runtime does not select images, layout entities, or parse
display-reference Markdown. The shared product prompt tells the model to copy a
reference only from the matching entity object's program-supplied `display_ref`,
never to construct one from text or IDs, and to use references sparingly in the
final answer. The presentation layer consumes those references, while generic
Artifact tools preserve them without resolving them. The detailed reference syntax belongs to
[`agent/product_run_state.md`](agent/product_run_state.md), and record/update
semantics belong to [`DATA.md`](DATA.md). Real-model placement quality remains
subject to separate observation.

Persistent Dota image URLs include the asset SHA-256. The read-only API route
validates the requested hash, PNG signature, size limit, and bytes before serving
with immutable cache headers. It resolves the file by hash rather than requiring
the hash to remain in the current manifest, so retained historical images continue
to serve old answer URLs after a manifest change. Content hashes are independent of
Catalog revisions and patch numbers.

When `DOTAMIND_DATA_DIR` is unset, the API uses its existing bundled catalog
repository. When set, it must name an absolute path containing a valid published
snapshot; startup does not create or initialize the directory and does not fall
back to bundled data on error. The API also reads guide partitions from this same
root, without falling back to Redis when a partition is missing or invalid. In
WSL, the fresh data root has been initialized, the API overlay is active with a
read-only mount, and the unified timer is enabled; the old Redis guide timer is
disabled. The timer's first scheduled firing has not yet been observed. No Redis
guide migration was run; the prior Docker Desktop data was left untouched.
Production still needs its own data root, migration decision, Compose cutover, and
timer installation. Real image downloads and API-container persistence were
verified locally in WSL. These changes do not alter the session Artifact storage
contract.
These changes do not alter the session Artifact storage contract.

## Runtime boundary

The Controller owns the model-authored ExecutionPlan shape, reference validation,
and capability-boundary errors. The execution runtime owns budgets, retries,
tracing, and persistence. Complete-request context capacity and automatic
compaction govern effective history; there is no independent cumulative Raw
admission budget. Execution has no step-count ceiling; Runtime retains
step numbering for traces, while the execution deadline, cancellation, plan
completion, and existing context-capacity or error exits control its lifecycle.
Steps-pressure calculations remain available for isolated tests, but production
Runtime does not supply a step budget.

The model-output and response-recovery contract is owned by
[`agent/model_output_and_recovery.md`](agent/model_output_and_recovery.md).
Dynamic output budgets, strict Adapter-side tool-call batch classification,
rejected-batch history encoding, paired non-execution feedback, and bounded
Runtime correction through execution finalization are implemented and
offline-tested. A rejected batch never reaches ToolRegistry. Ordinary valid-JSON
calls still use ToolRegistry schema and business validation; exhausted correction
enters Answer Stage using reliable results. A primary or degraded answer ending
with `finish_reason=length` fails that attempt and follows the existing
replacement path; degraded truncation reaches deterministic fallback. This is
offline-tested, while live Provider compatibility has not been verified.

Execution and answering have separate wall-clock deadlines. The execution
deadline defaults to 300 seconds and the answer deadline defaults to 60 seconds;
each can be configured from the repository-root `.env` with
`DOTAMIND_EXECUTION_DEADLINE_SECONDS` and
`DOTAMIND_ANSWER_DEADLINE_SECONDS`. Answer context preparation, compaction and
recovery, the primary response, and a degraded response share one answer
deadline. A degraded attempt never resets that budget, and an exhausted budget
uses the existing no-model fallback. Runtime prompts are ephemeral request
projections: execution prompts include time pressure and available tools, while
answer prompts include their own time-pressure snapshot and say tools are
unavailable.

`QueryContext` is intentionally empty until a real cross-tool concern is
designed. The model-authored `ExecutionPlan` is validated as received; no
provider-specific or sample-size mutation is applied afterward.

## Product chat state and transport

Runtime events are projected into a product-owned Run State before transport.
Execution outcome, canonical answer readiness, and dialogue persistence are
separate facts; a storage failure does not turn a completed Runtime into a failed
execution. Runtime must not depend on assistant-ui or presentation state.

The execution-commentary data path is implemented: Runtime publishes confirmed
execution commentary, tool lifecycle, stage, and timing facts; Product Run State
projects bounded ordered activities and authoritative timing; AssistantTransport
replicates product state; the converter places it in message metadata; and the
process panel presents a compact timeline with a locally advancing execution
timer, fixed backend duration, confirmed Chinese tool labels, adjacent-call
grouping, and one-time folding on entry to Answer Stage. Runtime does not choose
presentation labels, merge display groups, or control folding. Product projection
does not infer or summarize model text, and the frontend does not infer model
thoughts from tool names. The display is fixture-tested; observation of real model
commentary remains pending.
Final-answer deltas remain on their independent streaming path. The detailed
contract is in [`agent/product_run_state.md`](agent/product_run_state.md).

The production chat path uses AssistantTransport for state replication and a
frontend converter for message integration. A page-lifetime registry owns each
thread's connection and local Run State; changing the selected thread does not
cancel another thread's stream. The sidebar's session unread indicators are
browser-local and update independently of session-list reloads. Process activity
is presentation-only: it reads ordered Run State metadata while canonical answer
text remains in the assistant message body. The obsolete product-chat NDJSON
route and its event adapters have been removed. The separate `/runs` Runtime test
event stream remains for the Test Observer and is not a chat transport. The state
contract, ephemeral activity, canonical
history/metadata boundary, and phase acceptance are owned by
[`agent/product_run_state.md`](agent/product_run_state.md).

## 首页赛事与输入框查询模式（四种模式已实现）

首页赛事列表走普通后端数据接口，不调用模型。后端查询服务通过现有
PandaScore Provider 层获取 Series 及必要的冠军身份事实，并将排序后的候选
和刷新元数据放在共享缓存中；首页读取同一份最多十条候选，首页展示前五条。
读取接口为 `GET /api/v1/home/recent-series`，手动更新接口为
`POST /api/v1/home/recent-series/refresh`。普通 GET 在后台刷新时立即返回过期快照；POST
绕过十分钟新鲜缓存并等待结果，若已有刷新任务则复用它。服务使用同一个进程内任务和锁；Redis
持久化 60 秒手动冷却，失败后 600 秒限频仍有效。响应中的后端时间和允许时间供前端展示倒计时，
不由浏览器自行推算策略。

Series 原始对象中的 `league.name` 经 Provider 生命周期模型、近期候选、Redis
快照和只读 API 传递到前端；缺失或无效时为 `null`。前端只用来源值组合
`League · Series` 显示名和普通查询文本，不改写共享模型工具的 Series DTO。

首页 Series 点击会发送包含显示名、Series 语义和 ID 的普通文本，并保留输入框草稿及
查询模式。Composer 持有赛事、英雄、玩家、单局模式状态；选择模式后在输入框首行开头显示
不可编辑提示，不改动草稿；发送时在原正文前附加完整的一行纯文本模式说明。该入口不预排工具调用、不增加结构化消息
或第二套聊天协议；消息使用现有 AssistantTransport 和 Agent Runtime。前端文本生成与
草稿行为已有自动化验证，真实模型查询表现未验证。

```text
首页 -> 普通后端接口 -> Series 候选服务 <-> 共享缓存
                                |
                                +-> 现有 PandaScore Provider 层

赛事点击 -> 普通聊天文本 -> AssistantTransport -> Agent Runtime -> Agent
输入框模式 -> 纯文本说明 + Composer 文本 -> AssistantTransport -> Agent Runtime -> Agent
```

首页最多十条候选只在欢迎页展示前五条，不另设十条展开层。最近赛事显式刷新与错误重试由专用 POST
完成，不触发模型调用。手动刷新等待后台任务时保留旧列表并显示“正在刷新...”；结束后依据 `fresh`、
`stale` 或 `unavailable`、错误码与真实 `retrieved_at` 展示结果。冷却由服务端共享状态控制，前端倒计时
只负责展示。刷新失败不清除旧列表，也不把 HTTP 200 一律视为成功。Composer 主动发送在消息交给运行时后清理
未被用户改动的草稿并返回普通模式；准备失败保留草稿和模式，会话切换重置模式。

聊天壳统一持有左侧聊天记录与右侧 Trace 的展开状态：桌面从 1024px 起采用可独立收起的
三列，抽屉宽度以 180ms ease-out 动画变化；窄屏使用互斥覆盖抽屉和同步淡入淡出的遮罩。
抽屉关闭时立即 inert，收放不重挂载 RuntimeProvider 或 Thread。Trace 列表仅在右抽屉
逻辑打开时读取；Test Observer 仍保持独立。顶部 header 被删除，侧栏切换按钮在中间聊天
区域的两侧悬浮定位，错误提示仅在需要时浮层呈现。

Series 生命周期读取、候选组装、共享 Redis 缓存、普通只读接口、首页五条展示、
赛事点击链路、四种输入模式及两个会话抽屉已实现。不改变工具注册、Artifact 或 Run State
契约。

## Migration order

1. Keep the Artifact baseline green.
2. Add one domain capability with its own input/output contract and tests.
3. Register it explicitly after its boundary is accepted.
4. Delete transitional code instead of preserving compatibility shims.

## Rejected designs

- provider-named model tool namespaces;
- one universal open resource selector;
- a universal cross-provider business DTO;
- transport-private IDs as general capability inputs;
- scenario-specific workflows embedded in the generic registry;
- provider routers before a second concrete implementation exists;
- Artifact corpus discovery or hidden provider fetches.

## Cross-source esports game identity resolution (implemented; opt-in)

The offline resolver, bounded Provider read flow, capability Service, and
Artifact-continuation tool are implemented. Product composition registers the
tool only when `DOTAMIND_GAME_RESOLUTION_ENABLED=true`,
`DOTAMIND_OPENDOTA_ENABLED=true`, and a PandaScore token is configured. It remains
absent from the default registry. The product path connects a selected
PandaScore Match/Game to the existing `game.detail` input:

```text
Model
  → esports.match.search
      → Match-search Artifact
  → esports.game.resolve(match_artifact_ref, match_path, game_position)
      → validate the Artifact and selected Match; extract its ID
      → Resolution Service
          → obtain trusted PandaScore Match context
          → retrieve a bounded OpenDota League candidate set
          → enumerate candidate games
          → filter candidates for the selected PandaScore Game
          → read a small number of candidate details only when evidence is needed
          → compare selected-game evidence and any supplied mapping constraints
      → selected valve_game_id, selection basis and warnings, or an explicit unresolved result
  → model may call game.detail(valve_game_id)
      → existing OpenDota game-detail capability
      → generic Artifact handling
```

The resolution target is one game; its parent Match provides context. More than
one League or match candidate may remain after initial filtering, so the Service
must not choose one merely because it is first or unique before completing the
selected search scope. Once that complete scope yields one distinct candidate,
validated in-window detail permits selection with participant/winner uncertainty
warnings unless an explicit contradiction exists. `resolved` means selected;
`verified_identity` and `unique_candidate` distinguish completed checks from
selection with incomplete checks. Evidence statuses and original facts are not
upgraded to manufacture verification. Candidate
details are fetched only when they can add evidence. Search and detail reads are
bounded; continued pagination or time-window expansion cannot run indefinitely.
No-candidate, insufficient-evidence, ambiguity, source failure, and exhausted
budget remain distinguishable. A failure for one selected game does not clear
other resolved games. There is no invariant that all games in a Match share one
OpenDota `series_id` or the same in-game Team IDs.

| Layer | Owns | Does not own |
|---|---|---|
| Resolution Service | Trusted context, request coordination, finite budgets, cancellation, and result organization | Asking the model to invent matching fields or maintaining a second Runtime state machine |
| Provider implementation and adapters | Source requests, response validation, and source-field preservation | Deciding the answer or hiding a failed request as an empty success |
| Offline identity-resolution logic | Comparing collected facts, candidate filtering, and consistency checks | Network requests, model calls, or Artifact reads/writes |

The resolver is a small, independently testable responsibility; this design does
not require an abstract base class, strategy plugin, provider router, or a
particular package layout. Runtime and generic Artifact primitives remain
unaware of esports matching semantics. The identity evidence, recovery rules,
and external observations belong to [`DATA.md`](DATA.md) and its linked
[`cross-source reference`](reference/opendota-cross-source-identity.md).

Services reuse one PandaScore client and the same OpenDota game-detail adapter
for candidate-detail reads and `game.detail`. Registry composition binds the
continuation to that registry's existing session Artifact store; the shared
Services container does not own session state. The continuation currently passes
an empty confirmed-mapping map, so duplicate assignment checks across calls and
whole-Match consistency are not provided. Request-count limits do not override
the Runtime tool timeout or original execution deadline. Offline product-chain
acceptance uses saved historical responses through strict HTTP mocks and does not
establish live Provider availability or real-model behavior.

Product composition binds a fresh internal source-read cache to each Runtime run
through a generic request-resource scope. Match context, the OpenDota League
directory, League match lists, and validated game records are reused within that
run, including candidate-detail reuse by `game.detail`. Successful empty results
are reusable; errors and cancelled reads are not cached. Adapter instances and
source identities isolate keys, per-key locks coalesce concurrent reads, and
callers receive independent copies retaining original record retrieval times.
The cache is discarded when the run completes, fails, is cancelled, or its stream
is closed; sessions and later requests do not share it. It owns no model-facing
Artifact or identity decision. Logical adapter-read budgets still count cache
hits; request logs separately report actual source-read attempts and cache hits.

Within each resolution, independent League-list reads and then independent
candidate-detail reads use bounded workers (default 4, configured by
`DOTAMIND_GAME_RESOLUTION_MAX_CONCURRENCY`). The two phases remain sequential and
retain their full budget prechecks. Completion order does not change source order
or matching decisions. Failure or caller cancellation stops queued work and joins
cancelled active workers before propagating the original error; no partial scope
can produce success. This is a per-call concurrency bound, not a global limiter.

Name comparison permits the small terminal-word list `esports`, `e-sports`, and
`gaming`, with nonempty cores and no participant collisions; associations retain
their original names and matching method. Shared product instructions carry the
selection/warning meaning into execution, primary/rebuilt and degraded answers.
Tool descriptions agree: models assess existing evidence, may retrieve detail
for a selected ID, preserve uncertainty, and cannot pick an ID from unresolved
evidence. No model-driven identity re-query or new confirmation tool is required.

## Steam player and game-detail boundaries

The `capabilities/player` and `capabilities/game` contracts define closed
inputs, provenance, and JSON outputs. `player.profile` and
`player.recent_games` share the STRATZ GraphQL client and register only when a
STRATZ token is configured. The recent-games adapter sends `take`,
`orderBy: DESC`, and `playerList: SINGLE`, validates the outer and row Steam32
identities, and preserves selected match/player source objects as JSON. The
historical schema inventory identifies `DESC` as date ordering; local sorting
only stabilizes the returned order after STRATZ has selected the bounded
subset. A live cross-check for match `8960882635` returned the same ID, start
time, and duration from STRATZ `match(id)` and OpenDota. A live `player.matches`
query for one participant requested the newest 20 with `orderBy: DESC`; raw
STRATZ timestamps were nonincreasing and each row contained only that account.
The supplied match predates that sample and was not among those 20. This is
single-account sample evidence, not a guarantee for every account or general
provider availability. `game.detail` is implemented by an opt-in OpenDota
adapter. It requires the returned `match_id` to match the requested Valve ID,
checks known fields only when present, and currently preserves the complete
source object for the generic Artifact processor. The accepted target replaces
that public object with the governed DTO in
[`agent/game_detail_data.md`](agent/game_detail_data.md). Missing process
data does not trigger replay parsing. OpenDota composition and registry
construction are network-free.
Steam32 and PandaScore player identities remain separate unless a future
evidence-backed identity capability is designed.

The account-to-game workflow is composed by the existing model-driven Runtime,
not a dedicated player-analysis pipeline. `player.recent_games` supplies the
bounded list, `game.detail` receives only a selected Valve game ID, and the
player row is located by exact `account_id`. Existing conversation history and
generic Artifact handling support ordinal follow-ups and large details; no
second session store or automatic fetch of every listed match is introduced.
The local `catalog.lookup` capability resolves hero/item display labels from
the bundled Valve snapshot without changing provider observations or making
network requests.
