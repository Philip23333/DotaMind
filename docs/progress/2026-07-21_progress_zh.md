# 2026-07-21 进度快照

## 20:30 — V3.2-2 Prompt Registry

- 完成 `agentic/prompts` 轻量模块：Controller Prompt bundle、用户消息渲染、validation retry
  feedback、dormant recovery rules 与组件版本/哈希。
- `AgentController` 在缓存 Prompt 前封存 ToolRegistry；冻结后的注册稳定失败，确保 Prompt、
  validation 与 executor 共享同一 catalog。
- `controller_node` 在 LLM 调用前把 configured/prepared Prompt manifest 写入 RunContext；
  disabled 路径同样保留审计信息。hash 不代表请求已发送或成功。
- 删除无调用的 `ContractSpec.prompt_example` 和生产 `controller_payload()`，并移除
  `planning/__init__.py` eager re-export 以避免循环导入。
- 新增 UTF-8/LF/no-BOM golden Prompt fixture、enabled/disabled 审计、冻结、hash 变化、
  dormant recovery 与 fresh-import 回归测试；更新 V3.2-2、架构和技术文档。
- 验证：`ruff check .`、`pytest`（399 passed, 1 warning）、`uv lock --locked` 和
  `git diff --check` 通过；仅有既有 LF/CRLF 转换提示。

### 保持不变

- 未接线 Recovery/Replan、第二 Attempt、Graph 边、预算 gate、公开 API 或持久化存储。
- 既有 `AgentControllerResult` 原始诊断字段仍是 attempt-local 瞬态数据，不进入 manifest、
  AttemptRecord、公开 DTO、trace、Session 或持久化边界。

## 21:15 — 合并前阻断项修复

- `ToolRegistry.freeze()` 现在深度封存 ToolDefinition 的 `arg_contracts`、`output_paths` 和
  `metadata`；Controller 同时持有只读 Contract Registry 与 Sample Policy 快照。
- 真实 `AgentController` 与 `AgentGraphRunner` 必须共享同一 Registry；不一致在构造期失败。
  注入真实 Controller 的 PlanService 复用其已封存 Registry。
- manifest 新增仅覆盖 `history_window` 与 `history_max_chars` 的
  `controller.history_policy.sha256`，不包含 query、history 或 Session 正文。
- 固定 validation retry 与 dormant recovery rules 的语义断言和版本断言；补充深度冻结、
  registry 一致性与 history-policy 审计测试。
- 同步设计入口、AGENTS、整体架构与技术架构；`prompt_versions` 已标注为
  configured/prepared manifest。
- 验证：`ruff check .`、`pytest`（399 passed, 1 warning）、`uv lock --locked` 和
  `git diff --check` 通过。`git diff --check` 仅输出既有 LF/CRLF 转换提示。
