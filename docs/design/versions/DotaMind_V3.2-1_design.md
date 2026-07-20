# DotaMind V3.2-1 Run / Attempt / Budget 设计蓝图

> 状态：规范性设计与实现基线。
>
> 本文是 [DotaMind V3.2 Agent Runtime Foundation](./DotaMind_V3.2_design.md)
> 的第一阶段实施蓝图。它只建立单 attempt 运行时骨架，不提前实现 Prompt
> Registry、Recovery/Replan、请求幂等或 Redis。

更新日期：2026-07-20

## 1. 阶段定位

V3.2-0 已冻结业务工具目录，并为当前 Controller decision、Graph 分支、错误优先级、
Session 隐私和 Tool/Evidence contract 建立 characterization baseline。V3.2-1 在该
基线上引入请求级 Run、单次 Attempt 和全局 Budget 模型，使现有 V3.0 单次执行链
具备后续 Prompt 版本、有限 Replan、请求幂等和分布式持久化所需的稳定运行时边界。

本阶段不改变 constrained tool calling 的语义：

```text
intent             describes why
tool_calls         describe how
output_contract    describes response shape
required_evidence  describes proof obligations
```

Graph 仍只按 `decision.kind` 和运行状态路由，永不按 `intent` 路由。

## 2. 目标与非目标

### 2.1 目标

- 每次真实 Graph 执行拥有唯一 `run_id`、明确开始时间、deadline 和总耗时。
- 每个受控 Graph 终态形成且只形成一个 `AttemptRecord(attempt_index=0)`；未捕获异常、
  取消和进程退出由 V3.2-6 闭合。
- 用 `RunBudget` 统一记录 Controller、工具、Answer 和 Replan 消耗。
- Trace 具备 `run_id`、attempt、开始时间和节点耗时。
- 所有终态路径在公开序列化前完成 run 收口。
- `/debug/plan` 可以解释单 attempt、预算和耗时。
- 保持现有 status、reason、response type、错误优先级、会话持久化和隐私语义。

### 2.2 非目标

- 不增加 `attempt_finalize_node`、`recovery_node` 或 `attempt_reset_node`；它们属于
  V3.2-3。
- 不进行第二次 Controller 调用，不产生第二个 attempt。
- 不启用自动 Replan，不增加 recovery feedback。
- 不实现工具调用指纹、跨 attempt 结果复用或 duplicate-call 阻断。
- 不增加 API `request_id`；`RunContext.request_id` 本阶段固定为 `None`。
- 不拆分 Prompt，不计算正式 Prompt version/hash；`prompt_versions` 暂为空映射。
- 不实现 Redis、分布式锁、lease、fencing 或 RequestRecord。
- 不增加、删除或修改业务工具能力。
- 不增加新的顶层错误状态，也不把 deadline 超限转换为新公开错误。

## 3. V3.2-1 目标运行图

```text
START
  -> run_init_node
  -> controller_node
  -> decision_validate_node
      -> direct_answer -> conversation_answer_node -> run_finalize_node
      -> clarification -----------------------------> run_finalize_node
      -> context_missing ---------------------------> run_finalize_node
      -> capability_boundary -----------------------> run_finalize_node
      -> tool_plan
           -> validate_plan_node
           -> tool_executor_node
           -> evidence_node
           -> answer_node
           -> critic_node
           -> run_finalize_node
  -> response_node
  -> END
```

所有当前提前终止边必须由 `response_node` 改接到 `run_finalize_node`，再统一进入
`response_node`。本阶段没有返回 Controller 的循环边。

## 4. 运行时包结构

建议新增：

```text
app/agentic/runtime/
├── __init__.py
├── models.py       # RunContext / RunBudget / AttemptRecord 与摘要 DTO
├── clock.py        # UTC wall clock + monotonic duration，可注入测试时钟
├── reset.py        # attempt-local 平铺工作状态的集中纯函数 reset
└── summaries.py    # allowlist attempt/runtime 摘要与终态分类辅助函数
```

运行时模型不放入 `planning/`、`tools/` 或 `conversation/`，因为它们属于整个请求，
而不是某个业务层或某种决策。

## 5. 核心模型

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

约束：

- `run_id` 由 `run_init_node` 为每次真实执行生成 UUID v4。
- `started_at` 和 `deadline_at` 必须是 timezone-aware UTC 时间。
- `deadline_at` 只在初始化时计算一次，后续 attempt 不得重置。
- `session_id` 由 `PlanService` 注入内部 state，stateless 请求为 `None`。
- `request_id` 本阶段为 `None`，V3.2-4 才接入 API。
- `prompt_versions` 本阶段为 `{}`，V3.2-2 负责填入稳定版本和 hash。
- 不允许直接把完整 `RunContext` 序列化到公开 API。

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

计数口径：

- `controller_calls_used` 记录 Graph 级 Controller 调用。本阶段正常值为 `1`；
  Controller 内部 JSON/schema validation retry 不计为 Replan。
- `tool_calls_used` 只记录真正进入注册 handler 的调用。reference resolution 失败没有
  访问 handler，不增加该计数。
- `answer_calls_used` 只记录 `answer_node` 调用 Answer synthesizer；确定性 conversation
  answer 不增加该计数。
- `replans_used` 本阶段始终为 `0`。
- 工具计数是整个 run 的累计值，不按 attempt 重置。

V3.2-1 实现计数、剩余预算和 deadline 判断的确定性模型测试，但不增加新的预算路由。
`execution_budget_error`、`execution_timeout` 和 duplicate-call 阻断统一在 V3.2-3
接入 Graph，避免本阶段改变 V3.0 外部行为。

`deadline_at` 只用于审计展示。是否超限必须以 `monotonic elapsed` 与
`max_elapsed_seconds` 比较，不能以墙钟读取结果判断。本阶段即使记录到预算用尽或
deadline exceeded 也不阻止节点；`execution_timeout` 延后到 V3.2-3。

#### 5.2.1 Tool dispatch 非公开数据通道

`ToolExecutor.execute()` 返回 `(ToolResult, ToolDispatchRecord)`，并接受同步
`on_handler_entered` callback。顺序固定为 registry lookup、input validation、callback、
handler。registry/input validation 失败不计数；callback 在 handler 函数调用前执行，
所以 handler 同步抛错或异步失败都计一次。reference resolution 位于 node 层，由 node
同时构造既有失败 `ToolResult` 和内部 reference dispatch record。

```python
ToolDispatchStage = Literal["reference_resolution", "pre_dispatch", "handler"]
ToolErrorCode = Literal[
    "reference_resolution_error",
    "tool_not_registered",
    "input_validation_error",
    "handler_error",
]
```

`ToolDispatchRecord` 只进入平铺 state 和内部 Attempt 摘要，不进入顶层
`tool_results`、EvidenceGraph 或公开 API；禁止把 stage/error code 写入
`ToolResult.metadata`。因此 executor 的内部观测增强不得改变既有 `ToolResult` JSON。

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
    started_at: datetime
    duration_ms: int
```

本阶段：

- `attempt_index` 固定为 `0`。
- V3.2-1 不定义 `recovery_reason`、`recovery_code` 或任何其他恢复字段；V3.2-3
  再引入固定 `RecoveryCode`。
- `AttemptPlanSummary` 仅保留 `output_contract`、tool call 数量和 effective required
  evidence，不保留 intent、goal、args、context 或 metadata。
- `AttemptToolCallSummary` 仅保留 call id、工具名、status、latency、
  `handler_entered`、稳定 dispatch stage/error code，不保留 `ToolResult` payload。
- `AttemptEvidenceSummary` 只保留 required/present/missing kinds、completeness、
  mock_used 和 evidence count 等受控字段。
- `AttemptCriticSummary` 只保留 passed、severity 和 issue count；不得复制可能包含
  tool error 的完整自由文本 reasons。
- `AttemptAnswerSummary` 仅保留 answer type、status 和 `confidence: float | None`；
  不保存任何回答正文，social/recall 的 confidence 为 `None`。

`AttemptRecord` 不得保存：

- raw Controller output 或 raw content；
- Prompt messages 或完整 conversation history；
- validation retry/replan 原始反馈；
- 完整 `ExecutionPlan`、完整 `ToolResult`、回答文本和 Critic reasons；
- Authorization header、token、带敏感 query string 的 URL；
- 未脱敏 exception 或 validation echo。

### 5.4 AgentRunState 调整

在保留全部当前 attempt 工作字段的基础上增加：

```text
internal_session_id
run_context
run_budget
attempt_index = 0
attempt_started_at
run_started_monotonic
attempt_started_monotonic
attempts[]
attempt_failure_stage
tool_dispatch_records
terminal_stage
run_duration_ms
```

`internal_session_id` 只用于 `run_init_node` 构造 `RunContext`；继续依赖 response
allowlist 阻止其进入客户端响应。不要把 `session_memory_enabled` 改成路由键。

#### 5.4.1 长期状态选择：平铺 state + 集中 reset

这是 V3.2 的规范性长期选择，不是 V3.2-1 的临时过渡：

- 原始 attempt 工作字段永久平铺在 `AgentRunState`；不引入 `InternalAttemptState`、
  `current_attempt`、代理属性或双写路径。
- `AttemptRecord` 永远是脱敏审计摘要，不作为当前执行工作区。
- attempt-local 字段只能通过纯函数 `reset_attempt_working_state()` 集中清理。
- V3.2-1 实现并测试该函数，但不把 reset 接入 Graph，不增加
  `attempt_reset_node` 或第二个 attempt；V3.2-3 的节点只调用该函数。

```python
reset_attempt_working_state(
    state,
    *,
    next_attempt_index: int,
    started_at: datetime,
    started_monotonic: float,
) -> AgentRunState
```

该函数使用浅层 state copy，并对保留的可变字段显式 deep copy，避免先复制即将被
丢弃的大型 `ToolResult.data`。它清除 Controller/decision/plan、evidence obligation、
tool result/dispatch、evidence、answer、review、validation/safe-failure、
status/reason/errors/response，以及已经封存的 `terminal_stage`/`run_duration_ms` 等全部
attempt-local 或 finalize 派生状态；保留 query/game、history、
session 属性、RunContext、RunBudget 累计值、attempts、trace 和 run monotonic 起点。
返回 state 的 budget/history/attempts/trace 与输入对象不得共享可变容器。

本阶段不增加：

```text
recovery_feedback
executed_call_fingerprints
reused_tool_result_ids
```

## 6. 时间与 Trace

### 6.1 Clock

运行时使用两个时间来源：

- timezone-aware UTC wall clock：生成 `started_at`、`deadline_at` 和 trace 时间。
- monotonic clock：计算 node、attempt 和 run 的 `duration_ms`。

Clock 必须可注入，测试不得依赖 `sleep` 或机器墙钟精度。

### 6.2 AgentTraceEvent

```python
class AgentTraceEvent(BaseModel):
    run_id: UUID
    attempt_index: int
    node: str
    action: str
    status: Literal["planned", "completed", "failed"]
    started_at: datetime
    duration_ms: int
```

要求：

- 每个节点严格保留 `planned -> completed/failed` 两事件顺序，不增加第三条 span。
- `planned.duration_ms=0`；completed/failed 使用 monotonic node elapsed。
- `run_init`、`run_finalize` 进入 trace；`response_node` 不新增 trace。
- 新字段为 additive metadata，不把 query、answer、history、Prompt 或完整 session id
  放入 trace。
- `duration_ms` 必须非负。
- 本阶段所有事件 `attempt_index=0`，且 `run_id` 与 RunContext 一致。

Graph runner 可以使用统一 node wrapper 记录时延，避免每个业务 node 重复实现计时。

## 7. Run 初始化与收口

### 7.1 run_init_node

职责：

1. 从 runtime policy 创建 `RunBudget`。
2. 创建 `RunContext` 和全局 deadline。
3. 初始化 `attempt_index=0`、attempt 开始时间和累计 trace。
4. 拒绝覆盖已经存在的 RunContext，避免一个真实执行产生多个 run identity。

它不调用 LLM、工具、Evidence、Answer 或 Critic。

### 7.2 终态解析

V3.2-1 之前的 `response_node` 同时承担终态优先级和公开序列化。本阶段已把终态计算
抽成可复用的确定性函数：

```text
resolve_terminal_outcome(state)
  -> status
  -> response_type
  -> stable reason
  -> terminal_stage / failure_stage
```

优先级保持为：

```text
planning_error
  > decision_validation_error
  > tool_error
  > answer_error
  > insufficient_evidence from missing evidence
  > insufficient_evidence from critic quality failure
  > success
```

`response_node` 现在只负责应用公开 allowlist 和最终 schema 序列化，不重新解释
或覆盖已经收口的终态。

`response_node` 收到未 finalize 的 state 必须 fail-fast，不能保留旧终态兼容分支。原来
直接调用 `response_node()` 测试错误优先级的 characterization tests 迁移到
`resolve_terminal_outcome()` 或 `run_finalize_node`；保留原场景和断言语义，不保留旧函数职责。

#### 7.2.1 完整终态类型与映射

`AttemptStatus` 复用 `AgentRunStatus`，不创建第二套状态词汇：

```python
AgentRunStatus = Literal[
    "ok", "clarification_required", "insufficient_context", "insufficient_tools",
    "insufficient_evidence", "error",
]
AttemptStatus = AgentRunStatus
```

`TerminalStage` 与 `FailureStage` 是两个独立类型，即使目前取值集合相同。
`terminal_stage` 表示 attempt 最终归约到的运行阶段，始终必有；`failure_stage` 只表示
导致失败或 insufficient evidence 的阶段，正常成功和需要用户输入的受控结果为 `None`。

`resolve_terminal_outcome(state)` 必须一次返回 public status、response type、stable
reason、attempt status、terminal stage 和 failure stage；本阶段 attempt status 始终等于
public status。

| 场景 | public status | response type | attempt status | terminal stage | failure stage |
|---|---|---|---|---|---|
| social / validated recall | `ok` | `direct_answer` | `ok` | `conversation_answer` | `null` |
| clarification | `clarification_required` | `clarification` | `clarification_required` | `decision_validation` | `null` |
| context missing | `insufficient_context` | `conversation_context_missing` | `insufficient_context` | `decision_validation` | `null` |
| capability boundary | `insufficient_tools` | `capability_boundary` | `insufficient_tools` | `decision_validation` | `null` |
| tool-plan 成功 | `ok` | 最终 output contract | `ok` | `critic` | `null` |
| Controller transport/model error | `error` | `planning_error` | `error` | `controller` | `controller` |
| Controller validation retries 耗尽 | `error` | `decision_validation_error` | `error` | `controller` | `decision_validation` |
| Graph decision validation 失败 | `error` | `decision_validation_error` | `error` | `decision_validation` | `decision_validation` |
| plan validation 失败 | `error` | `decision_validation_error` | `error` | `plan_validation` | `plan_validation` |
| conversation answer 内部不变量失败 | `error` | `decision_validation_error` | `error` | `conversation_answer` | `conversation_answer` |
| reference/tool/pre-dispatch/handler error | `error` | `tool_error` | `error` | `tool_execution` | `tool_execution` |
| Answer error | `error` | `answer_error` | `error` | `answer` | `answer` |
| missing effective evidence | `insufficient_evidence` | `insufficient_evidence` | `insufficient_evidence` | `evidence` | `evidence` |
| Critic quality failure | `insufficient_evidence` | `insufficient_evidence` | `insufficient_evidence` | `critic` | `critic` |
| 未分类受控错误 | `error` | `execution_error` | `error` | `execution` | `execution` |

### 7.3 run_finalize_node

V3.2-1 尚无 `attempt_finalize_node`。为满足单 attempt 可审计要求，
`run_finalize_node` 调用纯函数 `build_attempt_record(state)` 生成 attempt 0，然后：

1. 确定终态和 failure stage。
2. 追加且只追加一个 AttemptRecord。
3. 计算 attempt/run duration。
4. 写入 `terminal_stage`。
5. 验证预算计数非负且未被隐式重置。

V3.2-3 引入 `attempt_finalize_node` 后，将复用同一个 `build_attempt_record()`：

- `attempt_finalize_node` 负责每次 attempt 追加记录；
- `run_finalize_node` 只封存整个 run 的最终总量；
- 不复制两套 AttemptRecord 构建逻辑。

## 8. 公开响应与 Debug UI

### 8.1 Public Runtime DTO

不公开原始 `RunContext`、`RunBudget` 或完整 `AttemptRecord`。`PlanResponse` 增加一个
必有的严格嵌套 `runtime` allowlist；所有受控 Graph 响应均返回它：

```text
runtime
├── run_id
├── duration_ms
├── terminal_stage
├── budget
│   ├── limits
│   └── used
└── attempts[]
    ├── attempt_index
    ├── decision_kind
    ├── status
    ├── failure_stage
    ├── duration_ms
    ├── tool_call_statuses
    ├── evidence_summary
    ├── answer_summary
    └── critic_summary
```

`runtime` 是 additive debug/audit metadata。既有顶层 `plan`、`tool_results`、
`evidence_graph`、`answer` 和 `review` 在本阶段保持不变。

公开 runtime 明确禁止包含：

- session id、request id 或 history；
- plan args、ToolResult data、answer 正文；
- 内部 handler_entered、dispatch stage/error code；
- raw Controller/Prompt/validation 内容；
- secret、Authorization header 或完整敏感 URL。

Stateful safe failure 继续清除公开 trace 和业务细节，但仍返回 runtime；attempt 只保留
index、status、failure stage 和 duration，decision kind 为空，tool/evidence/answer/critic
均为空。

### 8.2 `/debug/plan`

增加：

- Run ID、总耗时和 terminal stage；
- Budget limits/used；
- 单 attempt 卡片；
- Trace 的 attempt index 和 duration。

禁止显示 raw Prompt、raw Controller output 和完整 history。

## 9. 配置

`policy.yaml` 增加：

```yaml
planning:
  runtime:
    max_replans: 1
    max_tool_calls_total: 8
    max_controller_calls: 2
    max_answer_calls: 2
    max_elapsed_seconds: 60
  sample_policy:
    # existing entries unchanged
```

要求：

- 所有值由严格 Pydantic model 在启动时 fail-fast 校验。
- `max_replans` 本阶段只允许 `1`。
- secret、Redis URL 和部署开关不得进入 `policy.yaml`。
- 不修改任何当前业务工具的 sample policy。

## 10. 分工作包实施

### V3.2-1A：Models / Clock / Config

- 新增 runtime package 和模型。
- 新增 runtime policy。
- 完成 UUID、UTC、deadline、预算边界和摘要 allowlist 单元测试。
- 不接入 Graph，不改变 API。

### V3.2-1B：Single-Attempt Graph Integration

- 新增 `run_init_node`、`run_finalize_node`。
- 扩展 AgentRunState 和 Trace。
- 抽离终态解析，所有路径统一经过 run finalize。
- 接入 Controller/tool/answer 预算计数。
- 验证每种终态恰好生成一个 attempt。

### V3.2-1C：Public Runtime Summary / Debug UI

- 增加严格公开 runtime DTO。
- `/debug/plan` 展示 run、attempt、budget 和 duration。
- 补 API schema、safe failure 和隐私回归。
- 更新 architecture、node inventory 和进度快照。

## 11. 预计影响文件

新增：

```text
apps/api/app/agentic/runtime/*
apps/api/app/agentic/nodes/run_init.py
apps/api/app/agentic/nodes/run_finalize.py
apps/api/tests/test_agentic_runtime.py
```

修改：

```text
apps/api/app/agentic/state.py
apps/api/app/agentic/graph.py
apps/api/app/agentic/nodes/response.py
apps/api/app/agentic/nodes/controller.py
apps/api/app/agentic/nodes/tools.py
apps/api/app/agentic/nodes/answer.py
apps/api/app/application/plan_service.py
apps/api/app/api/v1/schemas.py
apps/api/app/api/v1/mappers.py
apps/api/app/resources/plan_console.html
apps/api/app/core/config.py
apps/api/app/config/policy.yaml
apps/api/tests/test_agentic_graph.py
apps/api/tests/test_agentic_nodes.py
apps/api/tests/test_config.py
apps/api/tests/test_plan_route.py
apps/api/tests/test_plan_console.py
apps/api/tests/test_plan_service.py
apps/api/tests/test_session_privacy.py
```

实际实现时如果文件不需要修改，不应为匹配清单制造无意义 diff。

## 12. 测试矩阵

### 12.1 Runtime 单元测试

- 每次初始化产生 UUID v4 run id。
- wall-clock 时间为 aware UTC，deadline 只计算一次。
- 每个预算计数器、剩余值和越界判断确定。
- `max_replans != 1` 配置启动失败。
- duration 使用 monotonic clock 且始终非负。
- Attempt/Public Runtime 摘要不包含禁止字段。

### 12.2 Graph 回归

以下每条路径都必须恰好形成一个 Attempt：

1. direct social answer；
2. 三种 validated recall；
3. clarification；
4. context missing；
5. capability boundary；
6. tool plan success；
7. Controller transport/model error；
8. decision/plan validation error；
9. reference resolution/tool error；
10. Answer error；
11. missing effective evidence；
12. Critic quality failure。

同时验证：

- 没有第二次 Controller 调用或第二个 attempt。
- 原 status、reason、response type 和错误优先级不变。
- direct answer 不进入 tool/evidence/critic。
- tool error 不被改写为 missing evidence。
- Answer error 不被改写为 Critic failure。

### 12.3 预算与 Trace

- 所有 trace 事件使用同一 run id 和 attempt 0。
- Controller Graph 调用计数为 1。
- direct answer 的 tool/answer 计数为 0。
- tool plan 的工具计数等于真正 dispatch 的 handler 数量。
- reference resolution failure 不增加 handler 调用计数。
- natural/structured Answer 调用计数符合实际 synthesizer 调用。

### 12.4 API、Debug 与隐私

- `runtime` schema 稳定且仅含 allowlist 字段。
- `/debug/plan` 能渲染单 attempt 和预算。
- history sentinel 不出现在 runtime、trace 或公开 attempt summary。
- raw Controller output、Prompt、retry content、session id 和 secret 不出现在公开输出。
- stateful safe failure 继续只持久化脱敏 Turn。

## 13. 完成定义

V3.2-1 完成必须同时满足：

- 每次请求都有唯一 RunContext 和恰好一个 AttemptRecord。
- “每次请求恰好一个 Attempt”限定为所有受控 Graph 终态；未捕获异常、取消和进程退出
  由 V3.2-6 处理。
- Graph 只有一次执行，没有 recovery/replan edge。
- RunBudget 和 Trace 记录实际单 attempt 消耗与时延。
- 所有现有顶层状态、错误优先级和响应语义保持不变。
- `/debug/plan` 能解释 run、attempt、budget 和 duration。
- Tool Registry 冻结测试保持精确通过。
- Session/history/Prompt/Controller 原始内容不跨公开边界。
- API 完整测试、V3.2-0 characterization、ruff、lock check 和 diff check 通过。
- technical architecture、node inventory 和中英文当日进度快照同步。

## 14. 下一阶段边界

V3.2-1 完成后进入 V3.2-2 Prompt Registry。V3.2-2 只拆 Prompt、区分 validation
retry 与 recovery rules，并向 `RunContext.prompt_versions` 写入稳定版本/hash。

只有 V3.2-2 完成后，V3.2-3 才引入：

```text
attempt_finalize_node
  -> recovery_node
      -> terminal -> run_finalize_node
      -> replan   -> attempt_reset_node -> controller_node
```

V3.2-3 必须复用本阶段的 RunContext、RunBudget、AttemptRecord、Trace、终态分类和
公开 runtime DTO，不得另建第二套运行时模型。
