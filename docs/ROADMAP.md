# Roadmap

## Guiding order

Work one capability boundary at a time:

```text
architecture confirmation
  -> one design unit
  -> implementation
  -> focused acceptance
  -> broader regression
```

Do not expand a capability into a provider-routing framework or universal DTO
before a second concrete implementation demonstrates the need.

## Commit 1: clean-slate tool layer

- Establish an artifact-only default model-facing registry baseline.
- Remove legacy domain tools, provider integrations, sample-policy mutation,
  provider prompt rules, and compatibility aliases.
- Preserve generic registry, executor, Controller, execution, tracing,
  persistence, and Artifact runtime primitives.

## Commit 2: semantic esports match search (implemented / under acceptance)

- Add the closed `esports.match.search` capability contract.
- Connect the contract to a thin PandaScore client and match adapter.
- Keep provider query syntax, transport details, and provider-private field
  names below the model-facing tool schema.
- Preserve complete validated match facts in the capability result; the generic
  registry result processor externalizes only oversized responses while keeping
  small observations inline.
- Protect the input/output boundary, request mapping, endpoint selection, and
  registry inventory with focused tests.

## Commit 3: semantic esports league search (implemented / under acceptance)

- Add the closed `esports.league.search` capability for recurring competition
  identity discovery.
- Reuse the existing PandaScore client through a second thin league adapter.
- Keep edition, season, and provider-specific fields out of the league schema.
- Protect one-request mapping, strict `id`/`name` normalization, and the exact
  four-tool registry inventory with focused tests.

## Commit 4: semantic esports series and tournament search (implemented / under acceptance)

- Add closed `esports.series.search` and `esports.tournament.search`
  capability contracts.
- Reuse the existing PandaScore client through explicit series and tournament
  adapters using their collection endpoints.
- Preserve the League → Series → Tournament → Match discovery boundaries while
  keeping provider-private query fields below the model-facing schemas.
- Protect single-request mapping, normalization, contract composability, and
  the exact six-tool registry inventory with focused tests.

## Commit 5: semantic esports team and player search (implemented / under acceptance)

- Add closed `esports.team.search` and `esports.player.search` capability
  contracts for participant identity and current-team discovery.
- Reuse the shared PandaScore client through explicit team and player collection
  adapters using `/dota2/teams` and `/dota2/players`.
- Keep provider query syntax and roster payloads below the model-facing schemas;
  `Team.players` is intentionally omitted from team identity output.
- Inherit the generic Artifact result processor without capability-specific
  externalization logic.
- Protect one-request mapping, normalization, composability, and the exact
  eight-tool registry inventory with focused tests.

## Commit 6: series participant-team capability (implemented / under acceptance)

- Add the closed `esports.series.teams` capability for one known series.
- Use the PandaScore `/dota2/series/{series_id}/teams` collection and normalize
  only participating team identities.
- Keep historical player rosters and exact per-match lineups outside this
  capability's contract.
- Reuse the shared result processor and protect the endpoint path, normalization,
  schema boundary, and nine-tool registry inventory.

## Commit 9: shared local entity-name resolver

- Add a code-internal synchronous component that resolves explicitly selected
  hero, item, and ability IDs through an injected local
  `DotaCatalogRepository`.
- Return each supplied ID, exact catalog names when found, explicit unknown entries,
  and the repository snapshot version. Validate the complete batch before any
  repository access; preserve first-seen order while deduplicating lookups.
- Keep source-field extraction in each business capability. This component does
  not scan payloads, infer IDs, call providers, or register in `ToolRegistry`.
- **Implemented:** `hero.guide` is integrated. `game.detail` remains a separate
  follow-up and has not adopted the resolver.

## Commit 10: hero-guide entity-name enrichment

- Extend guide DTOs with optional local-name fields while preserving source IDs,
  source labels, provider fields, event order, and repeated occurrences.
- Inject the shared resolver into `HeroGuideService`; resolve only fields in the
  post-filter, post-section-projection result, in at most one batch per entity
  kind. Always resolve the requested hero, including when both cache partitions
  are missing.
- Attribute names and `catalog_version` to the bundled Valve snapshot. Keep
  unknown IDs and zero-valued ability events with empty names. Require one
  catalog version across all batches.
- Enrich query DTOs only; do not write names into Redis or add lookup behavior to
  Artifact tools. Reuse generic Artifact externalization unchanged.
- **Implemented:** deterministic tests cover existing fixtures, zero-ID samples,
  section bounds, cache compatibility, composition sharing, and Artifact reads.
  `game.detail` name enrichment is a later independent follow-up.

## Shared data updates (file guide reads and scheduled refresh active on WSL; production deployment pending)

Shared game data uses a persistent file-backed update path. The WSL API reads
guide partitions from the same shared data root written by the update task. The
remaining deployment boundary is production activation and any needed one-time
import of legacy Redis guide snapshots.

1. **Implemented:** `CatalogSnapshotStore` copies the existing five
   catalog JSON files byte-for-byte, validates the copied models, catalog
   relations, and audit, and publishes each complete snapshot under a unique
   UUID revision by atomically replacing `catalog/current.json`. Failed
   publication keeps the old pointer; successful revision directories remain
   available. API startup reads this store when `DOTAMIND_DATA_DIR` is configured;
   initialization remains an explicit operator action.
2. **Implemented and run in WSL:** expose `python -m app.vnext.data_updates init-catalog`
   for one-time initialization from the bundled or explicitly selected local
   five-file catalog. The operator must supply an absolute data root with
   `--data-dir` or `DOTAMIND_DATA_DIR`; the production data directory remains
   uninitialized. The WSL fresh-data volume now has patch `7.41f`,
   revision `d0446e97add94e0fb29a30fdf4cc0905`.
3. **Implemented and used in WSL:** `FileHeroGuideCache` provides direct API
   reads and atomic partition writes. With `DOTAMIND_DATA_DIR` unset, the guide
   tool is not registered; API guide queries never fall back to Redis. The
   `migrate_redis_guides()` component and `migrate-guides` command remain only as
   a one-time importer for deployments that need to preserve existing Redis
   snapshots. No real Redis migration has been run.
4. **Implemented, not run in production:** `migrate-guides` uses the current
   Catalog hero list to import existing Redis partitions into files. Run it only
   if preserving that deployment's Redis guide data is required, then verify the
   import before switching its API to the shared data root. WSL uses its direct
   file refresh and did not import the old Redis volume.
5. **Implemented and run in WSL:** expose
   `python -m app.vnext.data_updates refresh-guides --data-dir ...`, reusing the
   serial `HeroGuideRefresher` with `FileHeroGuideCache`. It does not require a
   catalog snapshot or Redis URL. It acquires the shared data-root lock. Offline
   fake-client tests cover
   file publication and cancellation cleanup. WSL published data for 127 heroes
   with 763 requests and no guide fetch failures. The API reads files when
   `DOTAMIND_DATA_DIR` is configured; with no data root, the guide tool is absent.
   The legacy Redis refresh CLI and timer templates have been removed. The
   unified WSL timer is the supported daily job.
6. **Implemented:** add a loader that checks the current pointer by
   default every 30 seconds, validates changed snapshots in the background, and
   switches one in-memory snapshot reference only after a successful load.
   Unchanged revisions are not reloaded; failures retain the previous snapshot.
7. **Implemented:** wire API lifecycle, `catalog.lookup`, hero-guide name
   enrichment, and answer name matching to the loader. Each operation fixes one
   repository reference; a configured missing or invalid snapshot fails startup.
   This switches catalog-backed names only; it does not hot-reload image files.
8. **Implemented first step:** move the existing Valve catalog, patch-record,
   and image synchronization code into `app.integrations.valve.game_data_sync`,
   retaining the script as a thin entrypoint and preserving current behavior.
   The `--patch` argument does not fetch historical entity attributes.
9. **Implemented:** create one `ValveFetchSession` per ordinary sync run to share
   same-method/same-parameter Datafeed responses across patch identification,
   Catalog construction, and patch generation, while applying one concurrency
   limit to Datafeed calls. `--images-only` does not create a session. **Implemented:**
   Catalog construction fetches and validates its six localized lists first,
   then runs heroes→abilities alongside items/recipes in a fixed two-thread
   coordinator. Both branches share the same session and merge before the
   original five-file bundle is validated. Image CDN downloads are outside the
   Datafeed concurrency bound.
10. **Implemented for Catalog only; WSL check run:** expose
    `python -m app.vnext.data_updates refresh-catalog --data-dir ... --workers 8`
    with `--force` for same-patch rebuilds. It validates the current snapshot,
    checks Valve's latest patch, and either skips or builds and atomically
    publishes the same five-file Catalog through `CatalogSnapshotStore`. Invalid
    local pointers or snapshots can be replaced by a successful update; storage
    errors stop the run. WSL checked Valve and skipped full fetching because
    `7.41f` matched the current Catalog. This does not update patch notes, images,
    or guides.
11. **Implemented and run in WSL:** expose
    `python -m app.vnext.data_updates refresh-patches --data-dir ...` to check and
    atomically save the latest patch's legacy record under an independent
    patch-number filename. Existing valid files skip unless forced; missing or
    invalid current files can be repaired. The content SHA-256 is separate from
    patch number and Catalog revision. The WSL run wrote 100 changes for `7.41f`.
    This does not backfill history or fetch historical entity attributes.
12. **Implemented and run in WSL:** expose
    `python -m app.vnext.data_updates refresh-images --data-dir ... --workers 8`
    with `--force`. It reads one current validated Catalog snapshot, stores raw
    PNGs by SHA-256, and atomically publishes a manifest while retaining old
    entries on download failures. The WSL run downloaded 1,338 of 1,488 targets;
    150 ability images returned `download_failed`. API reads the configured
    manifest per answer match and serves retained content-hash assets; when data directory is unset,
    bundled assets remain in use.
13. **Implemented and run in WSL:** expose
    `python -m app.vnext.data_updates refresh-all` with `--workers 8` and
    `--image-workers 8`. Catalog and patch records share one bounded Datafeed
    session and run with the existing serial guide refresher; images run after a
    successful Catalog update or normal skip. Both update locks are held through
    cancellation cleanup, failures are isolated and summarized by module, and
    guide refresh is not repeated through a nested CLI. WSL's first run was
    partial due to the 150 optional ability-image failures; Catalog full fetching
    was skipped because the patch matched.
14. **Implemented configuration; WSL active, production pending:** declare a project-scoped
    `shared-data` volume and one-shot maintenance updater in WSL and production
    Compose, add an opt-in read-only API overlay, and provide a daily 03:00
    Asia/Shanghai systemd template. The updater and API use the same image; the
    updater writes and the API reads. WSL uses the overlay and its timer is
    enabled; the production host has not activated these files.
15. **Pending for production:** initialize the production data root, decide and
    verify any Redis guide migration, switch the production API to the overlay,
    and verify its scheduled update path. The first WSL timer firing is not yet
    observed.

The five-file catalog store and loader, configured API lifecycle and catalog-name
consumers, patch-gated Catalog refresh, independent latest patch-record refresh,
file-backed guide reads, guide import, file-backed guide refresh entrypoint,
persistent image serving, and unified manual refresh command are implemented.
WSL now has a fresh initialized Catalog, live patch and guide files, best-effort
image assets, API reads across an API-only recreation, and an enabled daily timer.
Catalog entity fetching skipped because the patch was unchanged; image refresh
was partial. No Redis guide migration or scheduled timer firing has been observed.
Production migration, mounts, and timer remain pending. Patch records are
independent of `refresh-catalog`; image URLs use content hashes independent of
Catalog revision and patch.
Offline tests do not establish power-loss recovery.
`game.detail` entity-name enrichment remains a later independent item after this
data-update migration.

## Subsequent capability work

1. Define one closed semantic capability contract.
2. Add its provider implementation and complete source-backed document path.
3. Protect input/output schemas, bounds, source attribution, and failures with
   deterministic tests.
4. Register the capability only after its focused acceptance passes.
5. Remove transitional code once the replacement is accepted.

## 首页与快捷查询优化

按 [PRODUCT.md](PRODUCT.md) 的首页交互契约实施；赛事候选和缓存由
[DATA.md](DATA.md) 定义，验收清单见 [EVALS.md](EVALS.md)。本阶段不新增独立
方案文档，不改变工具、Artifact 或聊天传输契约。

1. **已完成：赛事数据与缓存**：经普通后端接口和现有 Provider 层提供 Series 候选，
   实现排序、去重、冠军解析、十分钟共享缓存、并发刷新合并，以及旧数据保留。
   `GET /api/v1/home/recent-series` 已就绪。离线测试通过；真实 Provider 刷新与
   部署 Redis 行为尚未验收。
2. **已完成：赛事展示与点击发送**：替换硬编码 TI 宣传，首页显示最近五条；后端候选
   保留最多十条上限，但前端不再提供展开列表。显示来源 League 与 Series 名称，点击
   发送带名称、Series 语义和 ID 的普通文本，并保留输入草稿及当前模式。列表加载、空和
   失败不阻塞聊天。真实自由文本赛事理解仍需独立评估。
3. **已完成：输入框查询模式**：将赛事查询、英雄攻略、玩家战绩、单局解析整合为同一
   Composer 的四种模式。模式提示以不可编辑标记显示在输入框首行开头，不另占输入区顶端一行，
   也不修改草稿；发送时在正文前附加一行完整说明，继续使用普通 AssistantTransport 消息。成功交给运行时后清理未改动的草稿并重置模式；准备失败保留
   草稿。前端组件与 transport 集成测试通过；未验证真实模型的查询理解或回答质量。
4. **已完成：首页布局与抽屉交互**：调整品牌尺寸和赛事行，移除中央顶部 header，以
   两侧悬浮按钮控制聊天记录与 Trace 抽屉。桌面列宽 288px／360px 以 180ms 过渡，窄屏
   使用滑入式覆盖抽屉和淡入遮罩；关闭后立即 inert。真实 Provider 刷新、部署 Redis 行为
   与真实模型回答仍需分别验收。

## Hero guides (file-backed query and refresh active on WSL)

The internal query DTOs, bounded D2PT client, pure parsers, and fixed response
fixtures are covered by offline tests. The supported online path is file-backed:
the API registers `hero.guide` only when `DOTAMIND_DATA_DIR` selects the shared
file store, reads requested partitions directly, and never falls back to Redis.
The Service combines independent Pub and Pro source states, filters Pro examples
by position, applies section projections, and exposes pre-projection totals.
Cache misses do not trigger D2PT requests.

`HeroGuideRefresher` fetches the hero list once and requests Pub positions 1
through 5, then Pro once, for each hero in source order. Requests are sequential
with a one-second interval; successful responses publish complete file snapshots,
while fetch or parse failures preserve the prior partition. `data_updates
refresh-guides` and the daily `refresh-all` task write through
`FileHeroGuideCache`. The WSL unified timer uses the file-backed update path. The
old Redis refresh CLI and systemd timer templates have been removed.
`RedisHeroGuideCache` and `migrate-guides` remain only for an explicit one-time
import of legacy Redis snapshots during a deployment cutover. Neither refresh nor
migration is a public endpoint or model-facing tool. Application startup does not
refresh guides. Operational evidence is recorded in [`EVALS.md`](EVALS.md) and
[`reference/hero-guide-operations.md`](reference/hero-guide-operations.md).

Implementation and acceptance proceed in this order:

1. **Complete:** define the guide DTO and source boundaries, and pin the
   observed Pub and Pro response bodies as byte-for-byte test fixtures. Contract
   and fixture-integrity tests run offline.
2. **Complete:** implement the bounded D2PT fetch client with deterministic
   injected-opener tests for request shape, transport failures, response bounds,
   and minimal validation. These tests do not call D2PT.
3. **Complete:** implement and fixture-test separate Pub and Pro parsers. Pub
   supplies the primary guide; Pro contributes only examples from
   `recent_matches`. Parser tests use the fixed samples and local constructed
   cases, not live provider requests.
4. **Complete:** implement the standalone persistent cache retaining original
   response bytes, complete parsed source rows, and DTO projections, with atomic
   whole-snapshot replacement, old-value retention on failure, and explicit
   valid-empty records. Publish Pub by hero plus position and Pro by hero. The
   cache uses no TTL; freshness and Pro position filtering belong to the query
   Service.
5. **Complete:** add the cache-only `hero.guide(hero_id, position, section)`
   query capability. `DOTAMIND_DATA_DIR` selects file reads; without it, the
   guide tool is not registered. Redis is not a guide-query fallback. Query
   registration does not populate data.
6. **Complete: serial refresh executor.** Use one hero-list response in source
   order, then five Pub position requests and one Pro request per hero. Wait one
   second after every response or D2PT error, parse before publishing, retain the
   last good partition on fetch/parse failure, and abort on cache write failure.
   Offline tests use fake clients, clocks, sleeps, and file writers; no provider
   or production cache was contacted.
7. **Retired:** remove the Redis refresh CLI and its systemd templates. Retain
   the Redis adapter only for the one-time `migrate-guides` importer; scheduled
   jobs and API reads use files.
8. **Implemented and run in WSL:** add the `data_updates refresh-guides` CLI over
   the same serial refresher and file cache; protect the data root, output a safe
   report, and wait for worker I/O on cancellation. The API reads files when
   `DOTAMIND_DATA_DIR` is configured; the unified WSL timer uses `refresh-all`.
   The first scheduled firing remains unobserved.
9. **WSL deployment evidence:** a full file refresh and successful Sven and
   Anti-Mage Service queries after API-only recreation are recorded in
   [`EVALS.md`](EVALS.md) and
   [`reference/hero-guide-operations.md`](reference/hero-guide-operations.md).
   They do not establish successful timer firing, shared-file migration, API hot
   reload, another deployment's state, or real-model guide answer quality.

Do not force-match Pub item builds to skill sequences, derive recommendation
routes from Pro aggregates, manufacture a fixed number of examples, or infer
statistical meaning that the source does not establish. Local choices such as
Pub alternative thresholds, list merging/deduplication, and mapping integer
positions to source-specific strings are resolved within their implementation
stage. The DTO input position is already defined as a strict integer from 1
through 5.

Product guidance recognizes cached hero guides when enabled. Composition now
derives a short tool-name inventory from the actual Runtime registry and shares
it with execution and all answer attempts; answer tool calls remain disabled.
Deterministic regressions cover retained incorrect capability claims and an
offline guide lookup. Real-model acceptance in both new conversations and
conversations with old refusal history remains pending; scripted-model success
does not establish that real-model refusal behavior is fixed. `game.detail`
name enrichment remains a later independent item; shared data updates have
higher priority.

## Steam player and game-detail capabilities

- Define strict Steam32 inputs for player profile and recent-game observations,
  plus a Valve game-ID input for existing single-game detail.
- Preserve provider provenance and source business objects as JSON while
  keeping Steam accounts separate from PandaScore professional-player IDs.
- `player.profile` and `player.recent_games` are implemented through the shared
  STRATZ GraphQL client and register only when `DOTAMIND_STRATZ_TOKEN` is
  configured. Deterministic tests use local HTTP mocks. The profile query
  itself has not been live-verified. Recent games request an explicit
  date-descending bounded sample, validate the target player row, and preserve
  source match data for Artifact handling.
- A live spot check of match `8960882635` found matching STRATZ `Match.id` and
  OpenDota `match_id`, with matching start time and duration. A raw query for
  one participant returned 20 `player.matches` rows with nonincreasing
  timestamps under `orderBy: DESC`, each containing only that account. The
  supplied match predates that bounded sample. This is sample evidence, not a
  universal ordering or provider-availability guarantee.
- `game.detail` is implemented through an opt-in OpenDota client and adapter;
  it registers only when `DOTAMIND_OPENDOTA_ENABLED=true`. It validates returned
  `match_id` identity, preserves the complete source object, and uses generic
  Artifact handling. It does not submit or poll replay parsing. Deterministic
  HTTP-mock tests do not establish live OpenDota availability. The prior
  `8960882635` cross-source ID check remains single-match evidence only.

The account-to-game workflow is covered with deterministic Runtime composition:
the agent can continue from an account's bounded recent-games list to one
selected match, locate the exact account row, resolve known hero/item labels
from the local Valve catalog, and keep the prior list available for ordinal
follow-ups. This verifies scripted orchestration only, not real-model tool
selection or answer quality. Real provider/model evaluation remains separate.

## Optional Tavily MCP web search (implemented; live provider call unverified)

- Add the opt-in `web.search` capability through the official Python MCP SDK
  and Streamable HTTP, with the remote `tavily_search` schema discovered at API
  startup and validated locally.
- Keep credentials in the bearer transport header and keep MCP transport,
  provider adaptation, generic ToolRegistry validation, and Artifact handling
  at their existing boundaries.
- Expose only search; extraction, crawling, research, persistent MCP sessions,
  automatic rediscovery, and automatic retries remain out of scope.
- Deterministic tests use local sessions and fakes. A real Tavily MCP request
  has not been run as part of this change; use the explicit smoke command only
  when a live call is intended.

## Context Governance: Runtime-driven history compaction

The next phase is defined by
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md).
Runtime summarizes older execution history, retains recent raw messages, and
commits the current summary and kept boundary together. Bounded FIFO Artifact
locators support rereads. Follow-ups retain effective history with fresh
execution state. Storage remains process-local; restart recovery is excluded.

Implementation follows four stage exits:

1. Session execution records and shared execution/answer context construction.
2. One compaction loop, atomic summary/boundary replacement, and FIFO locators.
3. Full-input pressure, automatic compaction, bounded failure, and one overflow
   compact-and-retry recovery attempt.
4. Esports evaluations and removal of superseded summary/release gates.

Phases one, two, and three are implemented and have passed deterministic
acceptance. The verified workflows cover session records and projections,
atomic compaction, automatic full-request watermark checks for execution and
answering, bounded capacity fallbacks, one provider overflow recovery per user
request, Artifact rereads, product follow-ups, and recovery after a failed
summary candidate. The normal product entry passes the context-window
configuration into the session Runtime; an unset window leaves automatic
capacity governance disabled. These results do not claim real-model quality.

Phase four has not started: evaluate against real esports tasks and real models,
tune parameters, and clean up superseded behavior. Token capacity is an
estimate, provider overflow classification supports only its explicit current
error code, Artifact locators are bounded, summaries may omit information, and
session state remains process-local. The system does not promise to continue
arbitrarily long tasks. No real `.env` value is a project default, and this
roadmap does not imply that a service has been restarted.

No model-directed summary/release tools or general history-search tools are
required by the current design.

## Dynamic output budgets and generation recovery

The target contract is defined in
[`agent/model_output_and_recovery.md`](agent/model_output_and_recovery.md).
**Dynamic output budgets, configuration, Runtime/capacity wiring, trace capture,
Adapter-side strict tool-call batch classification, rejected-call history,
paired non-execution feedback, whole-batch execution gating, bounded generation
correction, and execution finalization are implemented and offline-tested.**
Trace records bounded rejection metadata without the raw batch. Primary/degraded
answer-truncation recovery is also implemented and offline-tested; live Provider
compatibility has not been verified. Execution continues to have no production
total step-count ceiling; the recovery boundary is consecutive failures, the
existing execution deadline, and user cancellation.

Implementation order:

1. ~~Derive expected and input-clipped actual output budgets.~~
2. ~~Strictly classify response batches and retain typed rejected-call data in the Adapter.~~
3. ~~Preserve failed call messages and encode paired non-execution results.~~
4. ~~Add Runtime whole-batch execution gating, bounded correction, and Answer Stage
   finalization.~~
5. ~~Complete the response-recovery offline acceptance matrix and trace checks.~~
6. Verify compatibility with live Providers and historical response shapes.

Content control is a later phase. This work does not add a total step limit,
change provider transport-error handling, or replace the separate summary retry
and explicit context-overflow recovery mechanisms.

## Follow-up: generic tool-result externalization (implemented / under acceptance)

- Attach one session-scoped result processor at registry composition time.
- Keep complete validated non-Artifact outputs in the session Artifact store
  when they exceed the inline bound.
- Return a deterministic bounded structural observation and opaque reference to
  the model while leaving `artifact.read` and `artifact.grep` inline.
- Protect the spill threshold, observation bound, full-result recovery, and
  Artifact-tool bypass with focused tests.

## Product chat: Run State and AssistantTransport (frontend integrated)

The accepted design and acceptance criteria are defined in
[`agent/product_run_state.md`](agent/product_run_state.md). Phase 1 lifecycle
design is approved. The product Run State schema, synchronous projection,
deterministic tests, and service integration with Runtime projection, persistence,
completed-answer retry, and repository replay are implemented. Phase 2 Runtime
lifecycle events, live delta delivery, and the event-to-state adapter are
implemented and validated. The Phase 3 backend AssistantTransport endpoint is
implemented and verified over real loopback HTTP with the official JavaScript
decoder, including live deltas, fallback, persistence, and disconnect
cancellation. The production chat frontend uses `/transport`; the per-thread
runtime registry preserves each connection and message state while switching
threads. Unread counts are session-scoped local state, clear on selection, and
update the sidebar without waiting for a session-list request. Mounted frontend
integration tests cover switching, independent stop, unread clearing, and save
updates. Actual disconnect cancels unfinished generation. Continuation after
disconnect and stream resume are excluded. The obsolete product-chat NDJSON
protocol was removed in Phase 6; the separate Runtime test-run `/runs` stream
remains.
Generation errors replace streamed text with fallback in the same message;
cancellation, disconnection, and save failures have separate semantics.
Started saves use a unified finite application-level budget; timeout preserves the
answer and cache for idempotent lookup/retry. Optional visual metadata failure
does not block canonical answer persistence.
Work one boundary at a time in this order:

1. Define the product state, message identities, history boundary, cancellation,
   persistence, interruption, and retry semantics.
2. Runtime answer-stage/attempt lifecycle events and identities are implemented
   with deterministic tests, primary/degraded answer fragments are delivered
   during the model invocation, and the request-local event-to-state adapter is
   connected to `VNextChatService` persistence, cache retry, and replay.
3. Connect the pure converter and AssistantTransport endpoint through the
   production runtime-provider in one end-to-end path, preserving authorization
   and request idempotency. Implemented.
4. Integrate independent thread runs, messages, history, and standard Markdown
   rendering; defer catalog visual enhancement. Implemented.
5. Implement execution/tool/final presentation and user-controlled folding.
   Implemented with ordered Run State activity and per-message local folding.
6. Complete failure/history regression and remove obsolete product-chat protocol
   code. Implemented; tests use the product state stream directly. The separate
   `/runs` Test Observer event stream remains independent.

First-version final answers stream as the model generates them, following the
requested ChatGPT-style interaction. Waiting for the complete answer or replaying
buffered text with a typing animation does not satisfy this requirement. Include
partial-answer interruption, fallback replacement, and canonical completion
reconciliation in the initial contract and focused checks. Resumable streams,
cross-tab recovery, raw reasoning display, and durable execution recovery are
outside this work. Failure semantics are designed in Phase 1 and tested with
each implementation phase, not postponed until the final regression phase.

## 处理过程展示优化（设计已确认，数据链路已实现）

Design is confirmed. The existing six-phase Run State and AssistantTransport
baseline remains implemented. Runtime commentary, bounded product projection,
authoritative execution timing, transport conversion, and minimal rendering in
the existing process panel are implemented. The enhanced timeline UI and its
visual acceptance remain pending. This work does not add raw reasoning, a
summary-generation call, or durable process logs.
The detailed contract is in
[`agent/product_run_state.md`](agent/product_run_state.md).

1. **已实现：** 将已接受工具调用响应中的过程说明作为有界 Run State 活动发布，
   并提供执行用时与终止时间事实；现有面板可按顺序显示说明文本。
2. **待实现：** 实现轻量时间线、中文工具名称、相邻调用合并、工具活动文字动画，以及首次进入
   回答阶段时自动收起并保留后续用户选择。
3. **待验收：** 第二项完成后检查增强 UI 的自动化行为并观察桌面和窄屏真实页面，再决定是否需要调整提示词。

## Not planned in the baseline

- a complete domain tool suite before each capability contract is accepted;
- provider selection or routing machinery;
- a universal esports hierarchy or cross-provider DTO;
- hidden provider fetches from Artifact tools;
- scenario-specific workflows or prompt recipes;
- sample-size or provider-specific plan mutation.
