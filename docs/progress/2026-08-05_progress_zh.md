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
