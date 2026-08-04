# DotaMind 进度快照 — 2026-08-02

## 17:44 — V3.2-6 阻断修复与最终验收

### 已完成

- 固定共享 `StableFailureCode` 和未知值归一规则；内部 `NodeExecutionFailure` 只携带安全 state、
  node 与 failure stage，原始异常不进入 state、Trace、日志或指标。
- 将 Run/Attempt 观测移到 Runner 唯一终态边界：response 成功后才记录真实结果；节点、Graph、
  response 或 finalizer 未捕获异常统一为安全 HTTP 500 `execution_error`，不写 Turn、不缓存 completed。
- `fail_request()` 固定返回 `failed/completed/noop`；Memory/Redis 幂等指标由持久结果驱动。
  Redis Lua 已提交后的取消保持 `completed + 1 Turn`，提交前取消保持 `failed/takeover + 0 Turn`。
- Prometheus 收敛为 13 组既定低基数单进程指标，名称、labels 与 buckets 与 V3.2-6 合同一致；
  不保留旧指标别名，不启用 multiprocess mode。
- 键值日志改为固定 event/字段 allowlist，ID 只输出 8 位前缀；Controller、Tool、Recovery、
  Store、provider 与 transport 请求路径不记录异常正文、动态 URL 或上游响应。
- reused 工具结果保留首次真实调用的 `latency_ms`，工具 counter 记录 reused，但 duration Histogram
  和 handler/预算只记录真实 dispatch。
- `/debug/plan` 增加 HTTP/Run/最慢节点/失败摘要、Attempt 分组、Controller/Tools/Answer 耗时、
  工具复用、Recovery 和预算；500/503/409 无 runtime 时安全降级，不展示 Store 或幂等内部状态。
- 同步 `DotaMind_V3.2-6_design.md` 与 V3.2 总设计为已完成。

### 验收证据

- 无 Redis 环境变量完整回归：`460 passed, 14 skipped, 1 warning`。
- 启用本机真实 Redis 完整回归：`474 passed, 1 warning`。
- 真实 Redis 集成测试模块：`14 passed`。
- `uv run ruff check app tests`、`uv lock --locked`、`git diff --check` 均通过。
- `/metrics` 人工检查确认 13 组合同指标存在，且不包含 run/session/request/tool-call/player ID、
  query 等禁止字段。
- 本地浏览器真实执行 `/debug/plan`：HTTP 200，正确显示 Run duration、最慢节点、Attempt 分组、
  工具耗时与预算；完整 ID 已截断，浏览器控制台无 warning/error。

### 保持不变的边界

- 一个 app process 对应一个 Prometheus scrape target；不承诺单容器多 Uvicorn worker 自动聚合。
- 不增加 Run Store、事件总线、数据库、后台聚合、生产故障开关或新的业务工具。
- 取消审计仅存在于当前进程的脱敏日志、Trace 摘要与指标，不持久化完整 Run/Attempt。
