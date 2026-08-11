# DotaMind V3.2 Agent Runtime Foundation 设计

> 状态：已完成并通过 V3.2-6 最终验收（2026-08-02）。
>
> V3.2 冻结业务工具扩张，优先完善 Agent 运行时。本文不替代
> `DotaMind_MVP_v2.5.md` 的 constrained tool calling 边界，也不改变 V3.0
> 已闭环的业务能力；它定义的是已有能力如何更可靠、可恢复、可追踪地运行。

更新日期：2026-08-02

> 当前覆盖说明（2026-08-11）：本文第 7-8 节记录 V3.2 当时的 stateful `/plan`
> RequestRecord 与 compact Turn SessionStore 基线。正式多轮现已迁移到 PostgreSQL
> Chat Session/Run/Turn；Controller 默认读取 Redis `RecentDialogueWindow` 中的真实
> role messages，cache miss 时从 PostgreSQL 重建。当前合同见
> [`../architecture/ConversationMemory层.md`](../architecture/ConversationMemory层.md) 和
> [`../../technical/architecture.md`](../../technical/architecture.md)。

## 1. 背景

DotaMind 当前已经具备一条统一 Agentic 路径：

```text
Controller
  -> Decision Validation
  -> Plan Validation
  -> Tools
  -> EvidenceGraph
  -> Answer
  -> Critic
  -> Response
```

Session memory 也已通过自建 `SessionStore` 接入：客户端复用 `session_id`，
`ChatRunExecutor` 在同一会话事务中完成 recent-message load -> graph run ->
PostgreSQL commit。完整用户/助手消息保存在 PostgreSQL，Redis 只保存受限
`RecentDialogueWindow`；下一轮 Controller 读取真实 role messages，而不是
结构化 referent/group/relation 状态。更早的对话可由内部
`conversation.history_lookup` 最多查找一次，并只在当前 Run 中生效。该扩展不改变
本文件定义的 Tool Calling、EvidenceGraph、Answer、Critic 和 SessionStore 边界。

1. 一次请求只有一组 `plan/tool_results/evidence/answer/review`，无法表达多次
   尝试，也无法安全实现 replan。
2. Evidence 或 Critic 判定可补救的问题时，当前只能终止，不能有界补证。
3. 缺少请求级幂等；客户端超时重试可能重复调用上游并重复写入 Turn。
4. `InMemorySessionStore` 仅单进程有效，API 重启或多 worker 时无法共享历史。
5. Trace 缺少 `run_id`、attempt、时间和累计预算，难以定位慢请求与恢复行为。
6. Controller、会话、catalog、contract、sample policy 和 retry feedback 混合在
   大型 Prompt 中，缺少明确版本与变更归因。

V3.2 将这些问题视为同一个目标：建立受预算约束、可恢复、幂等、可持久化且
可审计的 Agent Runtime。

## 2. 目标与非目标

### 2.1 目标

- 将一次 API 请求建模为 `AgentRun`，将每次规划执行建模为 `Attempt`。
- 在不放松 evidence 和 contract 边界的前提下支持最多一次自动 replan。
- 用全局预算限制 Controller、工具调用、运行时间和重复调用。
- 为 stateful 请求增加可选 `request_id` 幂等语义。
- 在保持 `SessionStore` 接口边界的基础上落地 Redis 持久化和分布式互斥。
- 收敛 Prompt 组成并记录稳定版本/hash，不向客户端暴露原始 Prompt。
- 让日志、trace、debug UI 能解释每次尝试、失败阶段和恢复结果。
- 保持现有公开错误边界、隐私边界和单轮无状态行为。

### 2.2 非目标

- V3.2 不新增 Dota 数据工具、业务 intent 或固定 pipeline。
- 不恢复旧 `/api/v1/query`、旧 report endpoints 或遗留前端。
- 不做无限 replan，不引入开放式 autonomous loop。
- 不让 LLM 修改工具 registry、拼接 URL、GraphQL 或 SQL。
- 不对 tool transport error 做静默 fallback 或换源掩盖。
- 不引入 LangGraph checkpointer；完整对话消息只由 PostgreSQL transcript 持久化，
  不写入 Redis prompt block 或 Controller raw output。
- 不持久化原始 Controller output、完整 Prompt、完整 history block 或 secret。
- 不增加第二个 LLM reviewer；Critic 继续 rule-first。
- 不在 V3.2 处理登录、付费、用户账号或跨用户共享会话。

## 3. 设计原则

1. **有限智能，确定性护栏**：LLM 提议，代码决定是否合法、是否可恢复以及还能
   消耗多少预算。
2. **Attempt 不覆盖历史**：每次尝试形成独立记录；最终结果可以选择最后一次有效
   尝试，但早期失败原因不能丢失。
3. **补证而非重跑**：replan 应增加必要证据；已经成功的相同工具调用不得再次访问
   上游。
4. **失败分类先于重试**：只有明确标记为 recoverable 的 evidence/quality 缺口才能
   replan。网络错误、非法计划和 Answer 失败直接暴露。
5. **全局预算优先**：每个 plan 的限制不能替代整个 run 的累计限制。
6. **幂等先于分布式**：Redis 不是简单换存储；请求幂等、Turn index 和锁所有权必须
   一起设计。
7. **隐私默认关闭**：内部调试数据采用 allowlist 输出，不以 denylist 猜测敏感字段。

## 4. 目标运行图

```text
START
  -> run_init_node
  -> controller_node
  -> decision_validate_node
      -> direct_answer -> conversation_answer_node -> attempt_finalize_node
      -> clarification -----------------------------> attempt_finalize_node
      -> context_missing ---------------------------> attempt_finalize_node
      -> capability_boundary -----------------------> attempt_finalize_node
      -> tool_plan
           -> validate_plan_node
           -> tool_executor_node
           -> evidence_node
               -> recoverable gap -> attempt_finalize_node
               -> answer_node
                    -> critic_node
                    -> attempt_finalize_node
  -> recovery_node
      -> terminal -> run_finalize_node -> response_node -> END
      -> replan -> attempt_reset_node -> controller_node
```

### 4.1 路由规则

- Graph 仍只按 decision discriminator、runtime status 和 recovery result 路由，
  永不按 `intent` 路由。
- `direct_answer`、clarification、context missing 和 capability boundary 不进入
  tool/evidence/critic 路径，也不会因为 recovery 机制被转换成工具计划。
- evidence 已确定缺失时，不应先调用 Answer LLM 再尝试恢复。
- V3.2-3 首版只恢复全局 missing-evidence 缺口；Critic Recovery 延后到存在稳定、
  Graph 可达的结构化质量失败码后再设计。
- `recovery_node` 是确定性规则节点，不是新的 LLM Agent。

## 5. 核心状态模型

### 5.1 RunContext

```python
class RunContext(BaseModel):
    run_id: UUID
    request_id: UUID | None
    session_id: UUID | None
    started_at: datetime
    deadline_at: datetime
    prompt_versions: dict[str, str]
```

- `run_id` 由服务端为每次实际执行生成。
- `request_id` 由客户端可选提供，用于幂等，不等同于 `session_id`。
- `session_id` 表示会话安全主体和 Turn 序列。
- 对外日志只显示 `session_id`/`request_id` 的短前缀；完整值仅用于受控内部关联。

### 5.2 RunBudget

```python
class RunBudget(BaseModel):
    max_replans: int = 1
    max_tool_calls_total: int = 8
    max_controller_calls: int = 2
    max_answer_calls: int = 2
    max_elapsed_seconds: int = 60

    replans_used: int = 0
    tool_calls_used: int = 0
    controller_calls_used: int = 0
    answer_calls_used: int = 0
```

说明：

- Controller 自身的 JSON/validation retry 与 replan 是两个预算维度，必须分别记录。
- `max_tool_calls_total` 按整个 run 的唯一工具调用计数，不按 attempt 重置。
- `deadline_at` 只用于审计展示；是否超限使用 monotonic elapsed 判断。
- V3.2-1 只记录超限而不阻止节点；从 V3.2-3 起，达到 deadline 后尚未启动的 node
  不得继续执行，并归约为 `execution_timeout`。
- 用户明确的样本或过滤条件不得为了“恢复成功”而静默放宽。

### 5.3 AttemptRecord

```python
class AttemptRecord(BaseModel):
    attempt_index: int
    decision_kind: str | None
    plan_summary: AttemptPlanSummary | None
    tool_calls: list[AttemptToolCallSummary]
    evidence_summary: AttemptEvidenceSummary | None
    answer_summary: AttemptAnswerSummary | None
    critic_summary: AttemptCriticSummary | None
    status: AttemptStatus
    failure_stage: FailureStage | None
    recovery_code: Literal["missing_evidence"] | None
    started_at: datetime
    duration_ms: int
```

`AttemptRecord` 是审计摘要，不存储：

- 完整 `ExecutionPlan`、完整 `ToolResult`、回答文本或 Critic reasons；
- 原始模型 output；
- Prompt messages；
- 完整 conversation history；
- 未脱敏 validation feedback；
- API token、Authorization header 或带 query string 的敏感 URL。

### 5.4 AgentRunState 调整

`AgentRunState` 保留当前 attempt 的工作字段，并增加：

```text
run_context
run_budget
attempt_index
attempts[]
recovery_action
recovery_feedback
recovery_baseline_decision
executed_call_fingerprints
runtime_failure_code
terminal_stage
```

V3.2 的长期状态选择是“平铺 state + 集中 reset”：原始 attempt 工作字段永久平铺在
`AgentRunState`，不引入 `InternalAttemptState`、`current_attempt`、代理属性或双写路径。
`AttemptRecord` 永远只承载 allowlist 审计摘要。V3.2-1 实现纯函数
`reset_attempt_working_state()`；V3.2-3 的 `attempt_reset_node` 只能调用该函数，不能复制
或另建 reset 逻辑。

进入下一次 attempt 前，集中 reset 只清理当前 attempt 的：

```text
controller_result / decision / plan
required evidence resolution
current tool results / evidence / answer / review
attempt-local errors
```

它不得清理：

```text
history / session_memory_enabled
run_context / run_budget
attempts
成功或失败的 Run-local 工具调用缓存
累计 trace
```

## 6. Recovery 与 Replan

### 6.1 RecoveryFeedback

Controller 接收的是结构化、脱敏后的失败摘要：

```json
{
  "failure_stage": "evidence",
  "code": "missing_evidence",
  "missing_evidence": ["sample_size"],
  "executed_calls": [
    {
      "id": "matchup",
      "tool": "stratz.hero_matchup_ranking",
      "status": "ok"
    }
  ],
  "remaining_tool_budget": 3,
  "replan_index": 1
}
```

不得包含完整 ToolResult data、原始 Answer、raw Controller output 或历史全文。

### 6.2 可恢复性矩阵

| 失败/终态 | 是否 replan | 原因 |
|---|---:|---|
| Controller transport/model error | 否 | 再规划仍依赖同一个不可用 Controller。 |
| Decision/plan validation retries exhausted | 否 | 候选计划不可信。 |
| clarification/context missing/capability boundary | 否 | 需要用户输入或缺少注册能力。 |
| Tool transport/handler/reference error | 否 | 必须直接暴露真实上游或执行错误。 |
| 全局 effective evidence 缺失，且 registry 中存在未使用的可产出工具 | 是 | 可以补工具调用。 |
| Critic 判定质量不足 | 否 | 首版没有真实、稳定且 Graph 可达的结构化失败码。 |
| 用户明确样本/范围导致结果稀疏 | 否 | 不得静默放宽用户约束。 |
| Answer LLM failure | 否 | 与 plan/evidence 无关。 |
| 可恢复缺口但 replan/controller/tool budget exhausted | 否 | `replan_exhausted` 收口。 |
| Attempt 执行中超预算或 duplicate fingerprint | 否 | `execution_budget_error` 收口。 |

### 6.3 Replan 输出约束

Replan 仍返回完整 `ControllerDecision`。若返回 `tool_plan`：

- Attempt 0 的全部调用必须以相同顺序和 `id/tool/args` 作为完整前缀。
- `intent`、`goal`、`output_contract`、`context`、`constraints` 必须完全一致。
- `required_evidence` 规范化后必须完全相等，不允许增加或删除。
- 至少追加一个使用此前未用工具的新调用，且新 id 不得与旧 id 重复。
- 既有 output reference 继续指向原 call id。
- 新 plan 必须重新经过 sample policy、catalog、contract、reference 和 evidence
  producibility 校验。
- 不允许通过改变 call id 绕过重复调用检测。

### 6.4 工具调用指纹与复用

工具指纹按以下内容规范化后计算：

```text
sha256(canonical_json({"tool": tool_name, "args": resolved_args,
                       "context": full_query_context}))
```

- 不包含模型生成的 call id。
- 引用参数必须先解析成实际值再计算。
- 相同指纹且 call id 相同时，executor 复用原 ToolResult，不再次调用上游；成功结果
  的复用延迟记为 `0`。
- 相同指纹已有失败结果时，不自动重试；最终保留 tool error。
- 相同指纹换 call id 时返回 `execution_budget_error`。
- 复用通过 Attempt tool-call summary 的 `reused` 字段公开，不增加唯一工具调用预算；
  V3.2-6 前不增加工具级 TraceEvent。

## 7. 请求幂等

### 7.1 API 语义

`POST /api/v1/plan` 增加可选 UUID v4：

```json
{
  "query": "enemy picked Lina, what should I pick?",
  "game": "dota2",
  "session_id": "optional UUID v4",
  "request_id": "optional UUID v4"
}
```

- 不提供 `request_id` 时保持当前行为。
- 提供 `request_id` 时，幂等键为 `(session_id, request_id)`；无 session 的请求可
  使用 `(stateless subject, request_id)`，但第一阶段可只对 stateful 请求启用。
- 相同幂等键必须同时校验 query/game 的稳定 request hash。

### 7.2 RequestRecord

```text
RequestRecord
├─ request_hash
├─ status: in_progress | completed | failed
├─ owner_token
├─ run_id
├─ response_summary / cached public response
├─ turn_index
├─ started_at
└─ expires_at
```

行为：

- `completed + same hash`：返回已保存的公开响应，不重新执行、不追加 Turn。
- `in_progress + same hash`：等待已有执行或返回稳定的 in-progress 结果；不得并行执行。
- `same key + different hash`：返回 idempotency conflict。
- owner 崩溃且 lease 过期：允许新 owner 接管，但必须依赖 fencing token 防止旧 owner
  迟到写入。
- 只有最终 owner 可以把 RequestRecord 标记为 completed 并 append Turn。

## 8. RedisSessionStore（V3.2 历史基线）

### 8.1 目标

```text
SessionStore
├─ InMemorySessionStore   # 本地/单 worker
└─ RedisSessionStore      # 多 worker/重启持久化
```

Redis 后端必须保持：

- `get` 返回按 `turn_index` 排序的 compact Turn 快照；
- `append` 原子分配单调 turn index；
- 每个 session 最多保留配置数量的 Turn；
- session 和 request record 支持 TTL；
- 同一 session 的完整 request transaction 串行化；
- 活跃 session 不被容量清理误删；
- JSON schema version 可迁移。

### 8.2 分布式锁

第一版以单 Redis primary 为边界：

- `SET lock_key owner_token NX PX lease_ms` 获取锁；
- Lua compare-and-delete 释放锁；
- Lua compare-and-pexpire 续租；
- 每次获取锁同时取得单调 fencing token；
- append/complete 必须携带 fencing token，旧 owner 即使恢复也不能覆盖新 owner。

禁止：

- 无 token 的 `DEL lock_key`；
- 仅依赖固定 TTL 而没有续租；
- 锁过期后允许旧任务继续 append；
- 将 Redis 连接失败降级为新的本地会话，造成同一 session 分叉。

### 8.3 存储内容

Redis 只保存：

- compact `Turn`；
- session metadata；
- idempotency `RequestRecord`；
- 必要的公开响应缓存；
- schema version、TTL 和 fencing counter。

不保存 raw messages、Prompt、raw Controller output 或 secret。

## 9. Prompt Registry 与版本

建议收敛为：

```text
app/agentic/prompts/
├─ controller_base.py
├─ conversation_rules.py
├─ recovery_rules.py
├─ catalog_renderer.py
├─ contract_renderer.py
├─ sample_policy_renderer.py
├─ retry_feedback.py
└─ versions.py
```

要求：

- Prompt 由小型纯函数组成，动态 catalog/contract 仍来自 registry。
- 每个组成部分有稳定版本；组合后计算 hash。
- `RunContext.prompt_versions` 记录版本和 hash，不记录 Prompt 正文。
- validation retry 和 replan feedback 分开，不能混用同一错误模板。
- Prompt 重构阶段不改变公开决策 schema 和已有语义；使用 golden/fixture 测试控制
  渲染变化。

## 10. 可观测性

### 10.1 TraceEvent

```python
class AgentTraceEvent(BaseModel):
    run_id: UUID
    attempt_index: int
    node: str
    action: str
    status: str
    started_at: datetime
    duration_ms: int
    tool_call_id: str | None = None
    recovery_code: str | None = None
```

### 10.2 指标

至少采集：

- run 总量、终态和总延迟；
- Controller 调用、validation retry 和失败率；
- 各工具调用量、延迟、错误率和复用率；
- evidence completeness 与 missing kinds；
- Critic pass/warning/failed；
- recovery candidate、replan 触发和成功率；
- budget exhausted 与 duplicate-call blocked；
- Session Store get/append、命中、淘汰、锁等待和 TTL 过期；
- request idempotency hit/conflict/takeover。

标签必须控制基数。不得把完整 query、answer、session_id、player id 或模型文本作为
指标 label。

### 10.3 Debug UI

`/debug/plan` 增加：

- Run summary：run id、预算、总耗时；
- 最多两个 Attempt 的列表和每次终态；
- ToolResult `reused` 标识和 Attempt 1 的固定 `recovery_code`；
- 最终公开结果。

继续禁止展示 raw Prompt、raw Controller output 和完整 history。

## 11. 配置

建议增加：

```yaml
planning:
  runtime:
    max_replans: 1
    max_tool_calls_total: 8
    max_controller_calls: 2
    max_answer_calls: 2
    max_elapsed_seconds: 60

conversation:
  backend: memory
  session_ttl_seconds: 86400
  request_record_ttl_seconds: 3600
  lock_lease_seconds: 90
```

Redis URL、密码、TLS 和部署开关属于 `.env`，不能进入 `policy.yaml`：

```text
DOTAMIND_SESSION_STORE_BACKEND=memory|redis
DOTAMIND_REDIS_URL=
```

所有配置必须由 Pydantic 在启动时 fail-fast 校验。

## 12. 错误与公开响应

V3.2 尽量复用当前顶层 status，不因内部 attempt 增加大量不稳定枚举：

| 内部终态 | 公开 status / response type |
|---|---|
| replan 后成功 | 原成功类型，并公开有限 attempt 摘要 |
| recoverable gap 但预算耗尽 | `insufficient_evidence` / `replan_exhausted` |
| duplicate tool blocked | `error` / `execution_budget_error` |
| run deadline exceeded | `error` / `execution_timeout` |
| idempotency key 参数冲突 | `error` / `idempotency_conflict` |
| Redis 不可用 | `error` / `session_store_error` |

优先级仍保持：Controller/validation/tool/answer/evidence/critic。Recovery 不能把早期
tool error 改写成 missing evidence，也不能把 Answer error 改写成 critic failure。

## 13. 隐私与安全不变量

- `session_id` 继续作为单一用户安全主体的 bearer capability；生产账号体系以后再
  增加 owner 绑定。
- history 只进入当前请求 Controller，不进入公开 response、trace 或 metrics。
- AttemptRecord 和 Redis record 均使用 allowlist DTO。
- V3.2-3 只引入固定 `RecoveryCode="missing_evidence"`。它表示“当前 Attempt 因何
  启动”：Attempt 0 永远为 null，实际启动的 Attempt 1 才记录该 code；已经封存的
  Attempt 0 不回写。
- 日志不得输出 discarded recall answer、raw validation echo 或 retry messages。
- 幂等缓存保存的是已经过 public mapper/response allowlist 的响应。
- Redis key 不直接使用可读 query 或用户文本；session/request UUID 应 hash 或使用
  固定命名空间。
- debug UI 只用于本地/受控环境；部署时应可关闭或受访问控制保护。

## 14. 分阶段实施

### V3.2-0：冻结与护栏

- 冻结当前 tool registry；本阶段不新增业务工具。
- 为现有 Graph、错误优先级、session privacy 和 Controller decisions 建立
  characterization tests。
- 更新 node/tool/edge inventory，标记目标节点但不假装已经实现。

### V3.2-1：Run / Attempt / Budget

- 增加 `RunContext`、`RunBudget`、`AttemptRecord`。
- 固定“平铺 state + 集中 `reset_attempt_working_state()`”长期边界。
- Trace 增加 attempt 和时延。
- Graph 保持一次执行，外部行为不变。
- `/debug/plan` 能显示单 attempt。

### V3.2-2：Prompt Registry

- 拆分 Controller Prompt 和 retry feedback。
- 增加 recovery rules renderer 和 prompt version/hash；hash 表示 configured/prepared
  system prompt，不表示 LLM 已发送或成功。
- 默认装配中，Controller 渲染 Prompt 前关闭 ToolRegistry 注册期，使 Prompt、validation 与
  executor 使用同一 registry catalog；不引入深度冻结或 fingerprint；recovery rules 在本阶段保持 dormant。
- 使用 golden tests 确认语义不漂移。

### V3.2-3：有界 Recovery/Replan（已完成）

- 增加 attempt finalize、recovery、attempt reset 节点。
- 首版只恢复真实可达的全局 missing-evidence 缺口；Critic Recovery 延后。
- 实现可恢复矩阵、全局预算、deadline guard 和工具指纹复用。
- `max_replans` 固定从 1 起步；不提供无限配置。
- duplicate fingerprint 阻断始终启用，不增加配置开关或 `reused_tool_result_ids`。
- debug UI 沿用 runtime JSON 展示最多两个 attempt。

### V3.2-4：请求幂等（已完成）

- API 增加可选 `request_id`。
- InMemory store 先实现 RequestRecord 语义和并发测试。
- 相同请求只执行一次、只写一个 Turn。
- 首版只支持 stateful `(session_id, request_id)`；request record 使用 TTL 与每
  Session 容量上限，Redis/lease/fencing 延后到 V3.2-5。

### V3.2-5：Redis Session Store（已完成）

- 实现 JSON schema、TTL、distributed lease、fencing 和 atomic append。
- 保留 memory backend 用于测试和单 worker 本地开发。
- Redis 配置失败时直接启动失败或返回 session store error，不回退到分叉的本地状态。
- Redis key、schema、lease/fencing、RequestRecord Hash + GC ZSET 与 API/worker 重建
  恢复边界以 `DotaMind_V3.2-5_design.md` 为准；Redis Server 重启的数据保留取决于
  部署时的 AOF/RDB 与持久卷。
- 2026-08-01 已用本机 Docker Redis 完成真实跨 Store 集成验收（`13 passed`）；启用 Redis
  的完整回归为 `459 passed, 1 warning`，未设置 Redis 环境变量的常规回归为
  `446 passed, 13 skipped, 1 warning`。

### V3.2-6：观测与故障边界（已完成）

- 以共用 Attempt/Run finalizer 和封闭 `StableFailureCode` 固定 terminal 语义。
- 补单进程 Prometheus `/metrics`、固定键值日志、公开 Trace 的工具/复用/recovery/failure 字段。
- 未捕获异常返回 500 `execution_error`，不写 Turn 或 completed replay；取消在提交前失败可接管，
  提交竞争后保持一个 completed Turn。
- `/debug/plan` 只显示公开 Trace/runtime/tool result，不暴露 Store 或幂等内部状态；业务工具仍冻结。
- Run/Attempt 指标移至 Runner 唯一终态边界；Store 的 `failed/completed/noop` 结果驱动幂等指标，
  Redis 提交后取消保持 `completed + 1 Turn`，提交前取消保持 `failed/takeover + 0 Turn`。
- 指标合同收敛为 13 组低基数单进程 collector；reused 保留原始耗时但不重复观察 duration。
- 2026-08-02 最终验收：无 Redis 环境变量 `460 passed, 14 skipped`，启用真实 Redis
  `474 passed`，真实 Redis 模块 `14 passed`；Ruff、lock 和 diff 检查均通过。

## 15. 测试与验收

### 15.1 单元测试

- RunBudget 每个计数器和 deadline 边界。
- Attempt reset 不清除 history、预算、缓存和累计 trace。
- Recovery classification 对每种终态的确定性映射。
- 工具指纹忽略 call id，但包含 resolved args 和 effective context。
- Prompt version/hash 稳定且不包含 secret。
- Turn/RequestRecord Redis JSON round-trip 和 schema version。

### 15.2 Graph 测试

1. 正常 plan 一次成功，只生成一个 Attempt。
2. 缺 evidence 且存在补证能力时触发一次 replan。
3. 第二次仍缺证时返回 `replan_exhausted`，不进入第三次 Controller。
4. 旧成功调用在新 attempt 中复用，不访问 handler 第二次。
5. 同工具同参数换 call id 返回 `execution_budget_error`。
6. Tool error、Answer error、invalid plan 和 capability boundary 不触发 replan。
7. 用户明确样本约束不被 recovery 放宽。
8. Stateful safe failure 仍只持久化脱敏 Turn。

### 15.3 并发与幂等测试

1. 同一 `(session_id, request_id)` 并发两次只运行一个 Graph。
2. 相同 key 不同 request hash 返回 conflict。
3. 已完成请求重放返回同一公开响应且不追加 Turn。
4. holder 被取消时 waiter 能安全接管。
5. 旧 fencing token 不能 append 或 complete。
6. 多 worker 竞争同一 session 时 turn index 唯一且单调。
7. Redis 重启后已提交 Turn 可恢复，in-progress lease 能按规则过期接管。

### 15.4 隐私回归

公开 API、trace、metrics、RequestRecord 和 AttemptRecord 中均不得出现：

- history sentinel；
- raw Controller output；
- Prompt 正文；
- retry/replan 原始消息；
- token 或 Authorization header；
- 未脱敏 validation 内容。

## 16. 完成定义

V3.2 完成必须同时满足：

- 业务工具目录没有因本阶段扩张。
- 单 attempt 请求与 V3.0 行为兼容。
- 可恢复的全局 missing-evidence gap 最多 replan 一次，并受总工具数和 deadline 限制；
  Critic quality gap 不在 V3.2-3 首版范围。
- 重复工具调用不会重复访问上游。
- `request_id` 重试不会重复执行或重复写 Turn。
- Redis backend 在多 worker 下保持 session 顺序、锁所有权和幂等。
- API 重启后 Redis 会话可继续；Redis 不可用不会静默分叉成 memory session。
- `/debug/plan` 能解释 run、attempt、budget、recovery 和最终结果。
- 所有敏感内部数据继续通过 allowlist 隔离。
- 完整测试、lint、lock check 和中英文每日进度快照通过。

## 17. 实施顺序总结

```text
Run/Attempt/Budget
  -> Prompt Registry
  -> Bounded Recovery/Replan
  -> Request Idempotency
  -> RedisSessionStore
  -> Observability + Fault Injection
  -> 解冻业务工具开发
```

V3.2 的核心不是增加更多 Agent，而是让现有 Controller、Tools、Evidence、Answer、
Critic 和 Session Store 在明确预算、失败边界和事务语义下组成可靠运行时。
