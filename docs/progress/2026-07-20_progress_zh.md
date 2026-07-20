# DotaMind 进度快照：2026-07-20

## 12:54 — V3.2-1 Run / Attempt / Budget 实现收口

- 将 V3.2 的长期状态边界固定为“平铺 `AgentRunState` + 集中
  `reset_attempt_working_state()`”：未引入 `InternalAttemptState`、
  `current_attempt`、代理属性、双写路径或第二个 attempt。reset 返回独立新 state，
  集中清除 attempt-local 工作字段，并深复制保留的 budget/history/attempts/trace。
- 新增严格 runtime 模型、`SystemClock`/`FakeClock`、UUID4/UTC `RunContext`、全局
  `RunBudget`、独立 `TerminalStage`/`FailureStage`、纯终态归约和脱敏
  `AttemptRecord` 摘要。Attempt 不保存完整 plan/result、回答文本、Critic reasons、
  原始异常或 recovery 字段。
- `ToolExecutor.execute()` 改为返回原 `ToolResult` 与非公开 `ToolDispatchRecord`；
  registry/reference/input validation 不计工具预算，handler 入口前同步计数，因此成功
  和 handler 异常均精确计一次。内部 dispatch 数据不写入公开 ToolResult metadata。
- Graph 已接入 `run_init -> 单 attempt 执行链 -> run_finalize -> response`；所有受控
  终态在序列化前归约且恰好生成一条 AttemptRecord。缺失 effective evidence 在 Answer
  前终止；deadline 使用 monotonic elapsed 观测，本阶段不执行预算/超时门禁。
- Trace 保留每节点 `planned -> completed/failed` 两事件顺序，增加 run/attempt/UTC/
  duration；`run_init` 和 `run_finalize` 进入 trace，response 不新增事件。Controller、
  handler 和 Answer 预算按真实入口计数，Replan 始终为 0。
- `/api/v1/plan` 的 `runtime` 现在为必有严格 DTO，公开 Run、Budget 和脱敏单 Attempt；
  stateful safe failure 也返回最小 runtime。既有顶层 plan/tool results/evidence/answer/
  review schema 保持，`/debug/plan` 增加 Run/Attempt/Budget 和计时 trace 展示。
- 同步修订 V3.2-1、V3.2 总体设计、node inventory、technical architecture 和 API
  文档，明确 Attempt 隐私、完整终态表、dispatch 私有通道、monotonic deadline、
  response 职责迁移及 V3.2-6 未捕获异常/取消边界。

### 验证

- V3.2-0 characterization baseline：`87 passed, 1 warning`，原场景与断言覆盖数量保持。
- API 完整测试：`381 passed, 1 warning`。warning 为 FastAPI/Starlette 上游
  `httpx` 弃用提示。
- `uv run ruff check .` 通过。
- `uv lock --check` 通过。
- `git diff --check` 通过；仅输出仓库既有的 LF/CRLF 转换提示。
- Tool Registry 精确冻结集合测试包含在上述通过结果中；未运行真实 DeepSeek/STRATZ
  网络请求，也未固定易变 STRATZ 数值。

## 13:11 — 整体架构与分层图示整理

- 新增 `docs/design/architecture/整体架构.md`，以当前已实现的 V3.2-1 工作树为准，
  汇总端到端请求架构、单 Attempt Graph、受约束 Tool Calling、Evidence 义务、
  Run/Attempt/Budget、Session、终态公开边界和 V3.2-2 至 V3.2-6 后续能力。
- 在 `Controller层.md`、`Tool层.md`、`Evidence层.md` 和 `Answer+Critic层.md` 中分别
  增加会话注入、工具执行、证据义务及终态收口 Mermaid 图，并从 node inventory
  链接到新的整体架构入口。
- 同步修正分层文档中的旧运行事实：tool error 现在直接进入 `run_finalize_node`，
  missing effective evidence 在 Answer 前收口，ToolExecutor 使用非公开
  `ToolDispatchRecord`，response 只序列化已经归约的终态和必有 runtime。
- 更新 `docs/design/README.md`，将 `整体架构.md` 列为 architecture 文档的统一入口。

### 验证

- 本次修改涉及的 design 文档本地 Markdown 链接检查通过。
- `git diff --check` 通过；仅输出仓库既有的 LF/CRLF 转换提示。
- 本次为文档整理，没有修改运行代码，因此未重复运行 API 测试或真实
  DeepSeek/STRATZ 请求。

## 13:24 — V3.2-1 终态与审计契约审查修复

- 修复 Evidence 缺少 plan 时只写失败 trace、却仍归约为成功的问题；该内部不变量
  失败现在写入稳定 error，最终返回 `error/execution_error`，terminal stage 为
  `execution`，不再产生 `ok/raw_tool_results`。
- Answer 返回 `error` 或 `insufficient_evidence` 后直接进入 `run_finalize_node`，不再
  执行 Critic；失败 Answer 的 trace 以 `failed` 收口，Attempt 不再产生误导性的
  Critic summary。
- 将 `AgentTraceEvent.status` 收紧为 `planned | completed | failed`。Critic pass/warning
  映射为 `completed`，Critic failed 映射为 `failed`；severity 只保留在 action 和
  Critic summary 中，不再混入 trace 生命周期字段。
- `reset_attempt_working_state()` 现在同时清除旧的 `terminal_stage` 和
  `run_duration_ms`，防止未来 V3.2-3 的下一 Attempt 继承已封存终态。
- 删除 reference resolution 失败 `ToolResult.metadata.stage`；dispatch stage/error code
  只保留在内部 `ToolDispatchRecord`。同步更新 Graph/runtime 回归、分层图和 V3.2-1
  规范描述。

### 验证

- 审查问题定向测试：`49 passed`。
- V3.2-0 characterization baseline：`87 passed, 1 warning`，原数量保持。
- API 完整测试：`387 passed, 1 warning`。warning 为 FastAPI/Starlette 上游
  `httpx` 弃用提示。
- `uv run ruff check .`、`uv lock --check` 和 `git diff --check` 通过；diff check
  仅输出仓库既有的 LF/CRLF 转换提示。
- 未运行真实 DeepSeek/STRATZ 网络请求，也未固定易变 STRATZ 数值。
