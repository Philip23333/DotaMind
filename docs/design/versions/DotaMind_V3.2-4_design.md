# DotaMind V3.2-4 Stateful Request Idempotency 设计

> 状态：已完成。完整 `pytest` 为 `436 passed, 1 warning`；`ruff check .`、
> `uv lock --locked` 和 `git diff --check` 均通过。本文定义 V3.2-4 在单进程
> `InMemorySessionStore` 中的请求幂等边界；Redis、lease、fencing 和多 worker
> 语义仍属于 V3.2-5。

## 1. 阶段目标

V3.2-4 为 stateful `POST /api/v1/plan` 增加可选 UUID v4 `request_id`。同一
`(session_id, request_id)` 在 RequestRecord 有效期内只代表一次逻辑请求：成功、受控
错误或业务边界结果都只执行一次 Graph、只写一个 compact Turn，并在重试时重放第一次
已经 allowlist 的公开响应。

本阶段不改变 v2.5 constrained tool calling：`intent` 不是路由键，Graph 仍只根据
`ControllerDecision` 和 runtime status 路由；幂等发生在 Graph 之前和 SessionStore
事务边界内。

## 2. API 与键语义

```json
{
  "query": "enemy picked Lina, what should I pick?",
  "game": "dota2",
  "session_id": "UUID v4",
  "request_id": "UUID v4"
}
```

| 输入 | 行为 |
|---|---|
| 未提供 `request_id` | 保持既有 stateful/stateless 行为。 |
| `session_id` 和 `request_id` 均提供 | 启用幂等。 |
| 只有 `request_id` | 422 validation error；首版不支持 stateless subject。 |
| 相同 key、相同 request hash、已完成 | 重放原公开响应；不运行 Graph、不追加 Turn。 |
| 相同 key、相同 hash、正在执行 | 等待同一 Session transaction；不得并行执行。 |
| 相同 key、不同 hash | HTTP 409，`error/idempotency_conflict`。 |

键固定为：

```text
(session_id, request_id)
```

request hash 固定为 UTF-8、稳定 key 排序、紧凑分隔符的：

```text
sha256(canonical_json({"game": validated_game, "query": validated_query}))
```

不对 query 做大小写、空白或语义归一化；不同的已验证输入就是 conflict。

## 3. RequestRecord

```text
RequestRecord
├─ request_id
├─ request_hash
├─ status: in_progress | completed | failed
├─ owner_token
├─ run_id
├─ cached_public_response
├─ turn_index
├─ started_at / completed_at
└─ expires_at
```

- `completed` 必须包含 allowlisted public response、`run_id` 和 `turn_index`。
- `in_progress` 不包含 response/turn；同一 Session lock 持有期间其他请求只能等待。
- 受控 Graph 终态（包括 `error`、`insufficient_evidence` 和 capability boundary）仍是
  completed request，可以重放。
- 未捕获异常或 cancellation 将当前 owner 标为 failed，且不追加 Turn；后续同 hash
  请求可以接管。若取消发生在上游已经产生副作用之后，内存后端不能承诺跨进程的
  exactly-once；该故障模型留给 V3.2-5/6。
- 记录只保存 public response 的深拷贝，绝不保存 `AgentRunState`、history、Prompt、raw
  Controller output、RecoveryFeedback、工具指纹缓存、token 或原始异常。

## 4. 事务与原子提交

stateful 服务流程为：

```text
transaction(session_id)
  -> begin_request
       -> replay   -> return cached public response
       -> conflict -> HTTP 409
       -> execute  -> get history -> Graph -> build Turn
                         -> complete_request_with_turn
```

`complete_request_with_turn` 在同一个 Session transaction 中校验 owner token，并一次
完成：分配 `turn_index`、追加 Turn、保存公开响应、写入 `run_id/turn_index`、标记
completed。不得把 append 与完成记录分成两个 await 边界。

当前 InMemorySessionStore 的 per-session lock 已覆盖完整 `get -> run -> append`，所以
同 key 并发请求只会有一个 Graph owner。不同 request id 仍按 Session 顺序串行化，以
保持 history 和 Turn index 语义。

## 5. 生命周期、容量与公开响应

`ConversationPolicy` 新增：

```yaml
request_record_ttl_seconds: 3600
max_request_records_per_session: 200
```

- 只惰性清理已过期的 completed/failed records；in-progress record 不会因 TTL 被删除。
- 容量淘汰只删除非 in-progress 的最旧记录；所有记录均为 in-progress 时允许临时超过
  上限。
- Session LRU 淘汰自然同时删除其中的 RequestRecord。
- 缓存命中不创建新的 Run；因此重放 response 内的 `runtime.run_id` 与首次执行相同。
- conflict 在 `run_init_node` 之前发生，使用独立的无 `runtime` 公开错误 envelope，不能
  伪造 Attempt。

`RunContext.request_id` 由 `AgentRunState.internal_request_id` 传入，只作受控内部关联，
不进入 Prompt、history、AttemptRecord 或普通日志全文。

## 6. 非目标

- 不支持 stateless request idempotency。
- 不实现 Redis、跨 worker、lease、fencing、进程重启恢复或 distributed takeover。
- 不增加跨 Run 工具缓存、Graph 节点/回边、Controller/Prompt/Registry 修改、Critic
  Recovery、旧 endpoint 或 `intent` 路由。
- 不把 cancellation、进程退出或未捕获异常的 Attempt 封存扩展为新的 Graph 行为；该收口
  属于 V3.2-6。

## 7. 验收矩阵

1. 相同 key 顺序重放：一次 Graph、一个 Turn、相同公开 response 和 `run_id`。
2. 相同 key 并发：第二个请求等待，只有一个 owner。
3. 相同 key 不同 query/game：409 conflict，不执行第二次 Graph、不写 Turn。
4. 不同 request id 或不同 Session：保持独立的正常请求语义。
5. request id 缺少 session id：422。
6. 受控错误可以重放；cancellation 后无半成品 Turn 且后续 owner 能接管。
7. TTL/容量规则确定，缓存和重放中没有 history 或其他内部敏感内容。
8. 完整 pytest、ruff、lock check、diff check 和中英文每日进度快照通过。
