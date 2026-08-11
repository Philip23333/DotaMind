# DotaMind V3.2-5 Redis Session Store 设计

> 状态：已完成（2026-08-01）。本文把 V3.2-4 的 stateful request idempotency 迁移到 Redis，
> 以支持多 worker、API/worker 重建后的会话恢复；Redis Server 自身的持久化能力取决于
> 部署时启用的 AOF/RDB 与持久卷。
>
> 当前覆盖说明（2026-08-11）：本文的 compact Turn/RequestRecord 描述是 V3.2
> stateful `/plan` 历史合同。正式 Chat Run 以 PostgreSQL 为 Run/Turn 权威源，Redis
> 保留 lease、事件、取消通知和可重建 `RecentDialogueWindow`；当前多轮链路不从 Redis
> compact Turn list 构造 Controller 历史。

## 1. 目标与边界

`SessionStore` 保持一个应用接口：

```text
SessionStore
├─ InMemorySessionStore   # 本地开发与单进程测试
└─ RedisSessionStore      # 单 Redis primary 下的多 worker 共享状态
```

`PlanService` 只调用 `transaction -> get -> Graph -> append/complete`，不得按后端分支。
Redis backend 必须保持 compact Turn 的顺序、单调 turn index、V3.2-4 的 claim/replay/
conflict/failed-takeover 语义和公开响应重放语义。

本阶段不实现 stateless idempotency、跨 Run 工具缓存、Redis Cluster/Redlock、多 Redis
primary、在线 schema migration 或 V3.2-6 的未捕获异常 Attempt 封存。

## 2. Key 与持久化 schema v1

```text
session_key_hash = sha256("dotamind:session:v1:" + session_id)
request_key_hash = sha256("dotamind:request:v1:" + request_id)
payload_hash     = sha256(canonical_json({"game": game, "query": query}))

dotamind:v1:session:{session_key_hash}:meta        Hash
dotamind:v1:session:{session_key_hash}:turns       List
dotamind:v1:session:{session_key_hash}:requests    Hash
dotamind:v1:session:{session_key_hash}:request_gc  ZSET
dotamind:v1:session:{session_key_hash}:lock        String
```

`meta` 包含 `schema_version`、`turn_counter` 与 `fencing_counter`。`requests` 的 field 为
`request_key_hash`，其 value 是 `StoredRequestRecordV1` JSON；record 内的 `payload_hash`
只用于判断同一 request ID 的输入是否一致。`request_gc` 只索引 completed/failed request
record，score 为过期 Unix timestamp。

所有 JSON 使用 `{ "schema_version": 1, "data": ... }` envelope、UTF-8、稳定 key 排序和
紧凑分隔符。未知版本、未知字段、缺失字段或损坏 JSON 都归约为 `SessionStoreError("data_invalid")`。
Redis key 不包含 query、用户文本、可读实体名称或原始 session/request UUID。

只保存 compact Turn、Session metadata、RequestRecord、allowlisted public response、TTL 和
fencing counter；禁止保存完整 AgentRunState、Prompt、history render block、raw Controller
output、RecoveryFeedback、工具缓存、token 或其他 secret。

## 3. 锁、lease 与 fencing

`transaction(session_id)` 用单个 Lua acquire 脚本原子完成：检查 lock 不存在、递增
`meta.fencing_counter`、写入带 PX lease 的完整 lock value、刷新 Session 数据 TTL，并返回
fencing token。lock value 为：

```json
{"owner_token":"UUID","fencing_token":42}
```

transaction context 按 `asyncio.current_task()` 保存 session base、owner token、fencing token、
renewal task 和 `lock_lost` 标记。续租间隔为
`min(lock_lease_seconds, session_ttl_seconds) / 3`。renew/release Lua
均精确比较完整 lock value；续租失败后，append/claim/complete/fail 必须拒绝为 `lock_lost`。
所有写 Lua 都校验 owner/fencing，因此 lease 过期后的旧 owner 不能迟到写入或删除新 owner 的锁。

锁等待使用 monotonic deadline，超过 `lock_acquire_timeout_seconds` 返回 `lock_timeout`。

## 4. 事务、TTL 与 RequestRecord

写操作在持有 transaction 后执行。Lua `append` 原子分配 turn index、RPUSH、LTRIM 并刷新 TTL。
`complete_request_with_turn` 在一个脚本中校验 lock 和 request owner、分配 turn index、写入 Turn、
完成 RequestRecord、写入 `request_gc` 并刷新 TTL；不得把 Turn 与 completed record 分到两个
await 边界。

claim 脚本惰性删除过期 ZSET member 与 Hash record，在容量超限时按 ZSET 最旧记录删除；
in-progress record 不在 ZSET 中，故可临时超过容量。Session 数据 key 的 TTL 由 acquire、renew
和每次写操作刷新；活跃 transaction 不会因 TTL 清理。request record TTL 与 Session TTL 均由
policy 配置。

## 5. 生命周期与错误

`build_session_store(settings, policy)` 选择 memory 或 Redis。Redis backend 不可用时绝不回退
memory。FastAPI lifespan 在 startup 构建 Store、PING Redis、构建 PlanService；shutdown 调用
`aclose()` 关闭连接池。

`unavailable`、`lock_timeout`、`lock_lost`、`data_invalid` 统一映射为 HTTP 503 的
`error/session_store_error` envelope，不要求 `runtime`。API/worker 重建后，只要重新连接同一份
Redis 数据，compact Turn 与 completed RequestRecord 可恢复；Redis Server 重启后的数据保留由
AOF/RDB、fsync/save 策略和持久卷决定，部署文档必须明确该前提。

## 6. 验收

- 两个独立 Store/PlanService 对同一 Redis Session 串行化；不同 Session 可并发。
- fencing token 原子递增，旧 owner 不能 renew/release/append/complete/fail。
- completed replay、conflict、failed takeover 与 V3.2-4 一致，且只写一个 Turn。
- 真实 Redis 集成测试使用随机 `dotamind:test:{uuid}` 前缀，只删除精确测试 key，禁止 FLUSHDB。
- 重建 Store/PlanService 后可恢复历史和 completed replay；运行时 Redis 错误返回 503，不产生
  memory 分叉。
- 本机 Docker Redis 验收使用 `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`：跨 Store
  集成测试 `13 passed`；启用 Redis 的完整回归为 `459 passed, 1 warning`，未设置 Redis
  环境变量的常规回归为 `446 passed, 13 skipped, 1 warning`。
