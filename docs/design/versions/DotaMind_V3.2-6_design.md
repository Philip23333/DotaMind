# DotaMind V3.2-6 Runtime Observability 与故障边界设计

> 状态：已完成并通过验收（2026-08-02）。业务工具目录保持冻结至本阶段验收结束。

## 1. 目标与非目标

本阶段闭合 Agent Runtime Foundation 的运行期边界：可观测、可分类的受控失败、不可缓存的
未捕获异常，以及取消与 Redis 原子提交的竞态。它不增加工具、Prompt、意图分支、重试策略或
新的存储后端。

`intent` 仍只描述用户目标；执行只由经过校验的 `tool_calls` 决定。

## 2. 终态与错误矩阵

| 事件 | HTTP / 响应 | Turn / RequestRecord | 后续同 request ID |
|---|---|---|---|
| 已受控的 Controller、校验、工具、证据、Answer、预算失败 | 200，safe 或受限公开响应 | 一个完整 safe Turn；completed | replay |
| Redis unavailable / lock timeout / lock lost | 503 `session_store_error` | 不承诺完成 | 按 Store 状态重试 |
| request_id 输入冲突 | 409 `idempotency_conflict` | 不写新 Turn | 保持冲突 |
| Graph 未捕获异常 | 500 `execution_error` | 不写 Turn；in-progress 改 failed | 可重新执行 |
| Graph/提交前取消 | 调用方收到取消 | failed/takeover + 0 Turn | 可接管并重试 |
| `complete_request_with_turn` Lua 已提交后取消 | 调用方收到取消 | completed + 1 完整 Turn | replay |

`complete_request_with_turn` 是 Turn 与 completed RequestRecord 的唯一提交点。失败清理只会将
当前 owner 的 in-progress record 标成 failed；若 Lua 已完成或 owner 已变化，它是无副作用的
no-op，不能回滚新 owner 或已完成记录。

## 3. 收口模型

`runtime.finalization` 提供 `finalize_attempt()` 和 `finalize_run()`；两者共享
`resolve_terminal_outcome()`，不允许第二套 terminal resolver。`AttemptRecord` 固定保留
`failure_stage`、封闭的 `StableFailureCode` 与 recovery code。

图节点包装器只捕获 `Exception`，绝不吞掉 `CancelledError`。非取消异常转换为只携带安全
state、node 和 failure stage 的内部 `NodeExecutionFailure`；Runner 在最外层只记录一次真实
Run 终态，再抛出 `AgentExecutionError`。API 将它和路由内剩余普通异常统一映射为固定 500
envelope。该路径不会生成 Response，因此不会持久化 Turn 或 replay payload。

Run 正常指标只在 `response_node` 完成后记录；response、attempt finalize 或 run finalize 失败
均不能提前计为 completed。取消只记录一次 cancelled Run，并继续传播原始 `CancelledError`。

`fail_request()` 返回 `failed/completed/noop` 三种内部结果，幂等指标以 Store 的持久结果为准。
Redis complete 在等待 Lua 返回时被取消，会在同一 task 中 best-effort 重读 RequestRecord：若
已经 completed，只记录 executed；否则依赖 failed cleanup 或 lease takeover，不虚报执行成功。

## 4. 公开 Trace、日志与指标

Trace 只允许 run/attempt/node、固定 action/status、duration、工具名/call id、复用、recovery
code 和稳定 failure code。它不含 Prompt、history、token、原始异常或上游 response body。

日志采用固定 `event=... key=value` 字段；Controller、LLM、Answer 和 HTTP transport 不记录
原始异常或上游内容。工具内部仍可保留诊断错误给控制流使用，但 API response 对错误工具统一
输出 `tool execution failed`。

使用 `prometheus-client` 的进程内 collector，`GET /metrics` 为内部 scrape endpoint。部署约束：
**一个进程对应一个 scrape target**；不使用 multiprocess collector。固定暴露 run、run duration、
attempt、controller、tool、tool duration、evidence completeness、critic、recovery、budget、
session-store、lock wait 和 idempotency 共 13 组指标。标签仅使用固定 status、stage、failure code、
tool、backend、operation 和 outcome，禁止 ID、用户文本、异常文本、Prompt、history 与 token。

键值日志的 event 和字段均使用 allowlist；未知 event/字段直接拒绝，failure code 先规范化，ID
统一截为 8 位前缀。reused 工具保留第一次真实 dispatch 的耗时，但不重复观察 duration Histogram。

`/debug/plan` 只渲染公开 response 中已有的 Trace、runtime 和 tool results；展示 HTTP 状态、Run
总耗时、最慢节点、Attempt 分组、Controller/Tools/Answer 耗时、reused、Recovery、预算及固定失败码。
它不展示 Store backend、request record、owner/fencing token 或当前幂等状态；500/503/409 无
runtime 时只显示安全错误摘要。

## 5. 验收

- 未捕获异常不能成为 completed replay；修复后同 request ID 只写一个 Turn。
- 取消不会保留不可接管的 in-progress record；提交竞态只允许 0 或 1 个完整 Turn。
- Redis fencing/lease 继续拒绝旧 owner 的迟到 append/complete/fail。
- `/metrics` 和日志不产生高基数或敏感字段。
- 2026-08-02 验收结果：无 Redis 环境变量 `460 passed, 14 skipped`；启用真实 Redis
  `474 passed`；真实 Redis 模块 `14 passed`；Ruff、`uv lock --locked`、`git diff --check` 通过。
- 本地浏览器真实请求验证 `/debug/plan` 的 Summary、Attempt 分组、耗时、工具表和预算正常展示，
  浏览器控制台无 warning/error。
