# DotaMind V3.3-2：多聊天并行运行与断线恢复

> 状态：阶段 A、B（B1-B8）已完成；C-E 尚未实现。
>
> 本阶段建立在 V3.3-1 的 PostgreSQL 聊天记录、Redis SessionStore lease/fencing 和
> V3.2 Run/Attempt/Budget 运行时之上。本文是本阶段实现的边界和验收合同。

## 1. 目标与范围

本阶段为同一匿名浏览器提供多聊天并行运行能力：

- 不同 `session_id` 可以同时执行 Run。
- 同一个聊天同时最多有一个活动 Run。
- HTTP/NDJSON 订阅只是观察通道，客户端断开不会取消后台 Run。
- Run 状态和最终聊天 Turn 由 PostgreSQL 持久化。
- Redis 只保存短期可重放运行事件和取消通知，并继续承担已有 session lease 协调。
- 用户显式停止时只取消指定 `run_id`。
- 切换、刷新或重新订阅后可以恢复活动 Run 的状态和事件。
- 完成后继续使用 V3.3-1 的自动标题、会话排序和 Turn 语义。

运行身份必须贯穿数据库、Graph、Trace、事件和 API：

```text
chat_runs.id == RunContext.run_id == public runtime.run_id
```

## 2. 阶段边界

本阶段包含：

- `chat_runs` 持久化和状态机。
- 后台 Run 管理、每 worker 并行上限和 heartbeat。
- Redis Stream 事件重放、TTL 和取消通知。
- 创建、查询、active Run、事件订阅和取消 API。
- 浏览器级 Run Store、切换恢复、未读状态和指定 Run 停止。
- stale Run 和服务重启后的 `interrupted` 收口。

本阶段不包含：

- 同一个聊天同时运行多个 Run。
- 登录、跨设备同步或多浏览器共享 Run。
- 独立任务队列或独立 Worker 服务。
- 服务重启后从模型生成的中间位置继续执行。
- LangGraph checkpoint。
- 消息编辑、重新生成和对话分支。

`interrupted` Run 不自动续跑；已经提交的 `chat_turns` 不得丢失。

## 3. 存储职责

```text
浏览器
  Run Store / 订阅 cursor / 未读 last-seen
          |
          v
PostgreSQL（权威）
  chat_runs: Run 状态、幂等、worker、heartbeat、最终 Turn 关联
  chat_sessions / chat_turns: 会话和最终聊天记录
          ^
          |
Redis（协调与短期事件）
  SessionStore lease/fencing
  per-run Stream、sequence、取消通知
```

PostgreSQL 负责最终业务事实。Redis Stream 过期或事件写入失败不得撤销已经提交的
PostgreSQL Turn；订阅端应通过 Run 状态或 transcript 恢复。

## 4. Run 状态机

活动状态为：

```text
queued | running | cancel_requested
```

终态为：

```text
completed | failed | cancelled | interrupted
```

合法转换：

```text
queued
  -> running
  -> cancel_requested
  -> interrupted
  -> failed

running
  -> completed
  -> cancel_requested
  -> failed
  -> interrupted

cancel_requested
  -> cancelled
  -> interrupted
```

任何终态不得再次转换；`cancel_requested -> completed` 明确禁止。完成和取消竞争时，
由 PostgreSQL 条件更新决定先获胜的一方。

取消语义：

- 导航或 HTTP 订阅断开只停止观察，不产生 `cancel_requested`。
- 用户点击“停止生成”才请求取消指定 Run。
- PostgreSQL 的 `cancel_requested` 是权威状态；Redis 通知只是低延迟加速器。
- worker shutdown 或 stale recovery 归约为 `interrupted`，不伪装成用户取消。

## 5. 并行和 worker 边界

`DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` 定义为单个 API worker 的并行上限。达到上限时
Run 保持 `queued`，不会回退到同步 HTTP 执行。

本阶段没有独立任务队列或分布式 semaphore，因此部署总并行上限为：

```text
API worker 数 × 每 worker 并行上限
```

如未来需要部署级严格上限，应另行设计 Redis semaphore 或任务队列，不在本阶段隐式加入。

## 6. PostgreSQL `chat_runs` 合同

建议字段：

| 字段 | 语义 |
| --- | --- |
| `id UUID` | 预分配的 `RunContext.run_id` |
| `session_id UUID` | 所属会话，级联删除 |
| `request_id UUID` | 客户端幂等请求键 |
| `payload_hash VARCHAR(64)` | query/game 的规范化 hash |
| `user_query TEXT` | 未完成 Run 恢复所需的用户输入 |
| `status VARCHAR` | 封闭状态集合 |
| `fencing_token BIGINT` | 本次执行的 PostgreSQL fencing token |
| `worker_id VARCHAR` | 当前执行 worker |
| `last_event_sequence BIGINT` | 已持久化的最后事件序号 |
| `result_turn_id UUID` | 完成后的 `chat_turns.id` |
| `error_code VARCHAR` | 稳定错误码，不保存原始异常 |
| `created_at` | 创建时间 |
| `started_at` | 开始执行时间 |
| `heartbeat_at` | 最近心跳 |
| `cancel_requested_at` | 用户请求停止时间 |
| `completed_at` | 终态时间 |

约束和索引：

```text
UNIQUE(session_id, request_id)
UNIQUE(result_turn_id) WHERE result_turn_id IS NOT NULL
UNIQUE(session_id) WHERE status IN ('queued', 'running', 'cancel_requested')
INDEX(session_id, status)
INDEX(status, heartbeat_at)
INDEX(worker_id, status)
```

数据库状态约束和应用层状态转换必须同时存在；应用层不接受未知状态。

## 7. 幂等与所有权

创建 Run 时使用 `(session_id, request_id)` 幂等键，并校验 `payload_hash`：

- 相同 key、相同 payload：返回已有 Run，不重复调度。
- 相同 key、不同 payload：返回 `409 idempotency_conflict`。
- 同一个 session 已有其他活动 Run：返回 `409 chat_run_active`。
- 不同 session 可以并行创建和执行。

所有 Run API 都必须通过 `browser_id_hash` 校验 session 所有权。不存在和不属于当前
浏览器统一返回 `404`，不泄漏其他浏览器的 Run 是否存在。

## 8. 原子完成

`complete_with_turn()` 必须在一个 PostgreSQL 事务中完成：

1. 锁定 `chat_runs` 行并确认状态仍为 `running`。
2. 校验 Run fencing token。
3. 锁定 `chat_sessions` 行并再次确认 session fencing token。
4. 分配单调 `turn_index`。
5. 写入 `chat_turns`。
6. 更新自动标题、`next_turn_index` 和 `updated_at`。
7. 更新 Run 为 `completed`。
8. 写入 `result_turn_id` 和 `completed_at`。

如果 Run 已经是 `cancel_requested`，不得写入 assistant Turn。

## 9. Redis Stream 事件

每个 Run 使用独立 Stream。Redis key 使用稳定命名空间和 Run ID hash，不包含 query 或
用户文本。事件由后台 Run-scoped Queue 的 Event Pump 写入 Redis；Graph 节点继续调用
现有同步事件发布接口，不直接依赖 HTTP 请求。

每条事件至少包含：

```json
{
  "run_id": "uuid",
  "session_id": "uuid",
  "sequence": 12,
  "type": "tool"
}
```

允许的事件类型：`phase`、`tool`、`answer_delta`、`result`、`error`、`status`。

事件禁止包含 prompt、history、工具参数、raw Controller output、原始异常和 secret。
事件具有 TTL；事件过期不代表 Run 失败。完成 Run 的 transcript 仍由 PostgreSQL 恢复。

## 10. API 合同

```text
POST /api/v1/chat/sessions/{session_id}/runs
GET  /api/v1/chat/runs/{run_id}
GET  /api/v1/chat/sessions/{session_id}/active-run
GET  /api/v1/chat/runs/{run_id}/events?after=N
POST /api/v1/chat/runs/{run_id}/cancel
```

`POST` 新建 Run 返回 `202`；相同 request/payload 返回已有 Run；冲突返回 `409`。
事件订阅按 `sequence > after` 重放，然后等待新事件。HTTP disconnect 只关闭订阅，不取消
后台任务。若 Redis 事件已过期但 PostgreSQL 已有终态，返回有限终态状态并要求客户端
刷新 transcript。

`GET /chat/sessions` 和 transcript 的 session summary 增加 `active_run`，避免前端为
每个聊天逐个查询活动状态。

## 11. 前端边界

运行状态位于浏览器级 Store，而不是 keyed `ChatSessionRuntime`：

```text
runsById[run_id]
activeRunIdBySession[session_id]
```

事件必须同时校验 `run_id`、`session_id` 和递增 sequence。切换聊天只 Abort 旧订阅；用户
停止必须单独调用 cancel API。pending 用户消息使用 `run_id` 派生的稳定 ID，刷新后可从
active Run 恢复。

未读状态仍只保存于匿名浏览器 localStorage。进入聊天后更新 last-seen；后台完成的非当前
聊天显示未读，不引入账号级通知。

## 12. 故障和隐私边界

- Redis lease、事件或取消通道不可用时暴露稳定错误，不创建内存分叉。
- Redis 事件写入失败不回滚已经提交的 PostgreSQL Turn。
- worker shutdown 和 stale Run 统一为 `interrupted`，不自动续跑。
- 旧 fencing token 不能更新、完成或删除新的 Run/Session 资源。
- 公共响应、Trace、metrics、Redis 事件和 Run 审计字段均使用 allowlist。
- 不保存 raw Prompt、完整 AgentRunState、完整 history、原始模型输出或 token。

## 13. 实施顺序

```text
A1 设计合同
  -> A2 chat_runs 模型与迁移
  -> A3 Run Repository
  -> A4 原子完成
  -> A5 Repository 测试
  -> B1-B8 后台执行与 Redis 事件
  -> C1-C7 Chat Run API
  -> D1-D8 前端 Run Store
  -> E1-E6 恢复、验收与文档收口
```

每个小阶段都必须通过对应验证并独立提交；未完成的小阶段不得被进度文档描述为已完成。

## 14. 阶段 A 完成定义

- 本文档存在且状态明确为“阶段 A 已完成”。
- Run 状态集合、转换、幂等、fencing、事件和所有权边界已冻结。
- 明确 per-worker 并行上限和无 checkpoint 的重启语义。
- `chat_runs` ORM、migration、Repository lifecycle 和 atomic completion 已实现并有回归入口。
- 未修改 `/plan`、`/plan/stream`、后台调度或前端运行链路。
