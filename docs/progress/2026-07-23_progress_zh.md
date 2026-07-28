# DotaMind 进度快照（2026-07-23）

## 10:01 — V3.2-3 Recovery/Replan 审查阻断项修复

### 修复内容

- Recovery 的可用追加容量现在取 `Run` 剩余 tool budget 与原始
  `plan.constraints.max_tool_calls - len(plan.tool_calls)` 的较小值；补齐全部缺口所需
  的 producer 数超过该容量时直接收口为
  `insufficient_evidence / replan_exhausted`，不消耗 Replan 或第二次 Controller 调用。
- RecoveryFeedback 的 `remaining_tool_budget` 使用上述有效容量，因此 Replan validator
  与实际可执行容量一致。
- Replan validator 现在要求每个 appended tool 至少声明一种
  `RecoveryFeedback.missing_evidence`；合法 producer 后夹带无关工具会被拒绝。
- Recovery 模式下通用 Controller 校验与 Replan 不变量校验同轮执行并合并反馈。
- 删除不可达的 `ToolErrorCode.duplicate_tool_call`；duplicate fingerprint 继续直接映射为
  `execution_budget_error`。

### 测试与文档

- 新增图级“原计划已达到 max_tool_calls”测试，确认单 Attempt
  `replan_exhausted` 且不消耗 Replan/第二次 Controller。
- 新增“合法 producer + 无关工具”拒绝测试，以及通用/Replan 错误合并测试。
- 同步 V3.2-3 设计文档中的容量与 appended tool 约束。
- 已验证：`uv run ruff check .` 通过；完整 `uv run pytest -q` 为
  `425 passed, 1 warning`。

### 提交边界

- `AGENTS.md` 仍是用户维护的独立修改，继续排除在 V3.2-3 提交之外。

## 10:07 — V3.2-3 文档收口与 V3.2-4 入口

### 阶段状态

- V3.2-3 已由提交 `9a8dfae` 完成收口；阶段蓝图状态由“已实现，待最终提交验收”
  更新为“已完成”。
- V3.2 总设计和设计索引现在明确标记 V3.2-3 已完成、V3.2-4 请求幂等为下一阶段。
- 当前尚无独立 V3.2-4 实施蓝图；进入实现前应先明确 InMemory `RequestRecord`、
  并发 single-flight、公开响应重放和单 Turn 提交的阶段边界。

### 验证与边界

- 本次只更新文档，未修改运行时代码，也未重复运行测试；沿用 V3.2-3 提交前已验证的
  `425 passed, 1 warning`、Ruff、lock 和 diff check 结果。
- 当前实现仍在 `run_init_node` 中固定 `request_id=None`，且没有 `RequestRecord`；
  V3.2-4 行为尚未实现。
- `AGENTS.md` 继续作为用户维护的独立修改，不纳入本次文档范围。

## 10:29 — V3.2-4 Stateful Request Idempotency

### 实现

- `POST /api/v1/plan` 增加可选 UUID v4 `request_id`；首版仅接受
  `(session_id, request_id)`，缺少 `session_id` 时返回 422。
- 新增 canonical request hash、`RequestRecord` 和 owner token；同 key 同 hash 重放
  allowlisted public response，不运行第二个 Graph、不追加第二个 Turn；不同 hash 返回
  HTTP 409 `idempotency_conflict`。
- `InMemorySessionStore` 在原有 per-session transaction 内新增 claim、failed takeover、
  TTL/容量清理，以及原子 `complete_request_with_turn`，使 Turn 与 completed record
  同步提交。
- `RunContext.request_id` 由内部 state 传递；request id 不进入 Prompt、history、
  AttemptRecord 或公开 trace。缓存命中不创建新 Run，保留首次 `runtime.run_id`。

### 测试与文档

- 新增顺序/并发重放、冲突、取消接管、TTL、容量、缓存深拷贝和 request-id 传播测试；
  同步更新 Route、Session privacy 和既有 PlanService 测试。
- 新增 V3.2-4 阶段蓝图，并同步总设计、设计索引、整体架构、技术架构和 API 文档。
- 已验证：`uv run ruff check .` 通过；完整 `uv run pytest -q` 为
  `436 passed, 1 warning`；`uv lock --locked` 与 `git diff --check` 通过。

### 明确边界

- 仅保证单进程 InMemorySessionStore 有效期内的 stateful 幂等；stateless、Redis、
  多 worker、lease/fencing、进程重启恢复和跨 Run 工具缓存继续留给 V3.2-5/6。
- 未捕获异常或 cancellation 不写 Turn，并允许同 hash 后续请求接管；上游已发生副作用
  时的跨进程 exactly-once 语义不在本阶段承诺范围。
