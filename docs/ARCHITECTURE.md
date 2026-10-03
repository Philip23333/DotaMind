# Architecture

## Status

The tool layer is in a clean-slate rebuild. The default LLM-facing registry
currently contains the generic Artifact tools and the closed
`esports.league.search`, `esports.series.search`,
`esports.series.teams`, `esports.tournament.search`,
`esports.match.search`, `esports.team.search`, and `esports.player.search`
capabilities. When explicitly enabled and discovered during application
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
component is integrated into `hero.guide`; `game.detail` integration remains
pending.

The model-facing contract never exposes wire routes, credentials, pagination
syntax, or transport-private IDs. A single provider does not justify a router or
plugin framework.

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
descriptions and argument schemas remain in execution's tool declarations.
Earlier assistant capability claims do not override the current inventory.

Answer requests still use `tools=[]`: execution has ended, while the product's
capabilities have not disappeared. The inventory grants no permission to call
tools in that stage and proves neither cache availability nor lookup success.
Answer evidence comes from the conversation and execution results. Runtime's
existing shared-instruction request builders carry this information without a
second registry or capability manager.

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

## Hero guide data flow (Redis/file queries and file refresh/import implemented; migration and scheduling pending)

The synchronous D2PT HTTP client is implemented with `urllib.request`; its
deterministic tests use an injected opener and make no live request. It sends
the verified request headers and performs bounded transport and minimal
response-shape validation. Pure Pub and Pro parsers project source rows into the
existing DTOs. The independent `RedisHeroGuideCache` stores each complete source
snapshot, including exact response bytes, parsed source rows, and DTO projection.
Pub keys use hero plus position; Pro keys use hero and replace all positions as
one snapshot. A successful publish replaces the complete snapshot with one
Redis `HSET`; callers record a failed fetch/parse by updating only attempt
metadata, which keeps the last successful snapshot. Reads use one `HGETALL`.
Keys have no TTL.
The Redis cache accepts an injected client and does not create connections. At
startup, a configured `DOTAMIND_DATA_DIR` selects `FileHeroGuideCache`; otherwise
the application wraps its existing Redis client when one is configured. The same
data root is used for the Catalog loader and guide files. Composition registers
the `hero.guide` Service/tool only when a reader is supplied. File mode takes
priority over Redis and never falls back to it for missing or invalid partitions.
An internal `HeroGuideRefresher` now connects the injected D2PT client and cache:
it fetches the hero list once, then requests Pub positions 1 through 5 and Pro
once per hero in source order. Requests run sequentially through
`asyncio.to_thread`; after every normal response or `D2PTError`, the executor
waits one second before parsing, publishing, recording failure, or starting the
next request. Successful full parses publish one whole snapshot. A fetch or parse
failure updates only that partition's attempt metadata, preserving its last good
snapshot; a cache write failure aborts the refresh. Cancellation and unexpected
programming errors propagate. An operator-only CLI runs this executor on demand
with the API container's `DOTAMIND_REDIS_URL`. It acquires a non-blocking `flock`
at `/tmp/dotamind-hero-guide-refresh.lock` before constructing resources, pings
Redis, runs one refresh, drains the default executor, closes its Redis client,
then releases the lock. The lock coordinates CLI processes sharing that
container's `/tmp`; it is not distributed and does not coordinate multiple API
containers. SIGINT/SIGTERM cancel the refresh coroutine; an urllib request
already running in a worker thread is allowed to finish before Redis closes and
the lock is released. The CLI emits one credential-safe JSON result and fixed
exit codes. A systemd service/timer template invokes the CLI through
`docker compose exec`; application startup is not wired to refresh. Repository
templates do not establish the installation state of a particular host. A
historical local WSL deployment record reports a completed full refresh and an
enabled guide timer, but does not establish that the timer fired successfully or
that shared file storage and API hot reload were deployed. See the operations
and evaluation references for the environment-specific evidence.

The cache's persistence across process or Redis restarts depends on the deployed
Redis AOF and persistent volume configuration. Offline tests use a fake Redis
and do not verify AOF recovery or a live Redis deployment. The shared guide
cache remains separate from session Artifacts.

The standalone `FileHeroGuideCache` stores one complete Pub or Pro entry per
file, including base64-encoded raw response bytes, source rows, parsed DTOs,
retrieval time, and latest attempt/error state. It uses a same-directory
temporary file and `os.replace` for each partition. `migrate_redis_guides()` is
an offline-verifiable component that reads selected entries through
`RedisHeroGuideCache`, imports absent file partitions, skips identical entries,
rejects conflicts, and compares imported entries by reading them back. The
`migrate-guides` operator command invokes this importer. The `HeroGuideRefresher`
depends on a minimal `HeroGuideWriter` protocol, and
`python -m app.vnext.data_updates refresh-guides --data-dir ...` runs the same
serial fetch/parse algorithm with `FileHeroGuideCache` as its writer. It takes the
data-root update lock and then the existing container-local Redis refresh lock,
so it does not overlap with the legacy command in that API container. This new
entrypoint has only offline fake-client acceptance; it has not been deployed or
used for a real refresh.

The migration period has two operator refresh entrypoints:

```text
legacy CLI or existing timer
  -> container-local refresh lock
  -> HeroGuideRefresher
  -> Redis guide partitions

new data_updates CLI
  -> data-root update lock, then container-local refresh lock
  -> HeroGuideRefresher
  -> file guide partitions
```

The new and legacy paths are separate migration-stage entrypoints and must not be
installed together as daily jobs. The existing timer still runs the Redis
command. The API reads files when `DOTAMIND_DATA_DIR` is configured and uses Redis when
the data directory is unset and Redis is configured; without either store the
tool is absent. No guide read falls back between stores. The refresh lock only
coordinates processes sharing one API container; multi-container coordination is
not implemented. Neither command is an HTTP endpoint or model-facing tool. The
repository timer template is deployment-specific, and its presence does not
describe local WSL or other installed service state.

Each implemented cache snapshot records its retrieval time; source-provided
update fields remain in the retained source rows and projections. The cache
entry separately records the latest attempt time and stable error code. It does
not calculate availability or staleness. The implemented Guide Service marks a
snapshot stale at an age of 36 hours or after a failed refresh attempt. The
repository's guide-only timer template is configured for 03:00 Asia/Shanghai;
installed schedules and their execution history are host-specific. The lock
prevents overlap only among CLI processes in one API container.

The current online guide query path is read-only:

```text
Model -> hero.guide(hero_id, position, section)
      -> Guide Service -> persistent guide cache
      -> hero/position filter and section projection
      -> injected EntityNameResolver -> local Valve catalog snapshot
      -> DTO with source IDs, local names, and catalog_version
      -> bounded tool result or existing generic Artifact externalization
```

With `DOTAMIND_DATA_DIR`, application startup injects a `FileHeroGuideCache` over
that root; without it, the reader wraps the lifespan's existing `vnext_redis`
client when available. Composition does not open or close Redis connections.
The tool is registered when either configured reader is supplied and remains
unregistered when neither data directory nor Redis is configured. The Guide
Service reads Pub and Pro once each for every query, filters Pro examples to the
exact hero and position, and applies the requested section without changing source status or
candidate totals. It does not cache file contents, write or repair guide files,
call D2PT, or start a refresh. Missing or stale partitions are reported while
any readable source data is returned; if both cache reads fail, the tool returns
a fixed execution error. The Guide Service
resolves only visible hero, item, and ability IDs after section projection, in up
to one batch per kind. It does not store names in guide snapshots or invoke the
`catalog.lookup` tool. The top-level catalog version identifies the local Valve
snapshot; a batch reporting a different version causes a fixed `ValueError`. The shared,
cross-session guide cache is distinct from the process-local, session-owned
Artifact store: Artifacts continue to hold oversized logical tool responses and
are not the durable guide cache.

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
from the environment. A non-blocking data-root lock protects all commands, and
guide migration also takes the existing refresh lock in data-lock-then-refresh-lock
order. File guide refresh does not require a catalog snapshot or Redis URL; it
takes the same two locks before constructing D2PT and file-cache resources. The
refresh lock is container-local, so migration and file refresh must run in the
same API container as the legacy guide refresh CLI. The file guide refresh command
has offline fake-client tests and completed a real WSL run for 127 heroes. The WSL
data root was initialized from the bundled Catalog; no Redis guide migration was
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

The manual `refresh-all` command acquires the data-root lock followed by the
legacy guide-refresh lock and holds both through cancellation cleanup. It runs
Catalog, patch records, and the serial file-guide refresher concurrently. Catalog
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

With a configured data directory, composition and answer presentation receive the
same callable that returns the loader's current repository. `catalog.lookup`
captures one repository per invocation; `hero.guide` creates one resolver before
its first cache read; and each answer-text match obtains one repository. Each
operation keeps that reference for its full duration, so a result cannot mix
catalog versions. Presentation rebuilds its current name-match records when the
repository object changes, including publications with the same patch number.

The configured snapshot backs the internal entity-name resolver, catalog query
capability, and chat name matching. In persistent data mode, each answer-text match
captures one current Catalog repository and reads the image manifest once. A valid
entry is used only when its entity ID and internal name match the Catalog and its
content-hash asset exists; the source patch does not need to match the current
Catalog patch. A new manifest affects the next match without restarting the API.
On manifest read or validation failure, the process keeps its last valid manifest;
if none has been valid, catalog images are omitted. It never falls back to bundled
Catalog images in persistent mode. With no configured data directory, the existing
bundled image behavior remains. Team images are unchanged. Publishing a Catalog
never rewrites previously generated Artifacts. API processes may detect a Catalog
publication at different checks within the 30-second interval; the design does not
promise a simultaneous fleet-wide switch.

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

The Controller owns decision shape, schema adherence, reference validation, and
capability-boundary errors. The execution runtime owns budgets, retries,
tracing, and persistence. Complete-request context capacity and automatic
compaction govern effective history; there is no independent cumulative Raw
admission budget. Execution has no step-count ceiling; Runtime retains
step numbering for traces, while the execution deadline, cancellation, plan
completion, and existing context-capacity or error exits control its lifecycle.
Steps-pressure calculations remain available for isolated tests, but production
Runtime does not supply a step budget.

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

## 首页赛事与快捷查询（Series 入口已实现）

首页赛事列表走普通后端数据接口，不调用模型。后端查询服务通过现有
PandaScore Provider 层获取 Series 及必要的冠军身份事实，并将排序后的候选
和刷新元数据放在共享缓存中；首页读取同一份最多十条候选，首页展示前五条。
接口为 `GET /api/v1/home/recent-series`。

Series 原始对象中的 `league.name` 经 Provider 生命周期模型、近期候选、Redis
快照和只读 API 传递到前端；缺失或无效时为 `null`。前端只用来源值组合
`League · Series` 显示名和普通查询文本，不改写共享模型工具的 Series DTO。

目前赛事点击会发送包含显示名、Series 语义和 ID 的普通文本。其他快捷面板仍是
产品设计目标，尚未接入。已实现的入口只组织用户输入，不预排工具调用、不增加
结构化消息或第二套聊天协议；消息使用现有 AssistantTransport 和 Agent Runtime。

```text
首页 -> 普通后端接口 -> Series 候选服务 <-> 共享缓存
                                |
                                +-> 现有 PandaScore Provider 层

赛事点击 -> 普通聊天文本 -> AssistantTransport -> Agent Runtime -> Agent
```

首页列表不触发模型调用。聊天壳统一持有左侧聊天记录与右侧 Trace 的展开状态：
桌面从 1024px 起采用可独立收起的三列，窄屏使用互斥覆盖抽屉。抽屉开合不重挂载
RuntimeProvider 或 Thread。Trace 列表仅在抽屉打开时按当前会话读取；Test Observer
仍保持独立。

Series 生命周期读取、候选组装、共享 Redis 缓存、普通只读接口、首页五条展示和
赛事点击链路已实现。英雄、玩家和单局输入面板仍待实现。不改变工具注册、Artifact
或 Run State 契约。

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

## Steam player and game-detail boundaries

The `capabilities/player` and `capabilities/game` contracts define closed
inputs, provenance, and source-shaped JSON outputs. `player.profile` and
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
checks known fields only when present, and preserves the complete source object
for the generic Artifact processor. Missing process data does not trigger
replay parsing. OpenDota composition and registry construction are network-free.
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
