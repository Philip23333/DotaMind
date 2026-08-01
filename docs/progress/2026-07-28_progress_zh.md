# DotaMind 进度快照（2026-07-28）

## 18:55 — V3.2-5 Redis Session Store 实现与待验证项

### 实现

- 新增 `RedisSessionStore`，与 `InMemorySessionStore` 共用 `SessionStore` 接口；
  `PlanService` 不按后端分支。
- Redis key 使用 session/request 命名空间 hash；compact Turn、RequestRecord 和公开响应
  使用严格 schema-v1 JSON envelope。request Hash field 用 request-key hash 定位，record
  内 payload hash 判断 query/game 是否冲突。
- 实现 Lua 原子 acquire/renew/release、fencing token、append、claim/replay/conflict、
  `complete_request_with_turn` 和 failed takeover；Session 与 request record 按 TTL/容量
  管理，in-progress record 不参与 GC。
- 增加 `memory|redis` backend 配置、Store factory、FastAPI lifespan、Redis startup PING、
  shutdown close，以及 HTTP 503 `session_store_error`；Redis 运行时错误不回退 memory。
- Docker Compose Redis 改为 AOF `appendfsync everysec`，并在 API/设计文档中说明 Redis
  Server 重启恢复仍依赖持久卷及部署策略。

### 测试与验证

- 新增 schema round-trip/损坏 schema、backend factory、503 映射，以及真实 Redis 跨 Store
  集成测试模块；集成测试通过 `DOTAMIND_TEST_REDIS_URL` 启用并使用随机 namespace，不执行
  `FLUSHDB`。
- 已验证：`uv run ruff check .` 通过；`uv run pytest -q` 为
  `445 passed, 3 skipped, 1 warning`；`uv lock --locked` 与 `git diff --check` 通过。
- 3 个 skipped 是真实 Redis 集成测试。尝试 `docker compose up -d redis` 时发现本机
  Docker daemon 未启动，故尚未执行真实 Redis 验收，不能将 V3.2-5 标记为完成。

### 明确边界

- API/worker 重建后恢复要求连接同一份 Redis 数据；Redis Server 重启的数据保留不由应用
  单独保证，取决于 AOF/RDB、fsync/save 策略和持久卷。
- 本阶段不增加业务工具、Graph 节点/回边、stateless 幂等、Redis Cluster/Redlock 或
  V3.2-6 的故障注入与未捕获 Attempt 封存。

## 19:03 — 本机 Redis 验收与 JSON 空数组修正

### 验收

- 本机 Docker 已启动项目 Redis 服务（`redis:7-alpine`，宿主机 `127.0.0.1:6379`），
  `redis-cli ping` 返回 `PONG`。
- 使用 `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15` 运行真实 Redis 跨 Store
  集成测试：`3 passed`，覆盖 fencing/Turn 顺序、completed replay/conflict 与重建恢复。
- 随后常规全量回归为 `445 passed, 3 skipped, 1 warning`；其中 3 个 skipped 仅因该命令未设置
  Redis 测试环境变量，真实 Redis 验收已在单独命令中完成。`ruff` 与 `git diff --check` 通过。

### 修正

- 真实 Redis 测试发现 Redis Lua `cjson` 会混淆空数组与空对象。append/complete 脚本改为在
  Python 已严格校验的 canonical JSON 中仅原子替换 `turn_index`，从而保留
  `resolved_entities`、`missing_fields` 的 `[]` schema 语义。

## 21:04 — V3.2-5 Redis 数据完整性修正

### 修正

- RequestRecord 的公开响应不再经 Lua `cjson` decode/encode；Python 严格读取并构造
  completed/failed canonical JSON，Lua 仅校验 lock/owner、原子分配 `turn_index` 并写入 JSON，
  因此重放保持 `missing_fields`、`tool_results`、`runtime.attempts` 等空数组语义。
- claim 先严格读取当前 RequestRecord 并处理 replay/conflict；只有新增 record 才执行容量淘汰，
  满容量时对已完成请求的同 key 重试不会误删自身后重复执行。
- begin、complete、fail 均严格反序列化 RequestRecord；未知 schema、缺失字段或额外字段在
  写入 Turn 前归约为 `data_invalid`。
- renewal 间隔改为 `min(lock_lease_seconds, session_ttl_seconds) / 3`，短 Session TTL 下的活跃
  transaction 会在数据过期前刷新 TTL，保留历史和单调 turn index。

### 验证

- 真实 Redis 集成测试扩展为 9 项，覆盖公开响应空数组重放、满容量 replay、短 TTL 活跃事务和
  begin/complete/fail 的损坏 RequestRecord schema 拒绝。
- 已验证：设置 `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15` 的完整 pytest 为
  `455 passed, 1 warning`；未设置该变量的常规 pytest 为 `446 passed, 9 skipped, 1 warning`。
  `ruff check .`、`uv lock --locked` 与 `git diff --check` 通过。
