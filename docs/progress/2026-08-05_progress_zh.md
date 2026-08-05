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
