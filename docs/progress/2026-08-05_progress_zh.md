# DotaMind 进度快照 — 2026-08-05

## 16:54 — V3.3-2 A1 设计合同冻结

### 已完成

- 新增 `docs/design/versions/DotaMind_V3.3-2_design.md`，冻结多聊天 Run 的 PostgreSQL/Redis 职责、`RunContext.run_id` 复用、Run 状态机、幂等与所有权、原子完成、事件 allowlist 和前端 Run Store 边界。
- 明确 `DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` 是每个 API worker 的并行上限；本阶段无独立队列，因此不承诺部署级全局上限。
- 明确客户端断开只终止观察订阅，服务重启/stale recovery 标记 `interrupted`，不引入 LangGraph checkpoint 或自动续跑。

### 已验证

- A1 仅新增设计合同和本进度记录；未修改数据库模型、API、运行图或前端运行链路。

### 边界

- A2-A5、B-E 尚未实现；设计文档状态保持为“仅 A1 完成”。

## 17:02 — V3.3-2 A2 chat_runs 模型与迁移

### 已完成

- `ChatRunRow` 已加入 PostgreSQL ORM：Run ID、session/request 幂等、状态、fencing、worker、事件序号、heartbeat、取消/终态时间和最终 Turn 关联均有明确字段。
- 新增 Alembic `20260805_03`，增加状态 CHECK、session/request 唯一约束、活动 Run partial unique index、result Turn 唯一索引和查询索引。
- `chat_sessions` 增加 `runs` 关系；Run 删除随 session 级联，`result_turn_id` 在 Turn 删除时置空。

### 已验证

- A2 代码检查与 `git diff --check` 通过；尚未实现 Repository 或运行调度。

### 边界

- A3-A5、B-E 尚未实现；当前 `/plan`、`/plan/stream` 和前端行为保持不变。

## 17:18 — V3.3-2 A3 Run Repository

### 已完成

- 新增 `ChatRunRepository` 合同、稳定错误码、状态 DTO 和 `PostgresChatRunRepository`。
- 实现 Run 创建/幂等重放、browser ownership、active Run 冲突、queued→running、heartbeat、取消请求、终态收口和 stale Run 标记。
- 新增 PostgreSQL 集成测试，覆盖跨浏览器隔离、同 session 活动唯一、幂等冲突、取消状态机和 stale 收口。

### 已验证

- `uv run ruff check app`：通过。
- `tests/test_postgres_chat_run_repository.py` 已加入真实 PostgreSQL 测试；未配置 `DOTAMIND_TEST_DATABASE_URL` 时按既有约定跳过。

### 边界

- A4 的 `complete_with_turn()` 原子提交尚未实现；A5 将补齐完整 Repository 回归。
- B-E 尚未实现；当前 API 和前端仍使用原有运行链路。

## 17:32 — V3.3-2 A4 原子完成

### 已完成

- `PostgresChatRunRepository.complete_with_turn()` 在同一 PostgreSQL 事务中锁定 Run 和 session，校验 worker/fencing，写入唯一 Turn，更新标题/序号，并将 Run 收口为 `completed`。
- `cancel_requested`、终态 Run 和过期 fencing 均拒绝完成；同一 completed Run 重复完成只返回已有结果，不重复写 Turn。
- 扩展真实 PostgreSQL 集成测试，覆盖原子提交、重复完成、Turn 唯一性和 fencing 拒绝。

### 已验证

- `uv run ruff check app tests/test_postgres_chat_run_repository.py`：通过。
- `uv run pytest -q tests/test_postgres_chat_run_repository.py`：未配置 `DOTAMIND_TEST_DATABASE_URL`，2 个测试按既有约定跳过。

### 边界

- A5 将补齐完整 Repository 回归和阶段 A 收口；B-E 尚未实现。

## 17:46 — V3.3-2 A5 阶段 A 回归收口

### 已完成

- 新增纯合同测试，固定 active/terminal 状态集合互斥且闭合，防止后续 API 或 Manager 引入未知状态。
- 阶段 A 设计文档状态更新为 A1-A5 已完成；B-E 继续明确为未实现。

### 已验证

- `uv run ruff check app tests`：通过。
- `uv run pytest -q tests/test_chat_run_contract.py tests/test_postgres_chat_repository.py tests/test_postgres_chat_run_repository.py`：`1 passed, 3 skipped`（本机未设置 `DOTAMIND_TEST_DATABASE_URL`）。
- `uv run alembic upgrade head`：通过；`uv run alembic check`：`No new upgrade operations detected`。
- `git diff --check`：通过。

### 阶段 A 结论

- PostgreSQL `chat_runs` schema、状态 DTO、生命周期 Repository 和 Run/Session/Turn 原子完成合同已落地。
- 未修改现有 `/plan`、`/plan/stream`、后台任务或前端运行路径；下一步进入 B1 预分配 Run ID。

## 18:02 — V3.3-2 B1 预分配 Run ID

### 已完成

- `AgentRunState` 新增内部 `internal_run_id`；`run_init_node` 优先复用预分配 ID，stateless 请求仍在未提供时生成 UUID v4。
- 新增 B1 合同测试，确认 `RunContext.run_id` 与预分配 ID 完全一致。

### 已验证

- `uv run ruff check app tests`：通过。
- `uv run pytest -q tests/test_run_init_preallocation.py`：通过。

### 边界

- B2-B8 尚未实现；`internal_run_id` 尚未接入 ChatRunExecutor 或公开 API。

## 18:21 — V3.3-2 B2 Redis Run Event Bus

### 已完成

- 新增 `RunEventBus` 合同和 `RedisRunEventBus`，使用每 Run Stream、Lua 原子 sequence、TTL、按 sequence 重放和 Redis 取消通知。
- 新增 `status` 运行事件模型；事件存储只接受现有 allowlist event，不写 query、history、prompt、工具参数或原始异常。
- Run Stream/sequence key 使用 Run ID hash；Event Bus 支持注入 Redis client，便于真实集成测试和独立生命周期管理。

### 已验证

- `uv run ruff check app tests`：通过。
- Redis 集成测试已加入；未设置 `DOTAMIND_TEST_REDIS_URL` 时按既有约定跳过。

### 边界

- B3 Event Pump、B4 Manager、B5 Graph 执行和 B6-B8 故障收口尚未实现；当前 Event Bus 尚未被 API 或后台任务调用。

## 18:39 — V3.3-2 B3 Run Event Pump

### 已完成

- 新增 `RunEventPump` 和 `bind_run_event_pump()`：Graph 继续通过同步 `publish_stream_event()` 发事件，Run-scoped asyncio Queue 异步写入 Event Bus。
- Event Pump 支持启动、flush、sequence cursor、queue 上限和稳定的 Event Bus failure 传播；退出前必须完成队列 flush。
- 新增纯单测，验证事件顺序、sequence 和 Redis/Bus 故障不会静默吞掉。

### 已验证

- `uv run ruff check app tests`：通过。
- `uv run pytest -q tests/test_run_event_pump.py`：通过。

### 边界

- B4 Manager、B5 Graph 执行接线和 B6-B8 故障收口尚未实现；Event Pump 目前仍由测试独立驱动。

## 12:06 — V3.3-1 PostgreSQL 聊天持久化与匿名浏览器多聊天管理

### 已完成

- 新增异步 SQLAlchemy/asyncpg 数据库资源、Alembic 配置和迁移；创建
  `chat_sessions` 与 `chat_turns`，PostgreSQL 保存完整用户查询、公开响应和 compact `Turn`。
- 新增 `PostgresChatRepository`：会话创建、列表、transcript、重命名、删除、浏览器归属校验、
  fencing claim、幂等重放/冲突和会话内单调 turn 序号均由 PostgreSQL 事务保证。
- 新持久化请求链路由 Redis `SessionStore` 提供 lease/fencing 协调，PostgreSQL 承担聊天历史
  权威存储；新路径不再将对话 turns 或公开响应写入 Redis。
- `/api/v1/chat/sessions` 提供创建、列表、读取、重命名和删除接口；带 `session_id` 的
  `/plan` 与 `/plan/stream` 要求 `X-DotaMind-Browser-Id`、`session_id`、`request_id`。
- `apps/chat` 保存浏览器 UUID v4 和当前 session 到 localStorage，增加多会话侧栏、创建/切换/
  重命名/删除，并从 PostgreSQL transcript 恢复消息；已有真实 NDJSON 流式运行卡保持不变。
- 新增 V3.3-1 设计文档，并同步 API、架构和聊天应用说明。

### 已验证

- `cd apps/api && uv run alembic upgrade head`：迁移 `20260805_01` 成功。
- PostgreSQL 集成测试（`DOTAMIND_TEST_DATABASE_URL`）：`1 passed`，覆盖跨浏览器隔离、
  transcript、自动标题、重命名、幂等 replay/conflict、compact Turn 和删除。
- `uv run ruff check app tests`：通过。
- `uv run pytest -q`：`465 passed, 15 skipped`；另有既有 FastAPI TestClient 弃用警告。
- `apps/chat`：`npm run lint` 与 `npm run build` 均通过。
- 运行中的 FastAPI 实例完成真实 session CRUD 冒烟：创建、列表隔离、重命名、跨浏览器 404、
  删除均通过。

### 边界

- 当前匿名身份只在同一浏览器 localStorage 范围内有效；未实现登录、跨设备同步、分享、搜索、
  附件、消息编辑/分支、断线重连、心跳或 LangGraph checkpoint。
- Redis 仍保存 lease/fencing 所需的协调元数据；PostgreSQL 是新聊天 transcript 与记忆的权威
  来源。旧 SessionStore 接口和无 repository 的测试路径保留以支持既有单元测试。
- 本次未提交；工作树中原有的 `.env.example` Redis backend 改动保持不变。

## 13:04 — P1 fencing/删除修复与 P2 前端体验修复

### 已完成

- fencing token 改为 PostgreSQL 行锁事务内严格递增分配；Redis/内存协调器只负责短期锁，
  Redis 会话键清空、自然过期或 API 协调器重启后，下一次 token 仍严格大于 PostgreSQL 已保存值。
- `commit_turn` 继续强制校验 `active_fencing_token`，旧 owner 使用过期 token 会被拒绝；新增真实
  PostgreSQL/Redis 集成测试覆盖 Redis 状态清理、自然过期和锁保护。
- 删除聊天改为先取得 SessionStore 协调锁，再删除 PostgreSQL session/turns；锁内只清理 Redis
  data keys，正常退出释放 lock，不再直接删除其他 owner 的活动锁。锁忙返回 `409 chat_busy`，
  重复删除保持稳定 `404`，Redis 清理失败只记录日志，不覆盖已完成的 PostgreSQL 删除。
- 流式最终 `result` 增加可选 session summary；前端首轮完成后无需重新拉取 turns 即同步自动标题，
  并按 `updated_at` 重新排序，手动标题仍受保护。
- 移动端改为抽屉式侧栏，新增打开/关闭按钮；聊天操作改为常驻“更多”菜单，支持触屏、键盘、
  Escape、焦点返回、明确 aria 名称和删除确认，不再依赖 hover。
- 优化 390px 窄屏的消息/输入框宽度、横向溢出和安全区域留白；桌面布局保持不变。

### 已验证

- `uv run pytest -q`：`465 passed, 17 skipped`；既有 FastAPI TestClient 弃用警告仍存在。
- 使用真实 PostgreSQL + Redis：`tests/test_postgres_chat_repository.py tests/test_persistent_fencing.py`：
  `3 passed`。
- `uv run ruff check app tests`：通过。
- `apps/chat`：`npm run lint` 与 `npm run build` 均通过。
- 真实流式 API：最终事件返回更新后的 session summary，首轮标题即时持久化。
- 浏览器响应式验证：`390×844`、`393×852`、`768×1024`、`1280×800` 均无横向溢出；移动端
  抽屉打开/关闭、更多菜单、Escape 关闭和焦点返回均通过。

### 边界

- Redis 重启本身未在测试中停止容器，而是通过真实 Redis 键清理与自然过期模拟状态丢失；
  PostgreSQL 仍是 fencing 和聊天记录的权威来源。
- 标题同步通过最终流事件携带摘要完成；如果客户端更新失败，不影响已展示的回答内容。

## 16:12 — 中断后修复链路复验

### 已验证

- `uv run alembic upgrade head` 与 `uv run alembic check`：通过。
- 使用真实 PostgreSQL + Redis：`tests/test_persistent_fencing.py tests/test_postgres_chat_repository.py`：`3 passed`。
- `uv run ruff check app tests`：通过。
- `apps/chat`：`npm run lint` 与 `npm run build`：通过。

## 18:58 — V3.3-2 B4 BackgroundRunManager

### 已完成

- 新增 `BackgroundRunManager`，以 `DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` 对单个 API worker 的后台 Run 任务施加并发上限；不同 Run 使用独立 asyncio task，不共享执行状态。
- 支持重复 Run 拒绝、worker 关闭后拒绝新提交、定向取消和统一 shutdown；shutdown 只通过回调通知持久化层收口，不直接改变 PostgreSQL 状态。
- 任务异常被记录到 worker-local failure 账本，避免后台 task 异常丢失；数据库权威状态与跨 worker 协调留给后续 B5-B7。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_background_run_manager.py`：`3 passed`，覆盖 per-worker 并发槽位、定向取消、shutdown 和重复提交。
- `git diff --check`：通过。

### 边界

- B4 仅建立 worker-local 生命周期管理，尚未接入 Graph 执行、Run Repository、Redis cancel listener 或 HTTP API；这些属于 B5-B8。

## 19:22 — V3.3-2 B5 后台 Graph 执行器

### 已完成

- 新增 `ChatRunExecutor`，按 `SessionStore.transaction → PostgreSQL fencing → mark_running → history → AgentGraphRunner → complete_with_turn` 的顺序执行一个已创建 Run。
- `ChatRunExecutionRequest.run_id` 注入 `AgentRunState.internal_run_id`，由 `run_init_node` 生成同一个 `RunContext.run_id`；Graph 事件在执行前绑定 Run-scoped Event Pump。
- 最终 Turn 先在 PostgreSQL 原子提交，再发布 Redis `result`/`completed` 事件；Redis/Event Bus 故障不会回滚已提交 Turn。Graph 异常会写稳定 `execution_error`，取消暂按 `interrupted` 收口，后续 B6 再细化用户取消语义。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_executor.py`：`2 passed`，覆盖预分配 Run ID、fencing/history 顺序、原子完成先于终态事件和 Graph 失败收口。
- `git diff --check`：通过。

### 边界

- B5 提供后台 Graph 执行闭环，但尚未接入 Manager 的 cancel listener/heartbeat/reconciliation，也尚未开放 C 阶段 HTTP API。

## 19:47 — V3.3-2 B6 取消和异常内部语义

### 已完成

- `BackgroundRunManager` 增加可选 Redis cancel listener：只处理目标为当前 worker 或无目标的通知，跨 worker 通过 Pub/Sub 加速本地 task.cancel()，不把 Redis 当作状态权威。
- `ChatRunExecutor` 捕获任务取消后先尝试 `mark_cancelled()`；只有 PostgreSQL 已记录 `cancel_requested` 时进入 `cancelled`，否则按 worker 中断进入 `interrupted`。
- Graph 未捕获异常进入 `failed` 并只写稳定 `execution_error`；后台 listener 异常被消费并记录，不产生内存 fallback。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_background_run_manager.py tests/test_chat_run_executor.py`：`7 passed`，覆盖目标 worker 过滤、定向取消、取消/中断判定和失败收口。

### 边界

- B6 尚未加入 heartbeat 周期检查、stale sweeper、重启恢复和 C 阶段公开取消 API；这些属于 B7/C 阶段。

## 20:15 — V3.3-2 B7 heartbeat 与 stale recovery

### 已完成

- 新增 `RunHeartbeat`：按配置周期更新 PostgreSQL `heartbeat_at`，发现权威状态为 `cancel_requested` 时只取消本地执行 task。
- 新增 `RunStaleSweeper`：按 `DOTAMIND_RUN_STALE_SECONDS` 计算 cutoff，调用 Repository 的条件 stale 收口，将无心跳的 `queued/running/cancel_requested` 标记为 `interrupted`。
- `ChatRunExecutor` 可为每个 Run 启动/停止 heartbeat；`Settings` 增加 per-worker 并发、heartbeat、stale 和 sweeper 周期配置，均使用 `DOTAMIND_` 前缀。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_run_recovery.py tests/test_chat_run_executor.py tests/test_config.py`：`21 passed`。
- `git diff --check`：通过。

### 边界

- B7 提供 heartbeat/sweeper 内部组件，但尚未在 FastAPI lifespan 启动 supervisor，也尚未实现 C 阶段 Run API；worker 重启后的调度接线留在 C/E 集成收口。

## 20:42 — V3.3-2 B8 阶段 B 回归收口

### 已完成

- 增加 Redis Event Bus fail-fast 回归：Redis 不可用直接暴露 `unavailable`，不降级到内存事件总线。
- 增加观察者消失回归：无 HTTP subscriber 时，后台 Run 的 Event Pump 仍能写入并 flush 完成。
- 汇总预分配 Run ID、事件顺序/重放、并发上限、取消/异常、heartbeat/stale 组件的 focused tests，完成阶段 B 内部闭环验证。

### 已验证

- `uv run ruff check app tests`：通过。
- B 阶段 focused suite：`14 passed, 1 skipped`；Redis integration 在未设置 `DOTAMIND_TEST_REDIS_URL` 时按既有约定跳过。
- `git diff --check`：通过。

### 阶段 B 结论

- 后台 Run 能在脱离 HTTP 观察者后继续执行；PostgreSQL 负责状态/Turn 权威，Redis 负责可重放事件与取消通知；B 阶段不改变现有 `/plan` 和前端正式切换边界。

## 21:08 — V3.3-2 C1 Chat Run API 合同

### 已完成

- 新增 `chat_run_schemas.py`，冻结创建、查询、active-run、事件、取消和稳定错误响应模型；公开响应不暴露 payload hash、worker、fencing 或内部 Agent state。
- 新增 `chat_run_routes.py` 路由命名空间与公共 helper：统一解析 `X-DotaMind-Browser-Id`、Run DTO 映射和错误码原因；具体 endpoint 在 C2-C5 逐步接入。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_api_contract.py`：`2 passed`。
- `git diff --check`：通过。

### 边界

- C1 只冻结 API schema/ownership/error contract，尚未挂载 FastAPI endpoint、Manager 调度或 Redis 事件订阅。

## 21:47 — V3.3-2 C2 创建 Chat Run

### 已完成

- 新增 `ChatRunRuntime`：预分配 UUID v4，按 payload hash 调用 `create_or_get_run()`，新 Run 持久化为 `queued` 后交给 `BackgroundRunManager`。
- 创建路由挂载为 `POST /api/v1/chat/sessions/{session_id}/runs`，成功返回 `202`；幂等重放返回 `200`，同 session 活动冲突/幂等冲突使用稳定 `409`。
- FastAPI lifespan 在配置 Redis 时构造 Run Repository、Redis Event Bus、Manager、Executor 和 stale sweeper；未配置 Redis 时 Run API 返回 `503 unavailable`，不降级内存事件总线。
- 调度失败会把刚创建的 queued Run 收口为 `failed/dispatch_failed`，不留下永久 queued。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_runtime.py tests/test_plan_route.py`：`13 passed`（含既有 TestClient 弃用警告）。
- `git diff --check`：通过。

### 边界

- C2 只完成创建和调度；Run 查询、active-run、事件重放/订阅和取消 API 属于 C3-C5，旧 stateful `/plan` 暂不删除。

## 22:28 — V3.3-2 C3 Run 查询与 active-run

### 已完成

- 新增 `GET /api/v1/chat/runs/{run_id}` 与 `GET /api/v1/chat/sessions/{session_id}/active-run`，统一按 browser ownership 查询；不属于当前浏览器时返回 `404 not_found`。
- Chat session list/transcript 的 PostgreSQL 查询增加活动 Run left join，返回 `run_id/status/last_event_sequence/error_code`，保持单次查询避免 N+1。
- 公开 Run/session DTO 继续隐藏 payload hash、worker、fencing 和内部 Agent state。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_query_routes.py tests/test_chat_run_runtime.py tests/test_postgres_chat_repository.py`：`4 passed, 1 skipped`。
- `git diff --check`：通过。

### 边界

- C3 尚未实现 Redis Stream 事件订阅、终态合成或取消 API；旧 stateful `/plan` 仍保留。

## 23:08 — V3.3-2 C4 Run 事件订阅

### 已完成

- 新增 `GET /api/v1/chat/runs/{run_id}/events?after=N`：先按 ownership 校验，再从 Redis Stream 重放 `sequence > after`，排序去重后使用 `XREAD` 等待后续事件。
- 订阅每次等待超时发送不写 Redis 的 heartbeat，并再次读取 PostgreSQL Run 状态；已终态但 Stream 缺事件时合成 `transcript_recovery=true` 的终态 status 事件。
- Redis 事件故障以稳定 stream error 结束观察；HTTP disconnect 只退出生成器，不调用 Manager.cancel。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_event_routes.py`：`2 passed`，覆盖顺序重放/终态关闭与 Redis 缺事件恢复。
- `git diff --check`：通过。

### 边界

- C4 尚未实现公开取消 API；事件订阅不改变后台任务生命周期，C5 负责取消状态转换和 Redis 通知。

## 23:52 — V3.3-2 C5 取消 API

### 已完成

- 新增 `POST /api/v1/chat/runs/{run_id}/cancel`；先调用 PostgreSQL `request_cancel()`，再尝试唤醒本 worker Manager 并发布 Redis cancel notification。
- `cancel_requested` 重复请求保持 `202` 幂等；终态 Run 返回 `409 run_terminal`；Redis 通知失败不回滚已持久化的取消请求，heartbeat 负责最终发现。
- 取消 API 与创建/查询/事件路由共享 browser UUID v4 ownership 和稳定错误映射。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_chat_run_cancel_routes.py tests/test_chat_run_runtime.py`：`5 passed`。
- `git diff --check`：通过。

### 边界

- C5 不直接伪造 `cancelled` 终态；由后台 Executor 根据 PostgreSQL 状态收口。C6/C7 继续处理旧 stateful 路径迁移准备和 API 全量回归。

## 23:58 — V3.3-2 C6 stateful 路径迁移准备

### 已完成

- 新增 `apps/chat/src/lib/chat-run-api.ts`，提供 create/get/active/events/cancel 客户端和 NDJSON 事件解析，支持 AbortSignal 观察订阅。
- 扩展前端共享类型：Run 状态、active Run、status/recovery/heartbeat 事件；session transcript/list 可承载 active Run 元数据。
- 后端 C1-C5 API 已挂载但旧 stateful `/plan`、`/plan/stream` 和 PlanService PostgreSQL 分支保持不变，为 D 阶段原子前端切换保留可回滚边界。

### 已验证

- `apps/chat`: `npm run lint` 通过（无 warning），`npm run build` 通过。
- `uv run ruff check app tests`：通过。
- `git diff --check`：通过。

### 边界

- C6 只增加客户端和类型准备，不改变现有消息发送路径；旧 stateful 路径必须等 D 正式切换后再删除。

## 23:59 — V3.3-2 C7 阶段 C API 回归收口

### 已完成

- 补齐创建、查询、active-run、事件重放/终态合成、取消、browser ownership、幂等和终态错误的 API focused tests。
- 增加终态取消 `409 run_terminal` 回归；统一错误原因补齐 `not_found` 与非法 `after`。
- 阶段 C 保持旧 `/plan`、`/plan/stream` stateful 路径和前端旧发送链路不变，满足 D 阶段原子切换前的可运行边界。

### 已验证

- API focused suite：`22 passed`（含既有 TestClient 弃用警告）。
- 全量 `uv run pytest -q`：`491 passed, 20 skipped, 1 warning`。
- `uv run ruff check app tests`：通过。
- `apps/chat`：`npm run lint`、`npm run build` 均通过。
- `git diff --check`：通过。

### 阶段 C 结论

- 后端已能独立完成 Run 创建、状态查询、事件观察和取消请求；观察连接不拥有任务生命周期；旧路径尚未删除，下一阶段切入前端 Run Store。

## 23:59 — V3.3-2 D1 浏览器级 Run Store

### 已完成

- 新增 `chat-run-store.ts` reducer：以 `run_id` 为 Run 身份、以 `activeRunIdBySession` 快速索引 session active Run，处理 phase/tool/delta/result/status/heartbeat/recovery 事件。
- 每次事件都校验 Run ID、session ID 和严格递增 sequence；迟到、重复、跨 session 事件直接丢弃。
- 新增 `ChatRunProvider`、`useChatRun`、`useSessionLoader` 并接入根布局；session loader 会把 transcript 返回的 active Run 注册到全局 Store。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过。
- `git diff --check`：通过。

### 边界

- D1 只建立状态层和恢复入口，未改变消息发送、订阅、切换竞争、停止按钮或旧 stateful API；这些属于 D2-D7。

## 23:59 — V3.3-2 D2 发送流程切换到 Chat Run API

### 已完成

- `ChatSessionRuntime` 发送先调用 `createChatRun()`，成功后才创建 runtime pending 状态，再通过 `subscribeChatRun()` 消费 Run 事件生成回答。
- phase/tool/delta/result/status/error 事件继续映射到现有 assistant-ui runtime；Run 创建失败不会遗留假的 runtime pending。
- 旧 stateful `/plan/stream` 不再是正式聊天发送入口，但仍保留用于 D 阶段完成前的调试/兼容边界。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过且无 warning。
- `git diff --check`：通过。

### 边界

- D2 尚未实现 pending Run 启动恢复、断线 cursor 续订、切换竞争保护、Stop 调用 cancel API 和删除旧 stateful 代码；这些属于 D3-D7。

## 23:59 — V3.3-2 D3 pending Run 恢复

### 已完成

- 激活 session 时读取 `active_run` 并补取完整 Run 元数据，构造 `${runId}:user` / `${runId}:assistant` 稳定 pending 消息 ID。
- 恢复订阅始终从 `after=0` 重放事件，Reducer 重建 phase/tool/delta/status/cursor；恢复观察器关闭时只 abort 订阅，不触发取消。
- 恢复运行信息写入全局 Run Store 和现有 RuntimeInfoCard，刷新页面后仍能看到正在执行的 Run 状态。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过且无 warning。
- `git diff --check`：通过。

### 边界

- D3 尚未处理同一时间多 session 切换的选择序列竞争、Stop/cancel、未读计数和旧 stateful 路径删除。

## 23:59 — V3.3-2 D4 切换竞争保护

### 已完成

- `activateSession()` 增加 `detailsAbortController`、`selectionSequence` 和 `requestedSessionId`；新选择会 abort 旧详情/Run 元数据请求。
- 所有详情和 active Run 响应在写入 UI 前校验 sequence、requested session 和 AbortSignal，迟到响应不会覆盖当前聊天。
- 切换仍保持 sidebar 挂载和右侧局部 loading overlay，后端 Run 不因切换而取消。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过且无 warning。
- `git diff --check`：通过。

### 边界

- D4 保护详情加载竞争；详细事件订阅的统一 abort、Stop/cancel、未读计数和旧路径删除继续由 D5-D7 完成。

## 23:59 — V3.3-2 D5 Stop 与取消

### 已完成

- assistant-ui Stop 触发 AbortError 后，如果已有 `activeRunId`，前端调用 `cancelChatRun()`；后端先写 PostgreSQL `cancel_requested`，再唤醒 worker/发布通知。
- 本地 UI 立即收口为 cancelled 文案，但 Run Store 仍注册后端返回状态；取消 API 失败不伪造持久化终态，后续恢复查询负责对账。
- 恢复订阅/切换详情 abort 路径未调用 cancel API，保持“断开观察不等于取消执行”。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过且无 warning。
- `git diff --check`：通过。

### 边界

- D5 尚未实现 session 级未读计数、后台订阅统一 manager、旧 stateful 路径删除和最终浏览器验收。

## 23:59 — V3.3-2 D6 未读计数与轮询

### 已完成

- Run Store 增加 `unreadRunCountBySession`、mark-read/mark-unread；终态事件在非当前 session 形成未读计数，进入 session 时清零。
- ChatSidebar 显示每个 session 的未读 Run badge；Assistant 每 5 秒轮询 session list，检测后台 Run 从 active 消失并标记未读。
- 当前 session 的事件流仍直接驱动 RuntimeInfo/Store，轮询只作为跨 session 状态发现，不取代 Redis 事件游标。

### 已验证

- `apps/chat`: `npm run lint`、`npm run build` 均通过；lint 无 warning。
- `git diff --check`：通过。

### 边界

- D6 尚未删除旧 stateful `/plan` 路径，也未做最终浏览器多窗口/断线矩阵验收；D7-D8/E 继续收口。

## 16:39 — 避免会话切换空状态闪现

- 右侧聊天 runtime 重新挂载后先渲染一次空消息状态，导致“新聊天”界面闪现；现由 `ChatSessionRuntime` 在挂载完成后通知父组件，再关闭右侧 loading 遮罩。
- 切换期间遮罩会覆盖 runtime 的初始化帧，避免空 Welcome 状态被用户看到；左侧侧栏继续保持挂载。
- `apps/chat`：`npm run lint` 与 `npm run build`：通过。

## 16:35 — 会话切换局部刷新

- 切换会话不再触发整个聊天页面的全屏 loading；左侧 `ChatSidebar` 保持挂载，仅右侧 transcript/runtime 区域显示加载遮罩并在数据完成后重新挂载。
- 首次页面初始化仍使用全屏 loading；切换期间暂时禁用侧栏操作，避免加载中的重复切换造成状态竞争。
- `apps/chat`：`npm run lint` 与 `npm run build`：通过。

## 16:29 — 置顶会话视觉标识

- 已置顶聊天在左侧标题前显示 Pin 图标，未置顶聊天不显示；标题截断、操作菜单和键盘焦点行为保持不变。
- `apps/chat`：`npm run lint` 与 `npm run build`：通过。
- `git diff --check`：通过。
- 全量 `uv run pytest -q`：`478 passed, 4 failed, 1 warning`。4 个失败均集中在未配置 LLM provider 时要求 `natural_language_answer` 成功的既有测试（`test_agent_plan_debug.py`、`test_agentic_graph.py`、`test_plan_service.py`），未涉及本轮 PostgreSQL/Redis fencing、删除锁保护或前端修改；不能将全量回归记为通过。

### 结论

- 本轮 P1 fencing token、删除锁保护、P2 标题同步、移动端抽屉和会话操作菜单的代码已在工作树中，专项回归通过。
- 全量测试仍需在配置可用 LLM provider 或为既有自然语言测试注入 fake provider 后重新收敛；该项不属于本轮持久化修复的代码变更。

## 16:25 — 聊天操作菜单与置顶

### 已完成

- “更多”菜单增加 document 级 `pointerdown` 外部点击监听；点击菜单、菜单按钮或菜单项之外的区域会立即关闭弹出菜单，Escape 和焦点返回行为保持不变。
- `chat_sessions` 新增持久化 `is_pinned` 字段和索引，新增 Alembic `20260805_02` 迁移；置顶状态不会改变聊天活动 `updated_at`。
- `PATCH /api/v1/chat/sessions/{session_id}` 支持 `{ "is_pinned": true|false }`，列表和流式 session summary 返回置顶状态；置顶会话优先显示，其他会话按最近更新时间排序。
- 前端“更多”菜单新增“置顶聊天/取消置顶”，刷新页面后状态仍然保留。

### 已验证

- `uv run alembic upgrade head`、`uv run alembic check`：通过。
- PostgreSQL + Redis 专项测试：`3 passed`。
- `uv run ruff check app tests`：通过。
- `apps/chat`：`npm run lint` 与 `npm run build`：通过。

## 23:59 — V3.3-2 D7 删除旧 stateful `/plan` 路径

### 已完成

- `PlanRequest` 现在只允许 `query` 与 `game`，`session_id`、`request_id` 等有状态字段由公开 `/plan`、`/plan/stream` 请求直接拒绝。
- `/plan` 与 `/plan/stream` 只调用无状态 `PlanService.run(query, game)`；移除路由层 browser/session/idempotency 错误映射和旧 stateful 调用参数。
- 删除 `PlanService` 旧 PostgreSQL chat branch；生产多轮运行统一由 `ChatRunExecutor` 通过 Chat Run API 执行，SessionStore 独立挂载给聊天 CRUD 删除协调使用。
- 更新 plan route 回归，固定 stateless-only 输入边界和 NDJSON 调试流行为。

### 已验证

- `uv run ruff check app tests`：通过。
- `uv run pytest -q tests/test_plan_route.py tests/test_plan_service.py`：`18 passed`。
- 全量 `uv run pytest -q`：`488 passed, 20 skipped, 1 warning`（既有 FastAPI TestClient 弃用警告）。
- `apps/chat`：`npm run lint`、`npm run build` 均通过。
- `git diff --check`：通过。

### 边界

- D7 后仍存在的 repository-less helper 已在 D8 移除；正式聊天发送、恢复、取消与持久化均不经过 `/plan`。
- D8 将进行全量后端/前端回归与最终多 Run 合同验收；E 尚未实现。

## 23:59 — V3.3-2 D8 前端测试与阶段 D 收口

### 已完成

- 从 `apps/chat/src/lib/dotamind-api.ts` 删除旧 `streamDotaMind()` 及其 stateful `/plan/stream` 请求体；聊天应用运行调用面现在只保留 Chat Run API。
- `PlanService` 改为只暴露 `run(query, game)`，移除请求内 session/idempotency、repository-less stateful 分支；ChatRunExecutor 继续直接承载 history/session/request/run_id 执行合同。
- 为前端增加最小 Vitest 配置和 `chat-run-store` 纯 reducer 测试，覆盖 sequence 去重、run/session 隔离、并行 Run、终态未读和 session 清理。
- 清理不再适用的旧 PlanService stateful 测试，保留独立的 idempotency hash、状态机、执行边界和隐私回归。

### 已验证

- `uv run alembic upgrade head`：通过。
- `uv run alembic check`：`No new upgrade operations detected`。
- `uv run ruff check app tests`：通过。
- 全量 `uv run pytest -q`：`469 passed, 20 skipped, 1 warning`（既有 FastAPI TestClient 弃用警告）。
- `apps/chat`: `npm run test`：`1 file, 3 tests passed`；`npm run lint`、`npm run build` 均通过。
- `git diff --check`：通过。

### 阶段 D 结论

- 前端多聊天 Run Store、切换/恢复/取消/未读状态与 stateless debug 边界已完成；旧 stateful 聊天执行路径已删除。
- E 阶段仍需完成真实重启/Redis 过期恢复、浏览器矩阵和最终文档验收。

## 23:59 — V3.3-2 E2 Chat Run 可观测性

### 已完成

- 新增低基数 Chat Run Prometheus 指标：终态计数/时延、事件发布/重放、事件总线错误、当前订阅数、取消结果和 stale interrupted 计数。
- 在 `ChatRunExecutor`、`RunEventPump`、Chat Run 事件订阅、取消 Runtime 和 stale sweeper 接入指标；不使用 `run_id`、`session_id`、query 或用户文本作为 label。
- 增加 observability 合同测试，固定指标 label 集合，避免后续把高基数身份泄漏进监控。

### 已验证

- `uv run ruff check app tests`：通过。
- `tests/test_observability.py tests/test_run_recovery.py tests/test_run_event_pump.py tests/test_chat_run_executor.py`：`10 passed`。

### 边界

- E1 恢复组件和 worker lifespan 已具备；真实 PostgreSQL/Redis 矩阵、浏览器验收和最终文档收口属于 E3-E6。
