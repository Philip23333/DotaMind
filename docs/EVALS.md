# Evals

Evaluation separates deterministic mechanical acceptance from real-model
quality review. A successful tool execution or completed Runtime workflow is
not, by itself, evidence that an answer is correct.

## Current tool surface

The normal vNext registry composes the generic Artifact tools, the currently
accepted esports capabilities, and request-scoped task planning when a
`TaskStateCoordinator` is supplied. The model-facing names are:

```text
artifact.grep
artifact.read
esports.league.search
esports.series.search
esports.series.teams
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
web.search                 # only when Tavily MCP discovery succeeds
task.plan                 # when task-state coordination is enabled
task.checkpoint           # when task-state coordination is enabled
```

The Context Governance evaluation adds only its local `fixture.edition.lookup`
fixture tool to that evaluation's registry. It does not register live esports
providers, and it does not change the product registry.

## Three evaluation layers

1. **Deterministic tests** use local fakes and fixed payloads to verify schemas,
   Artifact bounds and retrieval, Runtime state transitions, context accounting,
   failure behavior, and tracing. They make no provider calls.
2. **Real model with fixed synthetic data** evaluates model behavior against
   stable, explicitly synthetic tournament records. The Context Governance
   harness uses real Runtime, SessionHistory, task-state tools, Artifact
   externalization, and `artifact.read` / `artifact.grep`; only the model API is
   live. The fixture is not TI history and must not be reported as real esports
   evidence.
3. **Real model with real data sources** evaluates the end-to-end product
   against live capability providers and current esports data. This is a later
   evaluation step; provider volatility and outages are not deterministic test
   failures.

## 首页赛事、输入框模式与抽屉验收

后端 Provider、候选服务、缓存和 HTTP 路由有离线确定性测试。前端实现首页近期 Series
列表、直接发送、四种 Composer 模式及左右会话抽屉。前端测试只验证发送文本和状态管理，
不代表真实模型已能正确理解并回答这些查询；真实 Provider 验收与部署行为也需单独验证。
离线验收覆盖：

- 进行中 Series 按开始时间倒序优先、结束项按结束时间倒序补齐；超过上限、
  不足上限、ID 重复、日期缺失和有效空列表都得到契约规定的结果。
- 每轮刷新先并行启动 running/past，再按候选顺序并行补全；lifecycle、Tournament、Team
  的实际 Provider 请求共用最多六个并发槽。事件控制测试验证峰值达到六时第七个请求等待，
  释放请求后继续执行；六是上限，不要求每轮都达到峰值。
- Tournament 完成前不启动对应 Team 查询；同一 Team ID 的并发候选共享一个查询任务，
  包括查询未命中或可选 Provider 错误后的 `null` 结果。反序完成的补全仍按原候选顺序发布。
- 可选 Tournament/Team 查询失败只留空冠军并保留赛事行；running/past 任一必需查询失败时，
  取消并等待兄弟请求，保留旧快照且不发布部分列表。服务关闭会回收 lifecycle、候选和 Team 子任务；
  测试使用事件而非真实网络或固定睡眠控制这些边界。
- 候选最多十条，首页只显示其前五条；原生 Series Team 胜者优先，只有 Series
  `winner_id` 缺失时才查询该 Series 的 Tournament，并且只接受名称精确匹配
  `Playoffs` 的 Team 胜者。名称解析失败时不展示冠军，未知赛制不作推断。
- `league_name` 只取 Series 的 `league.name`，首尾空格会去除；字段缺失、非字符串
  或空文本变成 `null`。旧 Redis 快照和旧 HTTP 响应缺少该字段仍能读取；首页显示
  与点击查询使用同一个 League／Series 组合名。
- 新鲜缓存直接返回；过期成功快照在 Provider 刷新结束前立即返回，并只启动一个服务持有的
  后台任务；后续请求能读到新快照。冷缓存并发请求等待同一任务，单个等待者取消不取消
  刷新。刷新失败保留旧成功数据并单独记录状态；失败后 600 秒内不重复请求，Redis 记录的
  间隔能跨服务重建保留，记录失败本身写入失败时同一实例仍限频。关闭服务会取消并回收
  刷新任务，然后才关闭 Redis。有效空响应与请求失败保持可区分；无旧缓存时失败返回不可用。
- 普通 GET 对过期成功快照立即返回并启动后台刷新；新鲜快照直接返回。手动
  `POST /api/v1/home/recent-series/refresh` 即使缓存新鲜也请求上游并等待结果；同一刷新任务只执行一次，
  多个手动等待者复用它，取消一个等待者不取消共享任务。
- 手动冷却从共享任务启动时计 60 秒，服务重建后仍有效，59 秒拒绝、60 秒允许；长任务完成前仍显示刷新中，
  完成后若冷却已过期可立即刷新。手动请求加入既有后台任务时沿用该任务的原始启动时刻，不延长冷却。
  失败后的 600 秒限制与手动冷却取更晚者，限频期间不新增上游调用。
- 手动刷新失败保留旧候选并显示失败，即使该缓存仍在十分钟新鲜期内；无旧缓存时显示不可用和重试入口。
  Redis 写入手动冷却失败时请求失败且 Provider 零调用。旧 Redis 缓存缺少冷却字段可读取；Redis 服务重建后保留
  手动冷却和失败限频。普通 GET 不受手动冷却影响。
- 前端首次 GET 使用后端 `server_time` 与 `manual_refresh_available_at` 初始化倒计时；刷新和失败重试使用 POST。
  请求期间旧列表持续可见，按钮显示“正在刷新...”并禁用；请求结束后按后端允许时间倒计时，所有重试入口同步禁用。
  计时到零恢复按钮，不发请求；网络失败保留旧列表且不自行编造冷却。卸载时清理计时器。有效空列表仍显示实际更新时间，
  候选内容未变但 `retrieved_at` 改变时也更新时间。
- 首页只显示五条候选，赛事点击直接发送包含名称、`Series` 语义和正确 ID 的普通文本，
  不误用 Tournament 或 Match ID。点击时保留输入草稿和当前模式。首页刷新按钮和失败重试
  仍使用首页候选接口；刷新和重试走手动 POST；没有展开候选弹层。
- 状态分别用蓝色与绿色标签呈现；缺冠军不出现占位文字。名称组合、状态色和小屏换行
  不覆盖日期或冠军。
- Composer 模式按钮顺序和可访问名称固定为赛事查询、英雄攻略、玩家战绩、单局解析。
  点击模式后，在输入框首行开头显示不可编辑提示；切换或取消模式不改变草稿文本。悬浮与键盘
  聚焦显示按钮说明。发送时附加完整纯文本说明，保留用户正文和换行。只有模式提示而正文为空时
  仍不可发送。
- AssistantTransport 集成测试验证每次模式发送只产生一条普通用户消息；运行时接受后恢复普通
  模式并清除未改动的原草稿。历史准备失败保留模式和草稿。发送等待期间捕获的文本不被后续
  编辑替换，用户新写的草稿和新模式不被清理。会话切换会重置模式；生成期间仍可编辑下一条
  草稿、切换模式和使用停止按钮，不额外发送请求。
- 桌面从 1024px 起左右栏默认收起且可独立打开；小屏抽屉为覆盖布局，支持 Escape、遮罩关闭
  和焦点恢复，关闭状态立即 inert。抽屉开合期间 Thread 与 RuntimeProvider 保持挂载，现有
  transport 不取消；Trace 关闭时不读取列表，切换活动会话后不显示旧响应。

自动化测试验证状态和数据流；180ms 抽屉动效不以持续时间断言，桌面、窄屏布局及 reduced-motion
样式仍需浏览器视觉检查。真实模型查询理解、工具选择与回答质量未在本轮验证。

本轮新增的刷新生命周期测试使用 Fake Redis、假时钟和异步事件，不调用真实
Provider，也不依赖长时间等待。它验证普通旧快照立即返回、手动 POST 强制刷新、冷／热并发
合并、单个请求取消隔离、手动冷却在 59 秒与 60 秒的边界、600 秒失败间隔、服务重建后的限制、
冷却写入失败时不启动 Provider，以及关闭时的任务取消和回收。提供者真实数据
验收另行确认真实候选和获胜对象映射；确定性 fixture 不能证明上游长期稳定或冠军
信息始终可用。

冠军补全的离线回归分别覆盖：Series 原生 Team 胜者优先且不请求 Tournament；
Series 缺少胜者时经 `httpx.MockTransport` 验证 Tournament 过滤请求、Playoffs
来源字段映射、精确 Team 名称解析及快照往返；Playoffs 没有 Team 胜者或其请求失败
时仍返回赛事列表并省略冠军。该验收使用合成响应，不请求真实 PandaScore，也不代表
真实 Provider 当前数据或所有 Series 均能解析冠军。

## Chat process commentary and compact timeline (implemented; real-text observation pending)

The contract is owned by [`agent/product_run_state.md`](agent/product_run_state.md).
Focused tests verify the Runtime event boundary, ordered bounded projection,
execution timing, transport metadata, and the compact timeline:

- Accepted non-empty ordinary content is published once before tool activities;
  no-tool conclusions and rejected responses do not appear as commentary.
- Commentary remains separate from answer text and is capped at 2,000 Unicode
  code points under the existing activity-count bound.
- Backend timing starts at AgentStarted and freezes at AnswerStageStarted or an
  earlier failure/cancellation; answer output and saving are excluded.
- Answer retries, completion, and persistence updates do not change frozen timing.

Focused frontend acceptance covers the presentation projection:

- Adjacent calls with identical tool IDs merge in presentation, commentary breaks
  the group, and failure/unconfirmed status remains visible.
- The process area collapses once on first Answer Stage entry; reopening it
  preserves the user's choice through answer and persistence updates.
- Tool labels use the confirmed Chinese map, unknown tools use a generic label,
  and terminal runs do not retain active wording or animation.
- The timer advances only during active execution, freezes to backend timing,
  stops on an unconfirmed disconnect, and does not fabricate historical time.

Browser fixture review covers desktop and narrow layouts, long commentary,
repeated tools, timer, folding, and final-answer separation. Real model text
observation remains pending: observe mixed language, length, internal terminology,
and perceived timing. This is qualitative review; the existing prompt is
unchanged. No A/B prompt test is a prerequisite, and passing does not require all
commentary to be Chinese or short. Ordinary process text is not a verified fact
or a required summary.

## Enabled capability inventory and guide answers

Offline acceptance compares execution schemas and the shared inventory against
the same registry, in registration order, both with and without `hero.guide`.
An empty registry explicitly renders `none`. Product guidance distinguishes
unsupported capabilities, missing data, and failed lookups; the inventory must
not claim that a query has succeeded. Optional web-search guidance remains
conditional on the registered search capability.

Request-level regressions cover normal answers, answer overflow recovery/retry,
and degraded answers: all retain the inventory exactly once, while answer
requests keep `tools=[]` and exclude execution-only instructions. Input message
lists are unchanged. A scripted Runtime regression retains earlier assistant
claims such as "no hero guides" and "only web search", verifies the current
`hero.guide` schema and inventory, executes an offline handler, and confirms its
evidence reaches the answer stage. These tests establish request plumbing and
stage boundaries, not real-model willingness to use the tool.

Real-model acceptance remains pending. It must separately exercise a new
conversation and one retaining incorrect refusal history, using a known guide
cache state. Inspect traces for supported lookup selection, appropriate missing
input questions, and evidence-grounded answers. Also distinguish registered
tools with missing cache data or failed reads from unsupported capabilities.
Capability questions should be answered without executing tools; concrete guide
requests should not be rejected solely because of an earlier assistant claim.

## Context Governance harness

Run commands from `apps/api`. Without `--execute`, the command validates the
selected profile and fixture, prints a redacted run summary, and makes no model
call or output artifacts:

```bash
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m \
  tests.vnext.evals.context_governance_runner \
  --profile pressure \
  --output-dir /tmp/dotamind-context-eval/dry-run
```

To explicitly allow one bounded real-model evaluation, add `--execute` and use
a new output directory:

```bash
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m \
  tests.vnext.evals.context_governance_runner \
  --profile pressure \
  --output-dir /tmp/dotamind-context-eval/run-001 \
  --execute
```

Each invocation runs exactly one profile (`baseline`, `current`, or `pressure`)
and the same two fixed follow-up questions in one session. Profiles are not
automatically iterated. `current` and `pressure` require a configured context
window. `baseline` disables automatic capacity management but the evaluator
client applies the same business output-token cap as other profiles. `pressure`
sets `context_compaction_test_trigger_percent=1` and a recent-history target
equivalent to 4096 serialized bytes, rounded up using the configured
`context_estimate_bytes_per_token` (2048 estimated tokens at the default ratio
of 2); these are pressure-test overrides, not product recommendations. The
`baseline` profile clears both the configured context window and test trigger.
`current` preserves actual configuration, including any explicitly configured
test percentage, so it does not necessarily represent the pure production
threshold. `pressure` reports its effective test percentage and recent-history
budget in the run report and manifest.

With no test override, production compaction starts when the estimated input
exceeds `context_window_tokens - compaction_reserve_tokens`. A test percentage
is rounded up from the input capacity remaining after the current request's
output reserve and safety margin; the effective threshold is the earlier of
the production and test thresholds. Capacity estimates use configured UTF-8
bytes-per-token ratios rather than an exact tokenizer. Each complete summary
request, including its instruction, prior summary, and source history, must fit
its model window with the summary-specific output allowance and safety margin.
When both history and turn-prefix summaries are needed, both are checked before
the first summary call. No fixed summary-input byte limit applies.

The default shared limits are at most 12 model calls (including summary and
retry calls) and 180 wall-clock seconds for both questions together. CLI
overrides may lower or raise these bounds for a deliberate run. There are no
automatic provider retries beyond Runtime behavior, no repeated runs, and no
automatic profile sweep. Provider usage is reported separately for business
and summary requests; missing usage is unknown, byte estimates are not token
counts, and no cost is estimated without price data.

`DOTAMIND_COMPACTION_MAX_RETRIES` applies only to classified transient summary
errors, independently per summary segment; every actual retry is a separate
model call charged to this shared evaluation budget. Retry waits consume the
existing Runtime stage deadline. Truncation and other deterministic summary
failures do not retry, and summary retries do not add another provider-overflow
recovery allowance.

An executed run creates `manifest.json`, `calls.jsonl`, `traces.json`, and
`report.md`. Existing files with those names are never overwritten. Requests,
responses, usages, errors (type only), durations, and partial traces are kept
for review; credentials, authorization headers, full settings, and authenticated
URLs are not recorded. Failed and budget-terminated runs retain collected
artifacts and exit nonzero. A pressure run without a successful compaction says
that it did not evaluate post-compaction model behavior.

Review the actual answers, evidence observations, and traces manually. The
report's checklist starts as **待人工评审**; a completed workflow does not mark
the answer correct. For a real-model run, confirm the selected model, configured
window, output artifacts, and spend limits before passing `--execute`.

The runner reads model and AgentLimits configuration using
`VNextSettings.from_env()`. It does not edit `.env`, infer a provider's actual
window, or make the local token heuristic an exact tokenizer. Real evaluation
results do not become product defaults without a separate review.

## General agent checks

Agent-level evaluation should verify that the model follows the rendered tool
catalog, uses declared arguments and returned references, stops when evidence
is sufficient, and does not claim facts unsupported by collected observations.
Task-plan generalization covers temporal, entity, player, competition, hybrid,
and single-deep cases without prescribing exact task keys or a fixed retrieval
sequence. A deterministic checkpoint-source regression also covers eight
synthetic inline match records under the default 12 KiB inline bound: the current task
checkpoints them by their original query call ID, advances to the second task,
and reaches a final answer without `artifact.read` or creating an Artifact.
Companion checks reject externalized previews, control results, failures,
receipts, deferred results, stale IDs, and cross-task ownership while retaining
the existing raw `artifact.read` checkpoint path. These checks verify Runtime
source eligibility and lifecycle only; checkpoint success does not certify
business facts.

### Steam player and game-detail checks

Deterministic contract tests cover strict Steam32 and Valve game-ID inputs,
closed outer schemas, provenance literals, timezone-aware retrieval timestamps,
profile-presence semantics, recent-game count and duplicate-ID bounds, and
lossless JSON-compatible source fields. A composition check passes a game ID
from a recent-game result directly into the detail input. MockTransport tests
exercise both STRATZ player queries and their source validation/error paths,
Artifact externalization/retrieval, and token-gated registration without
network access; shared-client cancellation cleanup remains covered by the
profile/client regression tests. A live cross-check for `8960882635` matched
STRATZ `Match.id` with OpenDota `match_id`, start time, and duration. A raw live
`player.matches` query for one participant returned 20 rows in nonincreasing
timestamp order with only that player's row; the supplied match was older than
the returned sample. This is one-account evidence, not a universal guarantee.
`player.profile` and `player.recent_games` register with a STRATZ token;
`game.detail` registers only when OpenDota is explicitly enabled.
`game.detail` is covered by deterministic OpenDota MockTransport tests and is
opt-in at composition; no live OpenDota request was made for this
implementation. The earlier cross-source ID observation is limited to
`8960882635`. Later live or fixture-backed
cross-source evaluation must verify any proposed relationship between a
Steam32 account and a PandaScore professional player from explicit evidence;
the shared appearance of a player or event is not sufficient. These tests do
not establish general current STRATZ availability or every source business
meaning.

The account-to-game workflow tests use the real Runtime, registry, session
history, Artifact externalization/read path, and local Valve catalog with
scripted model responses and synthetic provider data. They verify selected
Valve IDs, exact `account_id` matching, ordinal follow-ups against the prior
list, and preservation of missing or conflicting source values. These tests
verify orchestration and evidence handling only; they do not establish that a
real model will choose the tools correctly or produce an accurate analysis.
No real STRATZ, OpenDota, or model request is made by this workflow suite.

The code-internal `EntityNameResolver` acceptance uses a call-recording fake
repository and the committed static Valve catalog. It covers strict batch ID
validation before repository access, kind-specific dispatch, first-seen
deduplication, the reserved zero value, unknown-ID and unexpected-error
semantics, missing names, result isolation, and repository-sourced catalog
versioning. The static-catalog integration check compares a present hero, item,
and ability directly with their repository records and checks zero plus an
absent ID. Follow-on hero-guide enrichment tests use the actual local catalog,
the committed Sven Pub/Pro samples, and the three Pro zero-ID fixtures. They
cover query-time Service enrichment, section-specific lookup bounds, duplicate
skill-sequence alignment, unknown IDs, copied output objects, missing-cache
hero names, version mismatch and resolver-error propagation, old Redis snapshot
decoding, composition repository sharing, tool non-use of `catalog.lookup`, and
name retrieval through the existing Artifact path. These are offline checks;
they do not establish real-model answer quality. `game.detail` remains outside
this integration.

Context Governance evaluation measures answer omissions, complete-request
peaks, summary and locator overhead, successful compactions, recovery attempts,
Artifact rereads, provider-reported tokens, and latency. A provider-confirmed
context-window overflow has a shared allowance of **at most one recovery per
user request**; execution and primary answer share it, while summary calls and
degraded answers do not start recovery. Recovery does not replay completed
business tools.

Deterministic tests protect state and protocol invariants. Traces from real
models assess summary quality and recovery behavior; byte accounting remains a
heuristic input measure rather than a precise token count. The stage status and
known limitations are maintained in
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md).

## Live source checks

Live source smoke tests are separate from both deterministic tests and the
fixed-fixture model evaluation. Use them only for a concrete current integration
question. Provider outages, expired credentials, and changing schedules must
not turn into deterministic test failures.

Never commit credentials, authorization headers, request tokens, or material
user data.

## Hero guide evaluation (file-backed query and refresh active on WSL; production deployment pending)

The D2PT probe recorded in [`reference/d2pt.md`](reference/d2pt.md) is a live
connectivity and sample-shape check for one Sven Pub row and one Sven Pro row.
It is distinct from the historical local full refresh recorded below. Neither
result proves a successful automatic timer firing, full parser correctness for
every source shape, or model answer quality.

The current offline acceptance covers strict DTO inputs, independent Pub/Pro
metadata, source-shaped JSON preservation, byte/hash/shape checks for the fixed
raw response fixtures, deterministic HTTP-client behavior through an
injected fake opener, Pub/Pro fixture parsing, the file cache, and the internal
`HeroGuideRefresher`. Fake Redis coverage remains for the one-time legacy import.
Client tests cover request URLs and headers, timeout and response-size bounds,
status/error handling, JSON and minimal schema validation, and response closure.
Parser tests cover the observed Sven fields and counts, the additional Pro
zero-ID samples, all-record ordering, source-position evidence, strict type and
identity validation, all-or-nothing failure, and deep-copy behavior. Cache tests use a fake Redis to verify whole
snapshot replacement, one-command HSET/HGETALL shapes, Pub/Pro key isolation,
raw bytes/source rows/DTO round-trips, failure retention, valid-empty snapshots,
corruption errors, and input/output mutation isolation. Service and tool tests
cover sections, matching, staleness, source metadata, partial read failures,
structured errors, conditional registration, composition injection, and large
result Artifact reads. Application wiring is exercised with fake external
resources. Refresh-executor tests use synchronous fake-client methods, fake
sleep, fake clocks, and fake caches; they cover source-order traversal, one
request at a time on a worker thread, the request→sleep→parse/publish sequence,
`1 + 6 × hero_count` calls, bounded per-partition failure handling, cancellation
and unexpected-error propagation, report counts, and old-snapshot retention
followed by successful replacement using the real cache component over fake
Redis. These checks make no network, live Redis, database, or model call; they do
not establish all-hero or all-position parser coverage, deployment persistence,
or AOF recovery.

Three additional raw Pro fixtures captured during the bounded 2026-09-28 parser
diagnosis exercise full `recent_matches` and ability-event ordering. They contain
7, 67, and 9 zero-valued `ability_id` events for hero IDs 1, 2, and 5. The tests
verify those events and source fields survive parsing; this is regression
coverage for the observed pattern, not Pro full-hero acceptance or evidence that
other previously failed heroes now parse.

The former Redis guide-refresh CLI tests were removed with that entrypoint and
its systemd templates. Redis remains an application dependency for unrelated
stores and is used by `migrate-guides` only when an operator explicitly imports
legacy guide partitions.

The `refresh-guides` data-update CLI is covered with a fake D2PT client and
temporary data roots. Tests verify that no Redis URL or client is required, the
shared data-root lock prevents provider construction when busy, the report is
emitted as one safe JSON line with ISO timestamps and fixed exit codes, cache
errors are redacted, and cancellation waits for a blocked file-write worker before
the lock is released. No real refresh is performed by these tests.

The standalone `FileHeroGuideCache` acceptance uses temporary directories and
the committed Sven Pub/Pro fixtures plus all three Pro fixtures containing
zero-valued ability events. It covers complete entry round-trips, partition
isolation, missing versus valid-empty versus failed states, retention and
recovery, strict identities and error codes, import conflicts and idempotency,
damaged-file handling, and atomic-write failure and visibility. The migration
tests use `FakeRedis`; they verify pre-I/O hero-list validation, first-seen order,
the five Pub reads followed by one Pro read per hero, complete status import,
read-back equality, safe resume, and absence of Redis writes, deletes, or expiry
operations. These tests do not connect to Redis or run an actual data migration.

`test_file_guide_refresh.py` connects the real `HeroGuideRefresher` to the real
`FileHeroGuideCache` with fake D2PT responses. It verifies the seven serial
requests for one hero, one-second waits through an injected sleeper, source byte
and row retention, DTO projection and attempt times, valid empty partitions,
failure retention followed by recovery, and abort on file-write failure. It does
not access D2PT, Redis, catalog files, or images.

`test_file_guide_api_wiring.py` verifies that `DOTAMIND_DATA_DIR` selects file
guide reads, and that no data directory leaves the guide tool unavailable even
when the application has Redis for unrelated stores.
It runs the existing Sven fixtures through the real file cache, Service, tool,
and Artifact read path; checks names, source metadata, totals, sections, and
exclusion of raw bytes/source rows; and covers immediate visibility after an
atomic replacement, missing versus empty data, retained success with a failed
attempt, single/both partition corruption, and query-time read-only behavior.
A gated file read with a Catalog loader publication verifies that one query
keeps the resolver captured before its cache wait while the next query sees the
new snapshot. These are offline tests and do not exercise a deployed data root.

### Catalog snapshot store acceptance (implemented)

`CatalogSnapshotStore` is covered by offline `tmp_path` tests using copies of the
committed five-file Valve catalog. They verify byte-preserving copies, ignored
extra files, runtime Repository queries, distinct UUID revisions for the same
patch, retention of prior revisions and already-loaded repositories, all five
required files, catalog/audit validation, failure injection during copy, final
directory rename, and pointer replacement, plus reads on both sides of the
atomic pointer switch. Invalid pointers and missing revisions are rejected with
stable store-error reasons. These tests do not write to the committed catalog,
call providers, or establish power-loss recovery. API reads are covered by the
separate loader and wiring tests.

### Valve sync application module (offline acceptance)

`test_valve_sync_entrypoint.py` verifies direct application-module import without
sync side effects, both module and legacy-script `--help` entrypoints, default
arguments, worker-range rejection, cwd-independent resource/output paths, the
`--images-only` path, and that the old script contains only its bootstrap and
forwarding call. The moved alias YAML has the same SHA-256 bytes as its prior
script location. `test_dota_catalog_sync.py` also exercises Catalog/audit and
recipe generation plus patch-record projection with fixed fake Datafeed input.
`test_valve_fetch_session.py` covers explicit endpoint forwarding, per-session
success and failure reuse, deep-copy isolation, parameter-key separation,
simultaneous duplicates, a shared mixed-endpoint concurrency ceiling, quota
release after failure, and fresh requests in a new session. A workflow test
confirms Catalog and patch generation share one session and reuse English lists
without conflating Chinese requests. These tests use fake clients and events; they
make no network request and do not execute a real synchronization.
`test_valve_catalog_tasks.py` verifies list-first identity checks, the concurrent
hero-to-ability and item branches, shared Datafeed bounds, the `workers=1` path,
stable output under opposite branch completion orders, no duplicate hero detail
fetches, and waiting for an already-started branch after failure. It also checks
talent values, supplemental abilities, recipe relations, and the reviewed item
exclusion. `test_valve_image_client.py` and `test_image_refresh.py` cover fixed
Valve URLs, raw PNG bounds/signature checks, response closure, safe transport
errors, Catalog-selected targets, content-hash reuse, skip and force behavior,
failure retention, one-snapshot consistency, worker bounds, and atomic manifest
publication. The fake opener prevents CDN access.

`test_catalog_refresh.py` uses the committed catalog only as a local test source
and publishes into `tmp_path`. It verifies same-patch skip without file or mtime
changes, patch-change publication, forced same-patch publication, first-time
initialization, recovery from invalid pointers and snapshots, storage and remote
check failures, retry after an unsuccessful build, shared five-file serialization,
preservation of old revisions, and temporary-directory cleanup. The extended
data-update CLI tests cover a single bounded Valve session, no Redis or guide-lock
use, lock contention before client construction, worker validation, safe JSON, and
cancellation waiting for the worker before releasing the data lock. These checks
use fakes and temporary directories; they do not call Valve or establish deployment
behavior.

`test_patch_refresh.py` uses a fake Valve session and temporary data roots. It
checks latest-patch skip/force decisions, independent per-patch files, legacy
record validation, repair of missing or invalid files, safe rejection of invalid
patch IDs and non-finite JSON numbers, content hashes, and atomic-write failure
retention. The extended CLI tests cover the data-root lock, one session, safe
single-line output, no Redis or guide lock, and cancellation waiting for the
worker before lock release. These tests do not call Valve or modify bundled data.

The offline data-update CLI tests use temporary data roots and FakeRedis. They
cover absolute data-root validation and argument-over-environment precedence,
first catalog initialization, safe skip on a valid existing pointer, corrupt
pointer/source failures, and publication from the bundled five-file source.
Migration tests verify that a missing or corrupt current catalog prevents Redis
construction, the hero list comes from the loaded snapshot, the existing
importer reports counts, identical partitions skip on a repeated run, and Redis
is never written, deleted, or expired. Lock tests cover data-lock contention,
the old refresh-lock order, release of the first lock when the second cannot be
acquired, and cleanup after failure or cancellation. Output tests check one-line
JSON, fixed safe reasons, credential redaction, help without I/O, and Redis
client closure. These checks do not connect to Redis or perform initialization
or migration against an operational data root.

### Catalog snapshot loader and API integration acceptance (implemented offline)

`CatalogSnapshotLoader` and the revision-only pointer read have offline
`tmp_path` coverage. Tests exercise startup and retry after failure, idempotent
start/stop, pointer-only checks for unchanged revisions, complete background
loads before reference replacement, old-reference availability during a load,
failure retention and later recovery, pointer disappearance and IO errors,
revision changes and rollback without UUID ordering, serialized concurrent
refreshes, stop waiting for active work, restart from disk, finite interval
validation, and fixed-reason logging. They also verify that reads do not write
snapshot or source files.

`test_catalog_api_wiring.py` verifies optional/invalid `DOTAMIND_DATA_DIR`
configuration, loader startup before consumer construction, startup failure for a
missing or corrupt configured snapshot, loader cleanup after normal shutdown,
later initialization failure, and startup cancellation. It checks that API reads
do not write the data root, that composition and presentation receive the same
repository provider, and that concurrent guide queries keep the repository each
captured before their cache wait. Catalog lookup tests verify one repository per
call, and presentation tests verify a same-patch repository replacement refreshes
the matching records. These checks are offline and do not connect to a real Redis,
database, provider, or model. They validate code wiring, not deployment state.

### Shared file-update acceptance (WSL live run and activation complete; scheduled firing and production pending)

The catalog store, patch-gated Catalog refresh, independent patch-record refresh,
persistent image refresh, unified refresh coordinator, loader, and configured API
consumer wiring have focused offline acceptance. A fresh WSL data root, live
`refresh-all`, read-only API mount, API-only recreation, and WSL timer activation
have also been checked. Production and an actual scheduled firing remain pending.

| Layer | Evidence and remaining scope |
|---|---|
| Catalog publication | Offline tests cover failure retention. WSL `init-catalog` published patch `7.41f`, revision `d0446e97add94e0fb29a30fdf4cc0905`. Live `refresh-all` checked Valve and skipped full entity fetching because the patch was unchanged; a changed-patch publication was not exercised. |
| Patch records | Offline tests cover validation, skip/force, SHA-256 reporting, and atomic replacement. The WSL run wrote patch `7.41f` with 100 changes and content SHA-256 `50e10530e0d2de4967df94a1331b43f8f4b13b16ab455cb9a8ca99db099b30df`. Historical patch backfill is not implemented. |
| Migration execution and guide switch | This WSL cutover used a fresh file store, so no Redis guide migration was run and old Docker Desktop volumes remain untouched. File guide refresh succeeded for 127 heroes with 763 requests. The API reads the same file volume; Sven and Anti-Mage position-1 Service queries each returned one Pub guide and five Pro examples. The old WSL Redis timer is disabled. Production migration remains separate. |
| Catalog version gate | Offline tests verify that a valid same-patch Catalog skips full entity fetching, `--force` refreshes the same patch, version-check failures do not skip, and a failed update is attempted again on the next invocation. This is DotaMind policy, not a Valve guarantee about same-patch data changes. |
| Fetch sharing and bounds | `refresh-all` starts Catalog and patch work with the same session and response cache; its configured Datafeed ceiling is shared by those branches. Images wait for Catalog success or skip and use the independent 1–16 image-worker bound. Guides run alongside them through the existing serial refresher and one-second request spacing. Offline tests cover gating, report retention, failure isolation, and cancellation cleanup. |
| Catalog hot reload | Offline tests prove validated snapshot switching and per-operation pinning. WSL API startup and file reads passed; Catalog hot-switch was not exercised because the live patch gate skipped fetching. The API container was recreated and retained its Catalog and guide reads. |
| Images | The WSL run downloaded 1,338 of 1,488 targets; 150 ability images reported `download_failed`. A Sven hash URL returned PNG bytes with matching SHA-256 and immutable cache headers. API image reads are backed by the persistent volume. |
| Container configuration | Compose uses the same API image for API and updater. The WSL updater wrote the project-scoped volume; the API mount is `RW=false`. Recreating only the API kept Catalog, guide, and image reads available; other service container IDs remained unchanged. |
| Scheduling configuration | `dotamind-data-update.timer` is installed, enabled, and active in WSL for 03:00 Asia/Shanghai with `Persistent=false`; next fire is 2026-10-03 03:00 CST. The legacy guide timer is disabled and inactive. No scheduled run has fired yet; production has not installed the timer. |
| Model behavior | Query inputs and DTOs remain stable; source attribution, catalog-name use, and generic Artifact access do not regress. |

### WSL live refresh evidence (2026-10-02)

The first unified refresh ran from 2026-10-02 15:20 to 15:49 CST with no `--force`.
Catalog checked Valve's latest patch and skipped full entity fetching because
`7.41f` matched revision `d0446e97add94e0fb29a30fdf4cc0905`. Patch records updated
with 100 changes. The guide module succeeded for 127 heroes with 763 requests,
publishing 635 Pub and 127 Pro partitions and recording 143 empty Pub plus 3 empty
Pro partitions. Images downloaded 1,338 of 1,488 targets and reported 150
`download_failed` ability images, so the overall result was partial.

After the API container was recreated by itself, the API remained healthy and its
read-only data mount still served the current Catalog and guide entries. Service
queries for Sven and Anti-Mage position 1 each returned one Pub guide and five Pro
examples. A Sven hash URL returned PNG bytes with a matching SHA-256 and immutable
cache headers. The unified WSL timer is enabled for the next 03:00 CST run, but no
scheduled firing has yet been observed. This is local WSL evidence only; it does
not establish production state or real-model answer quality.

Remaining acceptance layers are separate:

1. **Scheduled deployment:** the unified WSL timer is enabled, and the legacy
   guide timer is disabled. The first scheduled firing, lock behavior, and module
   report still need observation. Production scheduling remains unconfigured.
   Offline lock tests do not establish multi-container coordination.
2. **Persistence and container boundary:** WSL API-only recreation preserved the
   new shared volume, with the API mount verified read-only. The old Docker
   Desktop volumes remain separate and untouched. Production persistence is not
   established by this local check.
3. **Real update:** WSL live update behavior is recorded above. The unchanged
   patch meant Catalog full-entity publication was not exercised; the image
   result remains partial. Future patch changes, update failures, and production
   operation still require their own evidence.
4. **Real-model answer:** a separate evaluation checks whether the model answers
   from Pub guide and Pro examples, keeps the sources distinct, and avoids
   unsupported statistical or causal claims. A successful refresh does not imply
   answer quality.

### Tavily MCP smoke check

The offline smoke command is dry unless `--execute` is passed:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m scripts.smoke_tavily_mcp
```

With explicit `--execute`, it performs one startup-style tool discovery and one
bounded search for official TI 2026 information, then prints only status,
source URLs, and elapsed time. It does not exercise a live language model. Do
not run it as part of deterministic tests.

## Product Runtime trace recording

Set `VNEXT_TEST_RECORDING_ENABLED=true` in the API environment to record
successful, failed, and cancelled product chat executions. It defaults to
`false`; when disabled, the existing failure-diagnostic recording remains
available. Enabling full test recording requires `DOTAMIND_REDIS_URL` at API
startup. `DOTAMIND_VNEXT_TRACE_TTL_SECONDS` controls retention and defaults to
72 hours.

Trace records are scoped to the browser and chat session. The expanded
**会话 Trace** panel in chat lists metadata for the 100 most recent records and
offers a manual refresh. A trace can also be downloaded from its completed or
failed assistant message while that message retains its trace metadata. A record
that expires between listing and download returns HTTP 410.

The downloaded ZIP contains `manifest.json` (recording mode, Runtime outcome,
IDs, and timestamps), `trace.json` (the Runtime trace and recorded tool
observations), `model-calls.jsonl` (application-level `ModelRequest` and
`ModelResponse` records when full test recording is enabled), and
`artifact-manifest.json`. It does not contain the complete temporary Artifact
store or raw provider HTTP traffic. Diagnostic-only records may omit full model
call bodies.

`RunTrace.status` describes the Runtime execution: `completed`, `failed`, or
`cancelled`. A completed Runtime trace stays `completed` if persisting its chat
turn later fails; the chat response reports `chat_store_error` separately.
Recording or trace download failures do not replace the original answer or
Runtime error.

Model-response parsing failures may add a versioned `failure_diagnostics` object
to the affected model call. It records the parsing stage, stream or complete
mode, provider tool names and their mapped agent names when known, the observed
finish reason and usage, and the JSON error location when parsing failed. Stream
diagnostics also record whether `[DONE]` arrived and how many argument fragments
were collected. Missing provider fields remain `null` or `{}`; they are not
inferred. A valid JSON value that is not an object retains `json_error: null`.

Full test recording may retain bounded tool-argument evidence. The defaults are
64 calls, 64 KiB per call, and 256 KiB cumulatively across one failure. These
limits are configurable through `DOTAMIND_DIAGNOSTIC_*`; oversized arguments
keep only UTF-8-safe prefix and suffix snippets of up to 4 KiB each, subject to
the cumulative argument-copy budget, with `arguments_truncated` and the original
UTF-8 byte count. These limits apply only to diagnostic copies, not actual tool
calls or Runtime correction history. The byte budget covers argument text and
snippets, not the complete trace file. These diagnostics
describe model-response parsing; they are not raw HTTP or SSE
traffic and never include response headers or complete provider response bodies.
The default diagnostic-only recording removes raw argument text and snippets
while keeping the parsing stage, locations, counts, truncation flags, and
provider-reported metadata.

Diagnostic objects use `schema_version: 1` and are an optional addition to the
existing four-file ZIP, which remains at `recording_version: 1`. Older traces
without these fields mean that the evidence was not collected at that time; they
do not establish that the failure did not occur. Diagnostic persistence is
best-effort and cannot replace or suppress the original Runtime error.

## Dynamic output budgets and response recovery

The authoritative contract is
[`agent/model_output_and_recovery.md`](agent/model_output_and_recovery.md).
Dynamic budget calculation, configuration, Runtime wiring, capacity checks, and
trace capture are implemented and covered by deterministic offline tests. Those
tests cover sufficient space, clipping, zero remaining space, recalculation after
input changes, the expected-output-based early threshold, all three ordinary
stages, and equality between the actual request cap, capacity record, trace, and
OpenAI-compatible `max_tokens`. Summary calls retain their separate budgets.

Adapter and Runtime response-level rejection recovery are implemented and
offline-tested for complete and streamed responses: all identities and argument
carriers are checked before JSON classification; malformed/non-object JSON and
tool-call `finish_reason=length` reject the complete batch before execution.
Original arguments are retained in effective conversation history, while trace
records contain bounded rejection metadata rather than the full batch. Runtime
pairs every rejected call with an explicitly non-executed result and permits at
most two corrective generations after consecutive rejections. Primary/degraded
answer `finish_reason=length` recovery is implemented and offline-tested: failed
attempts are replaced, truncated text is not delivered or persisted, and a
truncated degraded answer reaches deterministic fallback. Live Provider
compatibility has not been verified.

| Case | Required evidence |
| --- | --- |
| Two-call batch; second argument JSON is invalid | Entire batch is rejected; neither handler runs; paired results include the shared not-executed explanation |
| Tool-call response ends with `finish_reason=length` | Zero handlers run even if received argument fragments parse; the batch enters bounded correction |
| Rejected call history | Raw argument text and identity are retained; paired results encode, persist, and compact as one indivisible history group; rejected calls are not evidence |
| Consecutive response-level failures | At most two corrective generations; a normal complete response resets the consecutive counter |
| Cancellation and execution deadline | Corrections do not reset the deadline; cancellation and expiry stop further correction |
| Correction exhaustion | Completed checkpoints remain; only reliable current-request results can support a partial answer; without reliable results the answer explains the repeated rejected calls |
| Primary answer `finish_reason=length` | Attempt is marked failed with `answer_output_truncated`; degraded answer uses a new attempt identity; truncated text is not delivered or persisted |
| Degraded answer `finish_reason=length` | Attempt is marked failed with `answer_output_truncated`; deterministic fallback replaces it; truncated text is not delivered or persisted |
| Normal ToolRegistry schema errors and provider overflow | Existing per-call feedback and one-time overflow compaction remain; completed tools are not replayed |

Full test recording and diagnostic traces continue to use the existing four-file
ZIP and `recording_version: 1`. A generation-recovery record exposes:

- expected output cap, actual output cap, and whether/how input capacity clipped
  it;
- every actual model call and its bounded failure diagnosis;
- response-level whole-batch rejection reason, call IDs, confirmed zero-execution
  result, consecutive rejection count, correction attempt, and next action;
- execution end reason, task coverage, and answer delivery result as distinct
  facts.

The original failed call and raw argument string belong to effective Runtime
conversation history for model feedback. Trace entries remain bounded diagnostic
records and must never be used to reconstruct a call or returned history. Existing
diagnostic truncation/redaction and recording limits continue to apply.

Live Provider compatibility and historical response-shape compatibility are
later verification items. Offline implementation acceptance does not claim that
online providers have been checked.
