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
