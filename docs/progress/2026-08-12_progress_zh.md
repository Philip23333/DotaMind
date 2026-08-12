# 2026-08-12 进度快照

## 02:02 — V3.3-4 文档验收收口

### 已完成

- 将 `DotaMind_V3.3-4_design.md` 状态更新为已于 2026-08-11 实现、2026-08-12 验收完成，并记录 API 全量测试、静态检查和真实 DeepSeek 重放通过。
- 将 `docs/design/README.md` 当前基线从 V3.3-1～V3.3-3 更新为 V3.3-1～V3.3-4 均已完成，并把 V3.3-4 标记为已完成蓝图。
- 在 `docs/README.md` 的版本蓝图入口补充 V3.3-4，完成总文档与设计文档导航对齐。
- 此次只修改文档，没有修改业务代码、运行时合同、配置或持久化结构。

### 验证

- `git diff --check`：通过。
- 人工核对 V3.3-4 状态、总入口、设计入口和中英文进度结构一致；未运行 API pytest 或前端 lint/build。

## 17:56 — 修正 STRATZ 对线结果与整局胜率语义

### 已完成

- `stratz.pair_lane_outcome` 现在按五类对线计数派生对线赢/平/输率，并独立透传 `match_win_rate`；五类计数不守恒时显式失败。
- 移除 pair lane normalized/evidence 中不可靠的 provider `position`，位置范围以 `filters.position_ids` 为唯一依据。
- Evidence kind 从 `pair_lane_winrate` 迁移为 `pair_lane_outcome`，同步更新 ToolRegistry、合同、Controller 示例和 node/tool edge inventory。
- Controller 增加“历史未出现的新统计值必须重新取证、不得编造”的规则；Answer 增加对线率/整局率并列展示、默认单周不代表能力限制、多周趋势和 Catalog/STRATZ 元数据边界。
- 更新 STRATZ 审计、Tool/Evidence/Controller/Answer 架构文档。

### 验证

- 定向 API 测试：164 passed。
- `ruff check app tests`：通过。
- `git diff --check`：通过。

## 17:57 — 全量回归

- API 全量 pytest：552 passed、21 skipped、1 warning（Starlette/httpx 弃用警告）。

## 17:59 — 补充 Evidence 合同断言

- 增加测试，锁定 `pair_lane_outcome` 同时包含对线率与整局率，且不向用户证据暴露 provider `position`。
- 定向回归：26 passed；Ruff 与 `git diff --check` 通过。

## 18:34 — P1 对线问答验收返修

### 已完成

- Controller 增加通用统计指标完整性门：历史缺少任一当前请求指标或数值时，拒绝 `direct_answer` 并要求在同一次决策中走 `tool_plan`；不新增 intent 路由或固定问句分支。
- Answer 收窄 Catalog 元数据披露范围：只有 Catalog 定义类问题披露 patch/generated_at；STRATZ 统计回答不披露 Catalog 快照元数据。
- Answer 增加 pair lane 后置边界校验，过滤 Catalog 统计版本泄漏和仅凭对线/整局胜率差异生成的中后期、翻盘等因果结论，并追加无因果的统计差异说明。
- Prompt component 版本升级至 `controller.base=v3`、`controller.conversation_rules=v3`。
- 增加缺失指标/完整指标 Controller 测试、Catalog + STRATZ 双证据 Prompt 测试、Answer 违规输出后置校验测试。
- 更新 [Controller层](../design/architecture/Controller层.md) 和 [Answer+Critic层](../design/architecture/Answer+Critic层.md)。

### 验证

- P1 定向测试：63 passed；扩展 Controller/Graph/Node 回归：90 passed。
- `ruff check app tests`：通过。
- `git diff --check`：通过。
- 重启独立 8002 API 后真实首问：`tool_plan`、`POSITION_2`、3 个工具调用，同时返回对线赢/平/输率与整局率，无 Catalog patch、无因果结论。
- 真实最近 4 周趋势：`weeks_back=4`、`POSITION_2`，同时比较两类胜率；无 Catalog patch、无因果结论。
- 真实历史缺指标 Controller：选择 `tool_plan`，调用两个 `resolve_hero` 和 `stratz.pair_lane_outcome`。
- 历史完整指标的 FakeLLM 合同测试允许 `direct_answer`；真实模型在易变 STRATZ 场景选择重新取证，符合刷新规则。

## 18:35 — P1 最终全量回归

- API 全量 pytest：556 passed、21 skipped、1 warning（Starlette/httpx 弃用警告）。

## 19:21 — Prompt 职责边界复盘清单

### 已完成

- 新增 `docs/interview_review/Prompt职责边界与重构复盘.md`，记录 Controller 与自然语言 Answer prompt 的已验证职责耦合、具体化/冗余规则、风险、建议归属与分步修改顺序。
- 在 `docs/README.md` 增加该复盘材料入口，并明确其为面试/迭代复盘辅助材料，不是运行时事实源或实施计划。
- 本次只更新文档；未修改 prompt、运行时合同、工具或 API 行为。

### 验证

- 人工核对文档链接、问题 ID、实现入口与当前代码一致；未运行测试（无代码变更）。

## 19:24 — P-01 Controller 决策状态命名统一

### 已完成

- 将 Controller prompt 中 region/mode scope 不受支持时的返回值从公开运行状态 `insufficient_tools` 改为合法决策 discriminator `capability_boundary`。
- 保持 Graph 将 `capability_boundary` 映射为 `insufficient_tools` 的对外状态语义不变。
- 更新 Controller system prompt golden fixture，并新增断言锁定该 schema 边界。
- 将 Prompt 复盘清单的 P-01 标记为已完成。

### 验证

- `tests/test_agentic_prompts.py`：12 passed。
- `git diff --check`：通过。
