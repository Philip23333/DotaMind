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
