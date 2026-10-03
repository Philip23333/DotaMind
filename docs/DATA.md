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
written into guide snapshots. Old snapshots remain readable because enrichment
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

When `DOTAMIND_DATA_DIR` is unset, the API loads its entity catalog from files
bundled with the API code and reads guides from Redis when configured. When set
to an absolute path, the API requires a valid published catalog snapshot there,
uses the background loader, and reads guide partitions from the same data root.
File mode takes priority over Redis; a missing or invalid guide file does not
fall back to Redis. With neither a data directory nor Redis configured,
`hero.guide` is not registered. The legacy Redis refresh CLI still writes Redis
snapshots.
The file-backed `refresh-guides` operator command is implemented, but has only
offline fake-client coverage and has not been used for a real D2PT refresh. The
persistent catalog and guide stores are implemented, as are manual initialization
and Redis-import commands, but neither initialization nor migration has been run
against an operational data root or Redis cache. The conceptual data areas are
`catalog`, `patches`, `images`, and `guides`.

## 首页近期赛事候选

后端返回最多十条 Series 候选，首页展示其前五条；前端不再提供候选展开层。候选保留足以展示
和继续查询的来源事实：Series ID、Series 身份、名称、League 名称、状态、开始／结束时间，
以及可用时的冠军战队名称。首页使用候选顺序中的前五条。赛事仍是 Series
届次，不转换成 Tournament 或 Match。

候选按状态分组排序：进行中的 Series 按开始时间倒序优先；数量不足十条时，
使用已结束 Series 按结束时间倒序补齐。按 Series ID 去重。相同状态内，缺少
相应排序日期的记录排在有日期的记录之后；数据不足十条时返回实际数量，不
填充虚构记录。

冠军优先从明确的 Series 获胜对象解析。只有获胜对象类型为 `Team` 且战队名称
解析成功时，候选才包含冠军名称。若 past Series 的 `winner_id` 为 `null`，服务
按 Series ID 查询其 Tournament，取名称经首尾空格去除并大小写折叠后精确等于
`playoffs` 的阶段；仅当该阶段明确给出 `winner_type="Team"` 和 `winner_id`，且
战队名称解析成功时，才补充冠军。`Finals`、`Main Event` 等别名不匹配，也不查询
Match 或推断赛制。Series 有非空胜者 ID 但类型不是 Team，或 Series Team 名称解析
失败时，不使用 Tournament 覆盖。未结束、获胜对象缺失或名称无法解析时不显示冠军。

候选的 `champion_source` 记录成功名称的来源（`series` 或 `tournament`）；来自
Tournament 时，`champion_tournament_id` 保留来源 ID。没有解析出冠军名称时这两个
字段与 `champion_name` 均为 `null`。旧 Redis 快照缺少来源字段时使用 `null` 默认值；
保留旧冠军名称，不反推其来源。只有最终入选的最多十条候选会触发 Playoffs 查询。
一次刷新内 Team 名称按 ID 复用。Playoffs 查询或 Team 名称查询发生已知 Provider
错误时，保留赛事行、留空冠军，不把可选补全错误登记为整份列表失败。

候选使用十分钟共享缓存和按需刷新。已有成功快照过期时，请求立即返回旧快照，
并启动最多一个由服务持有的后台刷新；刷新结束不会推送或改写已返回的响应。冷
缓存请求等待共享刷新任务，并发冷缓存请求复用该任务。一次失败尝试结束后的
600 秒内不再刷新，之后由下一次请求触发。Redis 中的失败元数据使服务重建后仍
能遵守间隔；若写入失败，当前服务实例保留失败时间。刷新任务只在单个 API 进程
内合并，不构成跨进程锁。成功获取时间与最新刷新尝试状态分别记录，以区分数据
获取时间和最近刷新结果。成功取得空列表表示有效空数据；请求失败表示数据不可
用，不能互相替代。没有成功缓存且刷新失败时也必须报告不可用状态。下面记录当前
后端实现采用的缓存、接口和冠军名称查询方式。

Provider 生命周期结果中的 `league_name` 只取 Series 原始响应的 `league.name`。
对象或名称缺失、名称不是字符串或去除首尾空格后为空时，值为 `null`。不额外
查询 League、不翻译，也不把它拼回共享 `SeriesDTO.name`。近期候选、Redis 快照和
HTTP 项目响应保留该字段。字段设有 `null` 默认值，旧 Redis 快照缺少它仍可读取；
前端也将旧响应中缺失的字段归一为 `null`。

### 当前后端实现

首页读取接口为 `GET /api/v1/home/recent-series`。响应包含 `status`、`items`、
`retrieved_at`、`last_attempt_at` 和安全错误码 `last_error`；状态为 `fresh`、
`stale` 或 `unavailable`。候选字段为 Series ID、展示名称、`league_name`、生命
周期、起止时间、可选冠军战队名称及其来源字段。`name` 优先取 `full_name`，缺失时取 `name`；
`league_name` 来自 Series 响应的 `league.name`。前端以可用的 League 和 Series
名称组合显示与查询用名，不能根据文本猜测 League。

Provider 读取分别调用 running 与 past Series 生命周期端点，候选服务按开始／结束
时间本地排序，日期缺失项排在有日期项之后，稳定保留相同日期的来源顺序；去重后
最多取十条。已结束 Series 缺少 `winner_id` 时额外读取
`GET /dota2/tournaments?filter[serie_id]=<series_id>&page=1&per_page=100`，只使用
名称精确匹配 `Playoffs` 的阶段胜者；Series 自身存在非 Team 胜者时不回退查询。Team
请求失败、结果缺失或名称为空只会省略冠军名称，不阻止赛事候选。冠军来源和
Tournament ID 随首页候选及 Redis 快照保存；旧快照缺失新字段仍可读取。

共享快照存于 Redis。十分钟是基于 `retrieved_at` 的新鲜度窗口；成功快照不设置
Redis TTL，以便刷新失败时继续返回旧数据并标记 `stale`。失败尝试单独更新
`last_attempt_at` 和稳定 `last_error`，有效空列表仍会作为成功快照缓存。没有成功
快照时，来源失败返回 `status="unavailable"`；Redis 不可用或缓存损坏时接口返回
HTTP 503。旧快照在后台 Provider 请求结束前立即返回。冷缓存请求等待同一个刷新
任务，单个请求取消不会取消共享刷新。失败尝试限频 600 秒；Redis 已记录的失败在
服务重建后仍生效，记录失败本身写 Redis 失败时由当前服务实例用本地时间兜底。
应用关闭时先取消并等待首页刷新，再关闭共享 Redis 客户端。刷新任务只在单个 API
进程内合并；没有跨进程刷新锁。

离线测试覆盖 Provider 读取后的 League 名称归一化、排序、去重、冠军条件、空与坏数据区分、缓存旧值
保留、旧值立即返回、冷／热缓存刷新合并、单个等待者取消隔离、600 秒失败间隔、
关闭时任务回收和 HTTP 路由。前端对有／无 League 名称、赛事名缺失和旧响应字段
缺失有离线回归。确定性测试不代表真实 PandaScore 刷新或部署环境中的 Redis 行为
已验收。

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
under a caller-supplied data root. The API loader reads published snapshots when
`DOTAMIND_DATA_DIR` is configured. WSL has initialized a fresh persistent data
root; production data initialization remains pending.

### Valve synchronization module

The existing Valve catalog, patch-record, and image sync implementation is in
`app.integrations.valve.game_data_sync`; `scripts/sync_game_data.py` is a thin
compatibility entrypoint. This change only relocates the code and Chinese hero
alias resource. Requests, normalization, ID filtering, worker bounds, retries,
and image replacement behavior remain unchanged. The module resolves its alias
resource and default Catalog and patch outputs from its own location, independent
of the process working directory. Defaults still write to the repository's
`app/data/catalog` and `app/data/patches`; the persistent snapshot store is not
connected to this sync module.

`--patch` still selects the patch label and patch-notes request; it does not
retrieve historical hero, item, or ability attributes. Those detail endpoints
continue to provide their current data. Importing the module does not create a
client, make a request, create output directories, or run the command. Catalog
construction first fetches and validates all six localized summary lists, then
runs a fixed hero-then-ability branch alongside an item-and-recipe branch. The
branches share one fetch session and merge into the original five-file bundle
before validation. An ordinary CLI run creates one
`ValveFetchSession` with the `--workers` bound and shares it across latest-patch
identification, Catalog construction, and patch-record generation. Within that
run, identical method/parameter requests share one result or exception; each
caller receives a deep copy. The limit applies to Datafeed calls only, not image
CDN downloads. A new run has a new session. `--images-only` reads the local
snapshot and does not create a Datafeed client or session. Patch-version gating
and persistent publication are now available through the separate
`refresh-catalog` operation; the legacy synchronization command above still writes
to the bundled repository paths and does not publish to the configured data root.

`CatalogSnapshotLoader` loads the current complete snapshot at startup and then
checks the pointer revision in the background, defaulting to a 30-second interval.
With `DOTAMIND_DATA_DIR` configured, API startup waits for this first load and
fails if the pointer or snapshot is missing or invalid; it does not initialize a
directory or fall back to bundled data. An unchanged revision does not reload the
five files. A new revision is fully validated before one in-memory snapshot
reference is switched; failed checks or loads keep the last successful snapshot
available. `catalog.lookup`, guide name enrichment, and answer name matching use
the current snapshot, each pinning one repository for its operation. The check
interval does not bound validation or IO time. Offline tests do not establish
power-loss recovery or deployed persistent-volume behavior.

The `refresh-catalog` operation writes one temporary five-file source and
delegates validation and publication to `CatalogSnapshotStore`. It never replaces
the current files one by one. A failed fetch, serialization, or publication leaves
the current pointer unchanged; the store may retain an unreferenced revision if
the final directory was created before pointer replacement failed.

Images are separate best-effort resources. A failed download keeps an existing
image when present, and a missing image does not block catalog publication.
Missing resources can be filled independently without fetching every entity
again. `python -m app.vnext.data_updates refresh-images --data-dir ...` now loads
one complete Catalog snapshot and selects hero, non-recipe item, and eligible
ability images using the existing Valve internal-name rules. It stores raw PNG
bytes at `images/assets/<sha256>.png` and publishes `images/manifest.json` by
atomic replacement. The manifest's kind, entity ID, internal name, content hash,
and last-successful source patch are validated; asset paths are derived from the
validated hash. Matching entries skip downloads, while missing, damaged, renamed,
or patch-stale assets are fetched again. Failed downloads preserve the old image
entry and patch marker; other targets continue. Unrelated manifest entries and
historical hash files are retained. A corrupt manifest stops the operation rather
than rebuilding it. The command uses a separate 1–16 worker bound and has offline
fake-client tests. Its first WSL run downloaded 1,338 of 1,488 targets; 150 ability
images returned `download_failed` and remain eligible for a later attempt. In
persistent mode,
each answer match reads the manifest once and fixes that snapshot for the match.
Entries are matched by image kind and entity ID, then checked against the Catalog
internal name; source patch does not have to equal the current Catalog patch. A
missing entry or asset omits image metadata while preserving text matching. The
reader retains its latest valid manifest after a later read or validation failure;
before any valid read, it returns an empty image set. It does not write, repair, or
fetch resources. Without a configured data directory, the API retains its bundled
image behavior.

Persistent answer images use `/api/v1/assets/dota/by-hash/<sha256>.png`. The route
only operates with `DOTAMIND_DATA_DIR`, reads a bounded file once, and checks PNG
signature and SHA-256 before serving immutable content. It does not require the
hash to remain in the current manifest, so previously published hash files keep
old answer links working. Hashes are independent of Catalog revision and patch.
Patch records are stored by patch version and do not share the catalog snapshot
number.

`python -m app.vnext.data_updates refresh-patches --data-dir /absolute/data/root`
independently checks the latest Valve patch and stores its existing patch-record
format at `patches/<patch_with_underscores>.json`. A valid file for that patch is
skipped unless `--force` is set; a missing or invalid file is fetched and atomically
replaced, preserving other patch files. The report hash is over the saved bytes;
it is distinct from both the patch number and Catalog revision. The command does
not require Catalog initialization, fetch older hero/item/ability attributes, or
fill all historical patch files. It does not update images or guides. The first WSL
run updated patch `7.41f` with 100 changes; the saved content SHA-256 was
`50e10530e0d2de4967df94a1331b43f8f4b13b16ab455cb9a8ca99db099b30df`.

### Unified manual refresh

The command is:

```bash
python -m app.vnext.data_updates refresh-all \
  --data-dir /absolute/data/root --workers 8 --image-workers 8
```

It runs the current Catalog, latest patch-record,
image, and file-guide refresh components in one invocation. `--force` is passed
to Catalog, patch, and image refresh; guides refresh on every run. Catalog and
patch work run in parallel with the guide refresher and share one
`ValveFetchSession`, response cache, and Datafeed concurrency ceiling. The
independent image worker limit controls CDN downloads. Images begin only after
Catalog succeeds or skips; Catalog failure marks images blocked, while patch or
guide failure does not cancel other work. The guide refresher retains its
existing serial hero/request order and one-second post-request wait.

The command acquires `<data_root>/.update.lock` and then the legacy guide-refresh
lock before creating clients or making requests. Both locks remain held through
thread and coroutine cleanup and are released in reverse order. It emits one
ordered module summary and returns success, partial, or failed according to the
module results. The first real WSL run completed as partial: Catalog skipped
because patch `7.41f` was unchanged, patch notes updated, file guides succeeded,
and images downloaded 1,338 targets with 150 ability-image failures. The full
safe report is recorded in the local operations evidence below.

### Persistent Compose and daily update configuration (WSL active; production pending)

Both `compose.wsl.yml` and `compose.prod.yml` give the API an explicit image tag
and define a `data-updater` service in the `maintenance` profile using that same
image. Its safe default command is `--help`; an explicit `run` command is required
to perform work. The updater writes the project-scoped `shared-data` volume at
`/var/lib/dotamind/data`. The separate `compose.data.yml` overlay opts the API
into `DOTAMIND_DATA_DIR` and mounts that volume read-only. Existing ordinary
Compose invocations do not load the overlay and keep their current API mode.

`deploy/systemd/dotamind-data-update.service` and `.timer` describe a one-shot
`refresh-all` run each day at 03:00 Asia/Shanghai. The service uses the production
Compose files, runs with `--rm --no-deps`, and treats only lock-busy exit code 3
as successful. The timer has `Persistent=false`. The WSL service and timer are
installed and active using a local drop-in for the WSL Compose files; the
production templates remain uninstalled. The WSL data root was initialized from
the bundled Catalog and guide data was fetched directly to files without a Redis
migration. See
[`reference/data-update-operations.md`](reference/data-update-operations.md)
for the WSL evidence and production cutover procedure. A failed/partial refresh (exit 4)
is not marked successful, and no automatic API restart is configured. The WSL
timer is active; production cutover remains separate.

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
a same-directory temporary file and `os.replace`; reads do not write, and files
have no TTL. API composition injects this cache when `DOTAMIND_DATA_DIR` is
configured. The query Service does not cache file contents, so each query sees
the latest atomically replaced partition.

The callable `migrate_redis_guides()` validates the complete hero list before
I/O, reads Pub positions 1 through 5 and then Pro through the existing Redis
cache API, imports complete non-missing entries, and reads each imported or
already-present file back for value equality. Identical files are safe to skip;
conflicting or corrupt targets stop the migration. The report counts checked,
missing, imported, and already-present partitions. Tests use a fake Redis and
temporary files. No real Redis migration has been run. The new `migrate-guides`
operator command calls this component using the hero list from the current
file-backed catalog; it reads `DOTAMIND_REDIS_URL` from the environment.

`python -m app.vnext.data_updates refresh-guides --data-dir /absolute/data/root`
uses the existing `HeroGuideRefresher` with `FileHeroGuideCache`. A minimal
`HeroGuideWriter` protocol expresses the two write methods used by the refresher;
the serial request order, one-second waits, parsers, stable error codes, and
failure retention remain unchanged. The command requires an absolute data root
from `--data-dir` or `DOTAMIND_DATA_DIR`, but does not require a catalog snapshot
or Redis URL and does not construct a Redis client. It takes
`<data_root>/.update.lock` followed by the existing
`/tmp/dotamind-hero-guide-refresh.lock`, releasing both in reverse order. The
second lock prevents overlap with the legacy Redis refresh command only among
processes sharing that container-local lock path. It does not coordinate across
containers.

The file refresh command has offline fake-client tests and has run against D2PT
on the local WSL host. It published data for 127 heroes: 635 nonempty Pub
partitions, 143 empty Pub partitions, 127 nonempty Pro partitions, and 3 empty Pro
partitions, with no guide fetch failures. Configured API instances read guide
files; instances without `DOTAMIND_DATA_DIR` read Redis when available. The old
Redis refresh timer is disabled on WSL. These remain migration-stage entrypoints;
do not install both as daily jobs.

Run `python -m app.vnext.data_updates init-catalog` before
`python -m app.vnext.data_updates migrate-guides` when importing existing guide
data. Those commands accept `--data-dir` as
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
files and Redis entries preserved. The fresh-data WSL deployment intentionally
did not run `migrate-guides`; its previous Docker Desktop Redis volume remains
untouched. Production migration remains a separate operation. Run it in the same
API container as the Redis refresh CLI because their shared refresh lock is
container-local.

The independent `refresh-guides` operation does not require `init-catalog` or
`migrate-guides`; it uses the D2PT hero list and writes partitions directly to
the configured file cache. The WSL recurring refresh path now uses the unified
file updater; the production path has not switched to files.

The existing 36-hour stale rule remains query semantics; it is not a file TTL or
deletion rule. Local-name enrichment remains at query time and is not written
back into source guide snapshots. The WSL deployment started with an empty file
guide store and did not import the old Docker Desktop Redis data. For production,
a migration run must verify raw bytes, source rows, DTOs, times, and states before
switching API reads. Do not rely on indefinite dual writes, and do not delete old
Redis guide data before migration acceptance. This migration does not change
session, Run State, or Artifact storage.

### Catalog update cadence and version gate

`python -m app.vnext.data_updates refresh-catalog --data-dir ...` checks the
current fully validated snapshot before asking Valve for its latest patch. If the
valid local patch matches, it skips entity fetching unless `--force` is supplied.
Otherwise it uses one bounded `ValveFetchSession` to build the complete Catalog,
serializes the same five JSON files as the legacy sync writer, and publishes them
through `CatalogSnapshotStore`. The pointer changes only after all five files
pass validation and the new Repository loads. A corrupt pointer or snapshot can
be replaced after a successful fetch; storage IO failures stop the operation.
The command takes the data-root update lock, does not use Redis or the guide lock,
and returns the action, decision reason, previous and target patch, and revision
as one JSON result. The first WSL unified refresh checked Valve's latest patch and
skipped full Catalog fetching because it matched the initialized `7.41f` snapshot;
revision `d0446e97add94e0fb29a30fdf4cc0905` remained current.

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
executor is not wired to application startup or an HTTP endpoint. The legacy
`python -m app.vnext.hero_guides refresh` command reads `DOTAMIND_REDIS_URL`,
acquires the non-blocking lock at `/tmp/dotamind-hero-guide-refresh.lock`, pings
Redis, executes one refresh, emits one JSON result, and closes Redis before
releasing the lock. The new `python -m app.vnext.data_updates refresh-guides`
command writes with `FileHeroGuideCache`; it first acquires
`<data_root>/.update.lock`, then the same refresh lock. It does not construct
Redis. Both commands reuse the same refresher and wait for default-executor work
to finish during SIGINT/SIGTERM cleanup. Exit codes and JSON reasons are fixed;
exception details and credentials are not printed. The refresh lock coordinates
processes sharing one API container's `/tmp` only, not multiple containers. The
legacy guide-only timer remains a Redis-based template and is disabled on WSL.
Do not install both commands as daily jobs. The file refresh command completed a
real WSL D2PT refresh for 127 heroes with 763 requests and no fetch failures. API
instances with `DOTAMIND_DATA_DIR` read guide files; instances without it read
Redis when available. The unified WSL timer is enabled but has not had its first
scheduled firing; production remains separate.

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

`catalog.lookup` reads exact Valve hero/item IDs from the active local snapshot
and returns display names with snapshot-version metadata. With
`DOTAMIND_DATA_DIR` unset, that snapshot is bundled with the API; when configured,
the API uses the published file-backed snapshot and background loader. These
labels remain separate from provider match facts and do not rewrite OpenDota's
`data`. Unknown IDs remain visible as unknown. Match statistics support only the
conclusions they encode; missing timeline, purchase, or identity data remains
unknown and must not be interpreted as proof that an event did not happen.
