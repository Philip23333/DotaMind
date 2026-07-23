# DotaMind 进度快照（2026-07-22）

## 14:17 — V3.2-2 基线提交与 V3.2-3 有界缺证 Recovery/Replan

### 基线

- V3.2-2 的轻量 Prompt Registry 收口已独立提交为 `8eb0051`；提交前验证结果为
  `396 passed, 1 warning`。
- 用户维护的 `AGENTS.md` 修改保持未暂存，未混入 V3.2-2 或 V3.2-3 功能范围。

### V3.2-3 实现

- Graph 统一为 `attempt_finalize -> recovery -> terminal/replan`，只保留
  `attempt_reset -> controller` 一条受控回边；每个 Run 只能形成一个或两个连续
  Attempt。
- Recovery 只处理真实可达的普通全局 missing-evidence 缺口；Critic、tool error、
  extractor failure、per-call evidence 缺口和 Answer error 均不触发 Replan。
- Attempt 1 必须保留 Attempt 0 的完整调用前缀和 plan scope，保持规范化后的
  `required_evidence` 完全相等，并使用此前未用的工具覆盖全部缺口。
- 增加 Run 内 canonical fingerprint cache：相同 id 的成功/失败结果复用且不重试；
  相同 fingerprint 换 id 固定返回 `execution_budget_error`。
- 增加共享 node-entry deadline/budget guard，并在每个通过 pre-dispatch validation 的
  未复用 handler 前再次检查 deadline 和 tool budget。Attempt 1 启动前再检查 deadline；
  收口节点不被 deadline 阻断。
- `AttemptRecord.recovery_code` 只描述当前 Attempt 的启动原因：Attempt 0 永远为 null，
  实际启动的 Attempt 1 为 `missing_evidence`，封存后的历史 Attempt 不回写。
- 公开 runtime 支持一到两个 Attempt，并增加
  `attempts[].recovery_code` 与 `tool_call_statuses[].reused`；feedback、baseline、
  fingerprint 和 cache 保持内部瞬态。
- `controller.recovery_rules=v1` 已接入 Prompt manifest；Recovery 消息复用原 system
  prompt、原 user envelope 和完整 baseline decision，V3.2-2 system golden/hash 不变。

### 文档与验证

- 新增 `docs/design/versions/DotaMind_V3.2-3_design.md`，并同步 V3.2 总设计、设计入口、
  当前架构、节点清单和 API 文档。
- 新增合成 Registry/FakeController/FakeClock 测试，覆盖补证成功、二次缺证、无
  producer、三类 replan 预算、前缀不变量、成功/失败复用、duplicate、逐 handler
  budget/deadline、Attempt 启动 deadline、公开字段和隐私边界。
- 已验证：`uv run ruff check .` 通过；完整 `uv run pytest -q` 为
  `422 passed, 1 warning`；`uv lock --locked` 通过；`git diff --check` 通过（仅现有
  Windows LF/CRLF 提示）。

### 明确延后

- Critic Recovery、工具重试/fallback、超过一次 Replan、跨 Run cache、请求幂等、
  Redis、工具级 TraceEvent、指标系统和 in-flight 强制取消均未接入。
