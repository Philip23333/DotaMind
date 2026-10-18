# Data

## Direction

The current vNext model-facing path uses validated, closed capability outputs.
It does not require every data source to fit one universal DotaMind business
DTO, and generic Artifact externalization does not automatically retain raw
provider documents.

## Tool-response documents and observations

Temporary arithmetic uses `math.calculate` as specified in [TOOLS.md](TOOLS.md).
Its result is a calculation from supplied inputs, not a new Provider fact, and
is never written back into GameDetail or its Artifact. Computed durations reuse
the common time formatter after calculator rounding; source DTO time labels
continue to preserve source precision.

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
DTO fields have defaults. `game.detail` also uses that local resolution during DTO construction, replaces
source internal keys with exact bilingual entity/unit objects at typed fields,
and keeps unmatched source scalars only in `coverage`. This explicit projection
exception does not change guide source-label retention or generic Artifact tools.

## Cross-source esports game identity (offline resolver, bounded reads, Service, and opt-in tool implemented)

This section owns the matching semantics for a path from a PandaScore Game to
the existing OpenDota `game.detail(valve_game_id)` capability. The Provider-side
offline League candidate discovery, game candidate, evidence, single-League and
multi-League normal-window resolver functions, and their bounded serialized
Provider read flow are implemented. Offline functions accept already-read source
records and make no network or model calls. The read flow coordinates the
existing adapters; the capability Service converts its result and errors without
repeating matching logic. Product composition can register the Artifact-
continuation tool when its independent flag, OpenDota enablement, and PandaScore
token are all present. It remains absent from the default tool inventory.
Observed provider behavior and sampled counterexamples are summarized in
[`reference/opendota-cross-source-identity.md`](reference/opendota-cross-source-identity.md).

### Identity boundary

PandaScore Match, PandaScore Game, PandaScore Series, PandaScore Tournament,
OpenDota League, and OpenDota `series_id` are source-specific identities and
hierarchy levels. A numeric ID from one source is never converted into an ID
from another. Names, acronyms, or a shared year are candidate-search clues, not
identity proof. One OpenDota League can contain games from multiple PandaScore
Series or tournaments. OpenDota Team IDs identify in-game teams in a match and
must not be treated as permanent equivalents of real esports teams. Matching
PandaScore and OpenDota `series_id` values by name or numeric resemblance is
not a contract; even within one PandaScore Match, the observed OpenDota value
can differ between games or be null/zero.

### Candidate retrieval

`find_game_candidates()` selects a PandaScore Game by its explicit `position`
and filters one supplied OpenDota League list using both start-time and duration
tolerances. Tolerances are explicit inputs; there is no production default.
`resolve_game()` evaluates that single supplied League scope. The
`resolve_game_across_leagues()` entry point accepts the caller's complete,
already-selected League IDs and their lists, then applies the same per-candidate
detail and identity checks across the combined scope. It verifies that each
League row ID, detail-map key, and detail `match_id` are the same strict positive
integer. Neither resolver selects or widens League scope, nor fetches missing
details.

`PandaScoreOpenDotaGameResolutionProvider` performs the internal reads in this
order: one PandaScore Match, target-Game validation, one complete OpenDota League
collection, all selected League match lists, then each distinct candidate detail
once. Reads are serial. `GameResolutionReadPolicy` requires explicit non-negative
time and duration tolerances and positive limits for League candidates, detail
reads, and total adapter reads; it has no production defaults. The read count
includes failed adapter calls. Before a list or detail phase starts, the flow
checks that the full selected phase fits its remaining request budget. A phase
that exceeds a limit fails without reading an arbitrary subset.

Match absence and offline target/League outcomes remain explicit. Adapter
`StructuredToolError` codes and safe details are preserved with the failing
operation and request count; transport, access, schema, and timeout failures are
not converted into empty source data or `no_candidates`. Cancellation propagates
unchanged, and no retry, parallel read, background task, or cross-call cache is
used. The internal read attempt retains the complete successfully read PandaScore
Match, OpenDota League collection, each selected League list, and each complete
`OpenDotaGameRecord` including its provider and retrieval time. Its own
`retrieved_at` is the attempt completion time, not a claim that all sources were
read simultaneously. These complete source records stay in the internal read
attempt. The Service publishes only the selected resolution evidence described
below; the continuation tool stores that complete public result through the
generic Artifact processor. It does not store the internal read attempt or a
handle for retrieving candidate details.

The accepted `game.detail` data projection is defined in
[`agent/game_detail_data.md`](agent/game_detail_data.md). It changes the
public detail result and its Artifact to the governed DTO while preserving
internal source facts required for identity checks. The resolver's public
evidence boundary is implemented independently of that pending projection:
the matcher still consumes complete candidate details, while its Artifact cannot
retrieve them. `game.detail` itself returns the governed DTO and cannot retrieve the
complete source record through an alternate public path.

### Capability result and Service

`GameResolutionService` calls the bounded Provider once with the requested
PandaScore Match ID, game position, read policy, and confirmed mapping object.
It validates that the returned attempt belongs to that request, then converts
the attempt's final category into `EsportsGameResolutionResult`. It performs no
additional reads and does not redo candidate selection, evidence comparison, or
identity confirmation.

The result has `status` (`resolved` or `unresolved`), the selected positive
`game_position`, optional program-selected `valve_game_id` and
`inferred_cross_source` method, `selection_basis`, identity `warnings`, a closed unresolved `reason`, the successfully
read source IDs in read order, the attempt completion `retrieved_at`, and `data`.
`data` is an explicit projection of the existing offline results, not the whole
internal `GameResolutionReadAttempt`. Its complete field set is:

| Field | Retained evidence |
|---|---|
| `match_id`, `game_position` | Internal request identity and selected source position |
| `stage`, `reason`, `requests_started` | Completed read stage, its reason, and adapter-read count |
| `target_game_result` | Target readiness/category, reason, and selected PandaScore Game record; `null` if not reached |
| `league_candidate_result` | League selection/category, selected candidate records and comparisons, total count, and reason; `null` if not reached |
| `resolution_result` | Existing cross-League outcome, scopes/diagnostics, candidate statuses/reasons, timing differences, participant/winner source facts, and per-game team-to-side associations; `null` if not reached |

The projection preserves these nested results and their source facts without
rerunning matching or inventing conclusions. Candidate IDs in evidence remain
unselected unless the top-level status is `resolved`. Selection is distinct from
complete identity verification: `selection_basis="verified_identity"` has no
warnings; `selection_basis="unique_candidate"` requires nonempty uncertainty codes.
Unresolved results have no ID, method or selection basis and have empty warnings.
The nested resolution result retains the same basis and warnings. Provider-private IDs
remain evidence, not new tool inputs. Top-level `retrieved_at` remains the
attempt completion time and is not duplicated in `data`.

The four internal source collections `pandascore_match_context`,
`opendota_leagues`, `league_matches_by_id`, and `candidate_details` are excluded
from the public result, inline observation, and Artifact. This excludes complete
candidate detail bodies and their per-read envelopes. It preserves the relevant
selected Game/League records already carried by the offline evidence results;
it does not store the complete League catalog or League match lists. There is
no raw field or alternate Artifact reference to those internal collections.
Generic Artifact read/grep behavior is unchanged.

The public reason categories distinguish missing Match, target-game selection
failures, insufficient target signals or competition context, no League scope,
no game candidates in a searched scope, ambiguity, incomplete evidence, mapping
conflict, explicit candidate rejection, and incomplete search scope. Completed
League discovery with no candidates maps to `no_league_candidates`; a completed
search of selected League match lists with no game candidates maps to
`no_candidates`. A missing required intermediate result is a contract error.
`ResolutionBudgetExceeded`
becomes a stable `tool_execution_error` with `budget_exhausted` details, not an
unresolved result. Provider `StructuredToolError` and cancellation propagate
unchanged. An internally inconsistent attempt is a contract error rather than a
successful empty result.

The Artifact-continuation tool validates the Match-search Artifact source and
selected Match, extracts its ID server-side, and invokes this Service. Product
composition binds the continuation to the same session Artifact store used by
`esports.match.search`, and stores the complete result through the generic
Artifact processor. The tool is registered only when
`DOTAMIND_GAME_RESOLUTION_ENABLED=true`, `DOTAMIND_OPENDOTA_ENABLED=true`, and a
non-empty PandaScore token are configured. Its initial policy bounds League,
candidate-detail, and total adapter reads; those request bounds do not guarantee
completion within Runtime's tool timeout or execution deadline. The continuation
passes an empty confirmed-mapping object, so cross-call mapping persistence,
duplicate assignment protection, and whole-Match consistency are not implemented.

For `league_matches_by_id`, a present key with `[]` means that League was read
and produced no rows; an absent selected key means the search scope is
incomplete. An incomplete selected scope is reported as `search_scope_incomplete`
and cannot produce a resolved identity, even if an available League has one
accepted candidate. League IDs are strict positive integers and duplicates are
deduplicated in first-seen order.

A unique result from time and duration may select a game with identity warnings
under the complete-scope rule below; it does not verify every identity check.
Candidate coverage and source failures remain scoped to the supplied
League result or the full selected multi-League scope; `no_candidates` means
only that no row in that current scope met the supplied tolerances, not that the
game does not exist.

### League candidate discovery

`find_league_candidates()` uses the explicit PandaScore `league.name` as the
competition-brand search term against an already-read OpenDota League collection.
It preserves `serie.name`, `serie.full_name`, `serie.season`, and `serie.year` as
the source context used to explain the comparison; Series names are not required
to match League names. Text matching applies Unicode NFKC, case folding, and
complete token matching with whitespace and punctuation as separators. It does
not translate, expand abbreviations, use aliases, or rank candidates.

An explicit positive PandaScore season and an OpenDota `Season N` value are
compared as editions. A canonical Roman numeral directly after the matched brand,
such as `BLAST SLAM VIII`, can also provide the OpenDota edition. Four-digit years
are not treated as season numbers. Explicit `serie.year` values are compared with
four-digit years or a clear year range in the OpenDota League name. Each
comparison is `matched`, `conflicting`, or `unspecified`. A candidate with an
explicit conflict is excluded; missing or unrecognized comparison data remains
`unspecified` and does not exclude a brand match. Qualifier numbers and regional
or stage names are not season evidence.

The caller supplies a strict positive `max_candidates` budget. Candidates retain
OpenDota source order and complete source records. If the remaining scope exceeds
the budget, the result reports `candidate_limit_exceeded` and the full count with
no truncated candidate list. A returned League is only a search scope: even one
candidate does not establish a PandaScore-to-OpenDota League identity or confirm
a Valve Game. In particular, a Series with no explicit season can leave a broad
range or exceed the caller's budget; the function does not infer a missing season.

### Identity confirmation

The normal-window identity-verification rule requires all of the following for a
candidate; successful verification is published as `selection_basis="verified_identity"`:

- the League row and detail identify the same Valve game;
- detail start time and duration are inside the same explicit tolerances used
  for list filtering;
- both participant names are comparable and associated by the existing
  participant-evidence function;
- the selected PandaScore Game's explicit Team winner agrees with the
  OpenDota `radiant_win` result; and
- the evidence contains no source-field contradiction.

Participant names first use Unicode NFKC, case folding and alphanumeric comparison.
If the two sets differ, comparison may remove one terminal complete word from
`esports`, `e-sports`, or `gaming`, ignoring case and terminal punctuation. A
substring or a word in the middle is not removed. Empty cores and collisions
between the two participants cannot establish an association. Academy, Junior,
regional and other qualifiers are preserved. Associations retain both original
names and `name_match_method` (`normalized_exact` or `common_suffix`); Provider
team IDs are retained but never required to equal IDs from another Provider.

If the complete selected scope contains exactly one distinct Valve candidate,
its list and validated detail both meet the time/duration window, and it has no
explicit contradiction or mapping conflict, incomplete participant/winner checks
do not block selection. Return `resolved`, the ID, and
`selection_basis="unique_candidate"`; `warnings` retains uncertainty reason codes
and the evidence retains original names, source IDs, timing differences and
winner facts. Allowed uncertainties are missing/uncomparable/unaligned/colliding
participant names, missing winner/type, unavailable winner-participant association,
or missing OpenDota winner. Missing detail/timing, out-of-window detail, explicit
winner or source contradictions, and incomplete scope remain blocking. This rule
does not choose one of several original candidates merely because others lack
evidence; uniqueness is global across selected Leagues, after Valve-ID deduplication.

The model reviews these already-returned facts to decide whether the selected
game reasonably fits the request, then may continue to `game.detail` without a
new identity lookup or repeated resolution solely to remove warnings. Material
association uncertainty must remain visible in the answer. `resolved` is a
selection outcome: a nested assessment may remain `unresolved` because its checks
are incomplete; it does not override the successful top-level selection.

All candidates across the complete selected scope are considered before
returning a result. Two or more distinct accepted Valve IDs produce `ambiguous`.
If the same Valve ID appears in multiple League lists, its per-League
assessments are retained together and count as one candidate: all accepted
assessments merge to accepted, all excluded assessments merge to excluded, and
any unresolved assessment keeps the evidence group unresolved. A mixture of accepted and
excluded assessments for one Valve ID is also unresolved and records a
cross-League assessment conflict and cannot use the single-candidate exception.
One accepted candidate with any unresolved competitor remains `evidence_insufficient`.
Outside the sole-candidate exception, selection requires one accepted candidate
and every other distinct candidate to have an explicit exclusion
reason, such as a detail outside the current window or a winner conflict after
its participants were supported. Missing details, missing timing, missing
participants or winner, unaligned names, and source conflicts remain unresolved;
they are not treated as evidence against a candidate. The sole-candidate rule
can retain allowed identity uncertainties as warnings. If all candidates are
explicitly excluded, the result is `no_acceptable_candidate`.

Before returning `resolved`, the function checks the caller's confirmed
PandaScore-Game-to-Valve-Game mappings for duplicate assignment or remapping. It
does not modify that mapping. The resolver does not use list order, nearest time,
or a similarity score, and does not copy full OpenDota details into its result.

### Recovery and whole-Match consistency

Within one product request, already validated internal source records may be
reused across single-game resolutions and `game.detail`. Preserve complete source
values and the original record retrieval timestamp; reuse does not refresh it or
confirm another game's identity. Each consumer receives an independent copy.
Successful empty collections remain distinct from failed reads, which are never
cached as empty successes. Request-scoped source reuse is discarded after the
request and exposes no model-visible path to internal candidate detail bodies.

The multi-League resolver is limited to the selected, fully supplied League
lists and the caller's normal time/duration window. It does not prove that a
PandaScore League or Series is identical to an OpenDota League. Search widening,
neighboring-game roster corroboration, and exact player `account_id` comparisons
remain future work. If source time fields conflict, preserve their original
values; do not repair them by substituting another timestamp or duration.

Across one Match, two different PandaScore Games must not both be automatically
assigned to the same Valve game. Game order and time should be consistent, but
the Nth OpenDota list row is not necessarily the Nth PandaScore Game. Explicit
identity or winner contradictions cannot be overridden by a weak signal.
Scheduled games, forfeits, missing games, and remakes remain distinguishable;
they are not erased by renumbering. One unresolved game does not invalidate
other independently confirmed games.

Confirmed results should retain the inference method, participating sources,
retrieval time, and matching evidence so a later persistent mapping can be
audited and corrected. Persistence format, TTL, and recurring synchronization
are not selected by this design. The complete product journey, candidate
workflow, tool proposal, and acceptance layers are described respectively in
[`PRODUCT.md`](PRODUCT.md), [`ARCHITECTURE.md`](ARCHITECTURE.md),
[`TOOLS.md`](TOOLS.md), and [`EVALS.md`](EVALS.md).

## Explicit entity display records and Team assets (directory, refresh, capability injection, renderer, and prompt guidance implemented)

This section owns the shared display-record and update-data contract. User-visible
placement and exclusions are defined in [PRODUCT.md](PRODUCT.md); reference
syntax is defined in [agent/product_run_state.md](agent/product_run_state.md).
The implemented refresh wiring below is not evidence of a deployed or successful
Team refresh. Real-model use and placement of references remain unverified.

### Display records

The Team snapshot is published at `<data_root>/display/teams.json` with
`schema_version: 1`; teams are indexed by their decimal PandaScore ID. Each record
is keyed at runtime by a stable `display_ref` and retains the entity type, source,
and identity within that source. It also provides the latest display name, the
identifier of the most recently successful local image resource when one exists,
the latest observed image URL, the URL associated with the last successful
download, the successful-download time, and the month through which the required
monthly image refresh has completed. The file record fields are `source_id`,
`label`, `observed_image_url`, `downloaded_image_url`, `image_asset`,
`image_downloaded_at`, and `monthly_refresh_completed`.
`image_asset` is a lowercase SHA-256 content hash for
`<data_root>/images/assets/<hash>.png`; the reader returns the existing local
by-hash image route only when that file exists, never the upstream CDN URL. A
missing or invalid initial snapshot produces an empty Team directory. After a
valid snapshot has been read, a damaged replacement leaves that last valid
snapshot in use; the next valid publication is visible on a later read.

Entity identity comes from an explicit source identity, never from a display name,
team acronym, or image filename. An image content hash identifies image bytes,
not the entity. Name updates and image updates are independent. If a later source
listing omits an already recorded entity, the record and its local image are not
automatically deleted. History stores no name or image snapshot; rendering looks
up the current shared record when the saved answer is loaded. Capability
composition attaches Team references only at explicit Team DTO fields in team,
series-team, tournament-participant, match-participant, and player current-team
results. The Team ID must exist in the local directory; this check does not
replace the Provider's current name or image URL. Catalog lookup also attaches
references to found Hero and Item entries, and `hero.guide` attaches references
to explicitly resolved Hero, Item, and Ability name objects after filtering and
section projection. Missing images do not block references. The shared product
prompt instructs the model to reuse only the reference attached to the same
entity and not infer references from names or IDs. User-visible rendering uses
the latest directory data.

### Batch display resolution API

`POST /api/v1/display/resolve` accepts a JSON object with a `refs` string array
and returns an `entities` mapping keyed by each resolved reference. The request
is limited to 100 entries and 128 characters per string; strings are validated
strictly, extra request fields are rejected, and invalid request shapes or
limits return `422`. Duplicate references are resolved once. An empty array
returns `200` with an empty mapping. Malformed references and valid references
whose entities are absent from the local directory are omitted from the mapping.

Each returned value contains `display_ref`, `kind`, the latest directory `label`,
and a nullable `image_url`. Image URLs are local by-hash asset routes only; the
response never exposes an upstream CDN URL or filesystem path. A known entity
without a local image is still returned with `image_url: null`. The route uses
the same `EntityDisplayDirectory` instance as capability enrichment and resolves
the whole batch in one call. It is read-only and sends `Cache-Control: no-store`;
it does not add Redis or TTL caching. A Team snapshot atomically replaced after
one request is visible to the next request. With no configured data root, Valve
entities can still resolve from the local Catalog while Team references remain
absent. If the display directory is not assembled, the route returns `503` with
`entity_display_unavailable`.

This is a frontend data endpoint, not a model-facing tool. The renderer calls it
for complete references in current and historical answers; the model prompt only
instructs the model to reuse program-supplied references and does not call this
endpoint. Real-model placement remains to be evaluated.

### Team directory and image updates

The shared updater reads the complete PandaScore Dota 2 team collection once per
day at 03:00 in `Asia/Shanghai`, requesting 100 teams per page and fetching pages
serially. It publishes a new team directory only after every required page has
been fetched and validated. A pagination or response failure leaves the previous
directory intact.

Team image downloads share one bounded image-download concurrency ceiling with
the existing Valve image update task. This is a combined limit: the updater must
not create a separate, equally sized concurrency pool for each source. A team
image is eligible when the team is new, its source URL changed, or its local asset
is missing or damaged. On the first day of each month, existing team images are
also downloaded again even when the URL is unchanged, so changed bytes at a stable
URL can be detected. This uses the existing daily update entry point; it does not
add a timer or change systemd catch-up settings.

An image failure does not block publishing a complete team directory. The last
successful local image remains associated with the record; if no image has ever
downloaded, the record remains usable without one. A missing source URL also
retains the prior image and does not count as a successful refresh. A changed URL
and the URL of the last successful download remain distinguishable. The monthly
completion marker advances only after the required download succeeds. A missed
run or failed image remains eligible on a later daily run; the system does not
mark incomplete work as successful.

The existing `refresh-all` entry point runs the Team metadata and image phase
after the Valve image phase has ended. Both phases receive the same
`image_workers` value and run sequentially, so their combined image-download
concurrency cannot exceed that value. Catalog failure blocks Valve image work
but does not block Team refresh; Valve image failure or partial success also does
not block Team. A Team failure is reported independently from the other modules.
`--force` applies to Catalog, patch records, and Valve images; Team images still
follow the URL, local-asset, and monthly-refresh checks above. The updater needs
`DOTAMIND_PANDASCORE_TOKEN`; a missing token is reported as a Team configuration
failure while the other refresh modules continue. The production Compose updater
passes the existing PandaScore base URL, token, and timeout settings. This code
integration does not by itself establish a successful deployed or scheduled Team
refresh.

The initial migration uses the historical team list to restore explicit source
identity mappings for the existing team assets and reuses those image files. It
does not restore the legacy name matcher or its full synchronization code. Any
historical entry without a verified source identity stays unresolved until that
identity is supplied; names and acronyms are not used to manufacture a mapping.
Observed investigation counts are not fixed limits on the directory.

## Shared data storage and update target

When `DOTAMIND_DATA_DIR` is unset, the API loads its entity catalog from files
bundled with the API code and does not register `hero.guide`. When set to an
absolute path, the API requires a valid published catalog snapshot there, uses
the background loader, and reads guide partitions directly from the same data
root. Guide queries never fall back to Redis. Redis remains configured for other
application stores; the guide importer reads legacy Redis partitions only when
an operator explicitly runs `migrate-guides`.
The file-backed `refresh-guides` command completed a real WSL D2PT refresh for
127 heroes, and the WSL API read the resulting shared files. The persistent
Catalog and guide stores are initialized and populated in WSL. No Redis guide
migration was run there; production data-root initialization and any required
migration remain pending. The conceptual data areas are `catalog`, `patches`,
`images`, and `guides`.

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
一次刷新内 Team 查询按 ID 复用同一个进行中或已完成的任务。Playoffs 查询或 Team 名称查询发生已知 Provider
错误时，保留赛事行、留空冠军，不把可选补全错误登记为整份列表失败。

候选使用十分钟共享缓存和按需刷新。普通 GET 在已有成功快照过期时立即返回旧快照，并启动最多一个由
服务持有的后台刷新；刷新结束不会推送或改写已返回的响应。冷缓存 GET 等待共享刷新任务，并发请求复用
该任务。手动刷新使用 `POST /api/v1/home/recent-series/refresh`：允许时绕过新鲜缓存，启动刷新并等待
结果；若已有任务则等待同一个任务。共享 Redis 元数据记录手动允许时间，冷却为 60 秒，从该任务启动时
计算，因此重载页面或重建服务不会绕过冷却，也不会被额外等待时间延长。若已有 600 秒失败限频仍在生效，
响应返回两项限制中更晚的允许时间。失败限频由最近失败尝试开始计算；手动冷却和失败限频都不改变普通
GET 的新鲜度规则。Redis 旧缓存没有手动允许时间字段时按无限制处理；保存新冷却元数据失败则返回现有
缓存不可用错误，不能先启动新的上游请求。刷新任务只在单个 API 进程内合并，不构成跨进程刷新锁。
成功获取时间与最新刷新尝试状态分别记录，以区分数据获取时间和最近刷新结果。成功取得空列表表示有效空
数据；请求失败表示数据不可用，不等同于有效空列表。没有成功缓存且刷新失败时也必须报告不可用状态。下面记录当前
后端实现采用的缓存、接口和冠军名称查询方式。

Provider 生命周期结果中的 `league_name` 只取 Series 原始响应的 `league.name`。
对象或名称缺失、名称不是字符串或去除首尾空格后为空时，值为 `null`。不额外
查询 League、不翻译，也不把它拼回共享 `SeriesDTO.name`。近期候选、Redis 快照和
HTTP 项目响应保留该字段。字段设有 `null` 默认值，旧 Redis 快照缺少它仍可读取；
前端也将旧响应中缺失的字段归一为 `null`。

### 当前后端实现

首页读取接口为 `GET /api/v1/home/recent-series`；手动刷新接口为
`POST /api/v1/home/recent-series/refresh`。页面首次读取使用 GET，刷新和重试使用 POST。
两种响应均包含 `server_time` 与 `manual_refresh_available_at`；前者是后端生成响应时的时间，后者
是综合 60 秒手动冷却和 600 秒失败限频后的下次允许时间，无限制时为 `null`。响应还包含 `status`、`items`、
`retrieved_at`、`last_attempt_at` 和安全错误码 `last_error`；状态为 `fresh`、
`stale` 或 `unavailable`。候选字段为 Series ID、展示名称、`league_name`、生命
周期、起止时间、可选冠军战队名称及其来源字段。`name` 优先取 `full_name`，缺失时取 `name`；
`league_name` 来自 Series 响应的 `league.name`。前端以可用的 League 和 Series
名称组合显示与查询用名，不能根据文本猜测 League。

每轮首页刷新在三个阶段工作：running 与 past Series 生命周期端点并行读取；按现有规则
排序、去重并选出最多十条；再并行补全入选候选的冠军并按候选原顺序组装。该轮的
lifecycle、Tournament 与 Team Provider 调用共用一个最多六路的局部并发上限；六是上限，
不保证始终有六个请求在途。请求结束、出错或取消时释放名额。Provider 读取分别调用 running 与 past
Series 生命周期端点，候选服务按开始／结束时间本地排序，日期缺失项排在有日期项之后，稳定保留相同日期的来源顺序；去重后
最多取十条。已结束 Series 缺少 `winner_id` 时额外读取
`GET /dota2/tournaments?filter[serie_id]=<series_id>&page=1&per_page=100`，只使用
名称精确匹配 `Playoffs` 的阶段胜者；Series 自身存在非 Team 胜者时不回退查询。Team
请求失败、结果缺失或名称为空只会省略冠军名称，不阻止赛事候选。冠军来源和
Tournament ID 随首页候选及 Redis 快照保存；旧快照缺失新字段仍可读取。每个候选保持
Tournament 结果先于其 Team 查询的依赖顺序；多个候选可并行补全，但最终列表仍按入选顺序。
必需的 running/past 查询任一失败会取消并回收兄弟请求，整轮不发布部分快照；刷新关闭或取消时，
候选及共享 Team 子任务也会全部回收。可选冠军查询失败仍只影响冠军字段。

共享快照存于 Redis。十分钟是基于 `retrieved_at` 的新鲜度窗口；成功快照不设置
Redis TTL，以便刷新失败时继续返回旧数据并标记 `stale`。失败尝试单独更新
`last_attempt_at` 和稳定 `last_error`，有效空列表仍会作为成功快照缓存。没有成功
快照时，来源失败返回 `status="unavailable"`；Redis 不可用或缓存损坏时接口返回
HTTP 503。普通 GET 的旧快照在后台 Provider 请求结束前立即返回；手动 POST 和冷缓存 GET
等待同一个刷新任务，单个请求取消不会取消共享刷新。手动 POST 绕过十分钟新鲜期，但遵守持久化的
60 秒手动冷却和 600 秒失败限频；普通 GET 仍遵守十分钟新鲜期与失败限频。失败尝试限频 600 秒；Redis 已记录的失败在
服务重建后仍生效，记录失败本身写 Redis 失败时由当前服务实例用本地时间兜底。
应用关闭时先取消并等待首页刷新，再关闭共享 Redis 客户端。刷新任务只在单个 API
进程内合并；没有跨进程刷新锁。

离线测试覆盖 Provider 读取后的 League 名称归一化、生命周期并行、六路请求上限、候选顺序稳定、
进行中 Team 任务去重、Tournament→Team 顺序、取消回收、排序、去重、冠军条件、空与坏数据区分、缓存旧值
保留、普通 GET 旧值立即返回、手动 POST 绕过新鲜缓存并等待完成、冷却起点与 59/60 秒边界、冷／热缓存刷新合并、单个等待者取消隔离、600 秒失败间隔、
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

The Valve catalog sync retains positive ability IDs from the bilingual ability
list when hero detail responses do not define them, including records whose
internal names use `special_bonus_`. Hero detail records remain authoritative for
duplicate IDs; supplemental records have no inferred hero association. These
supplements retain their validated ID/internal name and renderable bilingual
display names; they do not extend hero ability lists, talent trees, or the existing
talent-value candidate set. Missing or unresolved localized display names stay
empty, while malformed identity and other required source errors still fail
synchronization. Ability ID zero remains excluded. Image downloads are best
effort: failures are reported, successful and previously available files remain
usable, and the catalog snapshot can still be published. Chat visual metadata is
created only when the corresponding local image file exists; catalog name lookup
does not depend on images.

`CatalogSnapshotLoader` loads the current complete snapshot at startup and then
checks the pointer revision in the background, defaulting to a 30-second interval.
With `DOTAMIND_DATA_DIR` configured, API startup waits for this first load and
fails if the pointer or snapshot is missing or invalid; it does not initialize a
directory or fall back to bundled data. An unchanged revision does not reload the
five files. A new revision is fully validated before one in-memory snapshot
reference is switched; failed checks or loads keep the last successful snapshot
available. `catalog.lookup`, guide name enrichment, and the current legacy answer
name-matching path use the current snapshot, each pinning one repository for its
operation. That answer-matching path is current code, not the target display
contract; the confirmed explicit-reference design above remains pending. The
check interval does not bound validation or IO time. Offline tests do not
establish power-loss recovery or deployed persistent-volume behavior.

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

It runs the current Catalog, latest patch-record, Valve image, file-guide, and
Team directory refresh components in one invocation. `--force` is passed to
Catalog, patch, and Valve image refresh; Team images still follow their URL,
asset, and monthly-refresh checks, and guides refresh on every run. Catalog and
patch work run in parallel with the guide refresher and share one
`ValveFetchSession`, response cache, and Datafeed concurrency ceiling. The
image worker limit controls CDN downloads. Valve images begin only after Catalog
succeeds or skips; Catalog failure marks Valve images blocked. The Team stage
runs after the Valve image stage (or after it is blocked), so the two image
sources never overlap and share the same concurrency ceiling. Patch, guide, and
Team failures do not cancel other work. The guide refresher retains its existing
serial hero/request order and one-second post-request wait. Team metadata reads
use `DOTAMIND_PANDASCORE_TOKEN`, `DOTAMIND_PANDASCORE_BASE_URL` (default
`https://api.pandascore.co`), and `DOTAMIND_PANDASCORE_TIMEOUT_SECONDS` (default
`20`). Missing token or invalid Team metadata is reported in the `teams` module;
it does not silently turn into a successful empty result.

The command acquires `<data_root>/.update.lock` before creating clients or making
requests. The shared data-root lock remains held through thread and coroutine
cleanup. It emits one
ordered module summary, including the `teams` status/report/reason, and returns
success, partial, or failed according to the module results. Existing WSL
live-refresh evidence predates the unified Team integration and does not verify
a Team fetch. The first real WSL run completed as partial: Catalog skipped
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

### Guide partition storage and updates (implemented; production deployment pending)

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

The callable `migrate_redis_guides()` is retained only as a one-time import path
for an operator who must preserve existing Redis guide snapshots during a
deployment cutover. It validates the complete hero list before I/O, reads Pub
positions 1 through 5 and then Pro through the Redis cache API, imports complete
non-missing entries, and reads each imported or already-present file back for
value equality. Identical files are safe to skip; conflicting or corrupt targets
stop the migration. The report counts checked, missing, imported, and
already-present partitions. Tests use a fake Redis and temporary files. No real
Redis migration has been run. The `migrate-guides` command uses the hero list
from the current file-backed catalog and reads `DOTAMIND_REDIS_URL` from the
environment.

`python -m app.vnext.data_updates refresh-guides --data-dir /absolute/data/root`
uses the existing `HeroGuideRefresher` with `FileHeroGuideCache`. A minimal
`HeroGuideWriter` protocol expresses the two write methods used by the refresher;
the serial request order, one-second waits, parsers, stable error codes, and
failure retention remain unchanged. The command requires an absolute data root
from `--data-dir` or `DOTAMIND_DATA_DIR`, but does not require a catalog snapshot
or Redis URL and does not construct a Redis client. It takes
`<data_root>/.update.lock`; this shared-root lock prevents overlapping update or
migration commands that target the same data directory, including across
containers that mount that directory.

The file refresh command has offline fake-client tests and has run against D2PT
on the local WSL host. It published data for 127 heroes: 635 nonempty Pub
partitions, 143 empty Pub partitions, 127 nonempty Pro partitions, and 3 empty Pro
partitions, with no guide fetch failures. Configured API instances read guide
files directly; instances without `DOTAMIND_DATA_DIR` do not register the guide
tool. The Redis guide refresh CLI and timer templates have been removed. The
Redis-to-file importer remains a one-time migration command; it is not part of
the daily refresh path.

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
files and Redis entries preserved. The WSL deployment populated the file store
directly and left the previous Docker Desktop Redis volume untouched. Production
migration remains a separate operation. Migration and file refresh share the
data-root lock; the retired Redis refresh CLI and its container-local lock are no
longer part of the update path.

The independent `refresh-guides` operation does not require `init-catalog` or
`migrate-guides`; it uses the D2PT hero list and writes partitions directly to
the configured file cache. The WSL recurring refresh path uses the unified file
updater; production cutover remains separate.

The existing 36-hour stale rule remains query semantics; it is not a file TTL or
deletion rule. Local-name enrichment remains at query time and is not written
back into source guide snapshots. The WSL file guide store has been populated by
the file-backed refresher without importing the old Docker Desktop Redis data.
For production, a migration run must verify raw bytes, source rows, DTOs, times,
and states before switching API reads. Do not rely on dual writes, and do not
delete old Redis guide data before migration acceptance. This migration does not
change session, Run State, or Artifact storage.

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

## Hero guide data contract (DTO, HTTP client, parsers, file cache, and refresh executor implemented)

The internal contract is defined in `app.vnext.capabilities.hero.guide`. A
synchronous D2PT HTTP client now fetches the heroes list, Pub builds, and Pro
builds. It preserves the exact response bytes and parsed JSON array and performs
transport and minimal source-shape checks. Pure Pub and Pro parsers project
source rows into the existing guide DTOs without changing the response. A
file-backed cache stores source snapshots in the shared data root, and the API
reads requested partitions directly from those files. HeroGuideService exposes
file-backed queries through the conditionally registered `hero.guide` tool. An
internal serial refresher connects the D2PT client, parsers, and file cache; the
operator `data_updates` commands and daily `refresh-all` task write the same file
format. Redis is not a guide query or daily refresh store. A one-time importer
remains for deployments that need to migrate old Redis guide snapshots.
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

The one-time `migrate-guides` importer reads old `RedisHeroGuideCache` snapshots
and writes them into `FileHeroGuideCache`. It does not call the D2PT client or
modify Redis. It preserves old snapshot bytes, parsed rows, DTO projection,
retrieval time, and attempt/error state, then reads each target file back to
verify equality. Runtime API queries and scheduled refreshes do not instantiate
the Redis guide cache.

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
executor is not wired to application startup or an HTTP endpoint. The
operator command `python -m app.vnext.data_updates refresh-guides` writes with
`FileHeroGuideCache`; the unified daily `refresh-all` task uses the same
file-backed guide path. Both acquire the shared data-root update lock. The retired
Redis refresh CLI and its systemd templates are no longer in the repository. The
one-time `migrate-guides` importer is the only guide operation that reads Redis.
The file refresh command completed a real
WSL D2PT refresh for 127 heroes with 763 requests and no fetch failures. The WSL
API reads files when `DOTAMIND_DATA_DIR` is configured; without it the guide tool
is not registered. The unified WSL timer is enabled; production remains separate.

The file cache is connected to a read-only `HeroGuideService`, which the
model-facing `hero.guide` tool exposes when the application has a data directory.
The Service reads Pub and Pro once each for every section query. It filters Pro examples by
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
startup does not fetch or refresh guides. When a data root is configured, queries
read its current files; without one, the guide tool is not registered. These query
rules do not establish all-hero coverage or real-model answer quality.

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
`game.detail` currently registers only when `DOTAMIND_OPENDOTA_ENABLED` is
true. Its adapter preserves the complete validated source object internally,
including JSON extensions, null values, zeroes, and booleans. The returned positive
`match_id` must equal the requested Valve ID; known fields are type-checked
when present. Anonymous player rows and absent optional or parsed fields are
valid. Missing process data does not prove an event did not occur, and the
lookup does not trigger replay parsing. Tests use HTTP mocks. The earlier live
cross-source check of `8960882635` is a single-match observation, not live
verification of this new client. The target projection and its source/missing
rules are owned by [`agent/game_detail_data.md`](agent/game_detail_data.md);
the public implementation returns that DTO rather than the full source object.

The current pure OpenDota projector and closed eight-section `GameDetailData` are
implemented and connected to the public Service. They include source-aligned
minutes, final statistics, typed bilingual entities/units, normalized objective
types, direct hero interactions, and scalar coverage evidence. The source fixture
still contains excluded fields, so tests protect projection boundaries. The
implemented baseline has competition null and ten final-stat fields. The accepted
STRATZ-first target below changes mappings and selected fields; it is not yet
implemented. Unverified source semantics remain explicit unknowns.

The internal read and public result types are separate. The OpenDota adapter's
`get_game_record(match_id)` validates source identity and known fields, then
returns `OpenDotaGameRecord(match_id, provider, retrieved_at, data)`. It does not
depend on the model-facing `GameDetailInput` or `GameDetailResult`. The identity
resolver reads that internal record directly, retaining exact timestamps and
source team IDs for its offline checks.

`GameDetailService.get_game_detail(GameDetailInput)` calls that same adapter once
and constructs the separate public `GameDetailResult`, mapping internal
`match_id` to `valve_game_id` while retaining provider and retrieval time. It
pins one active local entity repository before the source read and projects the
record with that resolver and one loaded unit resource. Its outer result includes
`catalog_version` and `unit_mapping_version`. Public and internal data do not
share mutable values.
The Service adds no provider requests, retries, cache, or fallback; structured
errors and cancellation propagate unchanged. Product wiring shares one adapter
and client between this Service and the resolver, not one public result type.

### Current game detail projection (OpenDota baseline; deterministic checks passed)

The model-facing input remains `game.detail(valve_game_id)`. The outer
`valve_game_id`, `provider`, and `retrieved_at` fields remain unique
provenance metadata. The target also records one `catalog_version` and one
`unit_mapping_version` in this outer envelope. The `data` value contains the eight sections
`match`, `draft`, `players`, `economy`, `builds`,
`events`, `interactions`, and `coverage`. The source identity is
validated before mapping. The complete governed DTO, rather than the raw
OpenDota response, is the logical detail result stored by generic Artifact
externalization.

The contract owner is
[`agent/game_detail_data.md`](agent/game_detail_data.md). It deliberately
separates source facts from deterministic date, count, ordering, and enum
transformations. It defines the confirmed final-stat minimum, player sides,
minimal source-team identities, build fields, death records, hero-only direct
interaction maps, and structured missing/conflict records. The first version
deliberately leaves competition null and excludes additional final statistics.
Its accepted bilingual hero/item/ability objects keep canonical IDs. Exact
source keys resolve before output; unconvertible keys and opaque codes become
field-specific scalar coverage evidence rather than model-facing business keys.
Unknown provider semantics remain limitations, not another scope-approval round.

Non-hero unit names and types live in a separate versioned static resource
queried through Catalog. This is independent of the existing five-file entity
Catalog publication protocol; it adds no request-time fetch or automatic unit
refresh in this migration. Capture one entity repository and one unit resource
per detail operation. Name/ID misses are local gaps; unexpected resolver or
resource failures must not be disguised as missing source keys. Generic unit
default teams do not establish live ownership. The evidence and verified sample
mapping table are in
[`reference/opendota-unit-identifiers.md`](reference/opendota-unit-identifiers.md).

The internal-consumer split is implemented: the resolver uses
`OpenDotaGameRecord`, while `GameDetailService` owns construction of
`GameDetailResult`. The public projection occurs at this Service boundary without
changing the resolver's record. Any converter that consumes a game must retain the
precise validated source timestamp and source team identities until it has
finished using them. A model-facing DTO or Artifact must not expose the original
detail as a raw member or equivalent retrieval path. The resolver already keeps
complete source collections internal and exposes only the resolution evidence
defined above. Preserve that boundary when implementing the separate detail DTO.

The closed scope, source-semantic limits, and remaining implementation work are
enumerated in the owner contract. This target
does not select frontend rendering, an HTTP shape, persistent storage, replay
parsing, or deployment changes.

### Accepted STRATZ-first game detail governance (not implemented)

The sole field/type/source owner is
[`agent/game_detail_data.md`](agent/game_detail_data.md). It keeps the eight
sections and canonical `valve_game_id`, but makes STRATZ the primary detail source.
OpenDota supplies a fixed set of data groups/event categories inside the Service,
not through model-operated fallback searches. Complete validated source records
stay internal. This does not replace the resolver's OpenDota read/evidence path.

- Remove minute `net_worth`. Every public `gold_t` value becomes
  `cumulative_gold_earned`; cumulative experience becomes `cumulative_experience`.
  Initial income and unverified STRATZ minute mappings use the explicit OpenDota
  supplemental groups. STRATZ GPM/gold-event sums do not establish total income.
- Replace final `net_worth` with `earned_gold_net_worth_gap` (累计金币与净值差),
  requiring reliable inputs at the same final instant. Otherwise null with
  coverage; do not subtract the last minute from final net worth or call the
  difference pure death loss. No minute replacement gap is added.
- Construct `events.hero_deaths` once from verified source facts; retain known
  time and supported unknown-time rows. `known_deaths` counts only located events
  through each minute, while final `deaths` stays the source total. Aggregates do
  not fabricate individual deaths. The STRATZ DEATH-gold association remains a
  candidate rule requiring additional samples, not a raw-list filter.
- STRATZ explicit Tormentor messages are usable; initial Roshan/Aegis/concrete
  building groups use OpenDota explicit objectives. A `ROSHAN` gold reason also
  appears at Tormentor times in the sample and is not a Roshan-kill predicate.
- Timed STRATZ inventory observations and ability upgrades stay under `builds`,
  separate from purchases and player minute nodes; no recipe/inventory inference.
- Outer `provider` means primary source; `sources` records successful reads and
  their own times. Coverage groups and event `source_paths` attribute facts to
  the real source. Partial death coverage, mapping gaps, and conflicts cannot
  erase usable economic/experience statistics.

Primary source/root identity failures are structured errors. Ordinary supplement
unavailability affects only dependent groups with explicit coverage; it is never
an empty list or silent whole-provider failover. Existing cancellation, local
resource, storage, and programming-error behavior remains intact. See the owner
for the exact failure policy, namespace validation, and implementation gates.
The [source reference](reference/stratz-game-detail.md) records live comparison
facts for `8960991322`; it does not certify the unwritten projection or general
coverage. Current registration flags and implementation remain unchanged.

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
labels have provenance separate from provider match facts. The accepted
`game.detail` projection adds them to its governed DTO before Artifact storage;
the complete internal OpenDota record is not rewritten. This integration is verified offline. Unknown IDs remain visible as unknown. Match statistics support only the
conclusions they encode; missing timeline, purchase, or identity data remains
unknown and must not be interpreted as proof that an event did not happen.
