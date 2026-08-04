# DotaMind 进度快照（2026-08-01）

## 22:48 — V3.2-5 完成修正与最终验收

### 修正

- Redis append/complete Lua 脚本改为只替换 canonical JSON 末尾的顶层
  `turn_index`，不再误改 `context_scope` 等嵌套同名字段。
- 新增真实 Redis 验收：嵌套字段数据完整性、failed takeover、同 Session 串行化、
  不同 Session 并发，以及 lease 过期后旧 owner 的 renew/release/append/complete/fail
  拒绝。
- 同步 `AGENTS.md`、V3.2 总设计、V3.2-5 设计和设计入口文档；V3.2-5 后续阶段为
  V3.2-6 观测与故障注入。

### 验证

- 设置 `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15` 的完整 pytest：
  `459 passed, 1 warning`。
- 未设置 Redis 环境变量的常规 pytest：`446 passed, 13 skipped, 1 warning`；
  skipped 全部为真实 Redis 集成测试。
- `uv run ruff check app tests`、`uv lock --locked` 和 `git diff --check` 均通过。

### 当前状态

- V3.2-5 的功能实现和真实 Redis 验收已完成，Redis Server 重启后的数据保留仍取决于
  AOF/RDB、fsync/save 策略和持久卷。
- 本次 V3.2-5 修改仍在工作树中，尚未提交；提交前应继续检查完整 diff。

## 23:54 — 整体架构 SessionStore 状态修正

### 文档修正

- 修正 `docs/design/architecture/整体架构.md` 中仍把当前后端描述为仅
  `InMemorySessionStore`、把 Redis 和 request 幂等列为后续阶段的陈旧内容。
- 总体图和 Session sequence 现在统一标注 `SessionStore: memory / Redis`，并补充
  V3.2-5 已实现的多 worker lease、续租、fencing、原子提交与重建恢复边界。
- 明确 Redis Server 重启后的数据保留仍依赖 AOF/RDB、fsync/save 策略和持久卷。

### 验证与边界

- 本次只修正文档，没有修改运行时代码，也未重复运行测试；执行 `git diff --check`
  验证文档 diff。
- V3.2-5 已在本次修正前提交为 `e67ee03`；当前未提交内容仅为本节记录的架构和
  中英文进度文档修正。

## 16:03 — V3.2-6 Runtime Foundation 收口

### 实现

- 新增 V3.2-6 设计文档；共用 Attempt/Run finalizer 保持单一 terminal resolver，并在
  Attempt summary 中固定 failure stage/code。
- 增加公开 Trace 的工具、复用、recovery 和 failure 字段；`/debug/plan` 只渲染现有公开
  Trace/runtime/tool result 数据。
- 增加单进程 Prometheus `/metrics` 与低基数运行时、工具、Store/锁、幂等指标；部署约束为
  一进程一个 scrape target。
- 未捕获 Graph 异常统一为 HTTP 500 `execution_error`，不写 Turn 或 completed replay；受控
  业务失败仍保持安全响应、Turn 与 replay 语义。
- 取消清理仅失败当前 owner 的 in-progress record；原子 complete 已提交时不回滚，确保
  `completed + 1 Turn` 或 `failed + 0 Turn`。
- Controller、LLM、Answer 和 transport 日志不再输出原始异常/上游内容；公开工具失败
  统一脱敏为稳定文本。

### 验证

- 常规完整 pytest：`450 passed, 13 skipped, 1 warning`。
- 设置 `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15` 的完整 pytest：
  `463 passed, 1 warning`。
- `uv run ruff check app tests`、`uv lock --check` 和 `git diff --check` 均通过。
- 新增异常重试、提交后取消 replay 和 API 500 安全 envelope 覆盖；既有真实 Redis failed
  takeover 测试继续实际调用 `fail_request()`。

### 当前状态

- V3.2-6 已完成，业务工具继续冻结；后续工作可在 V3.2 runtime foundation 之外单独规划。
