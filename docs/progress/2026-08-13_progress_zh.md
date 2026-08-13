# 2026-08-13 进度快照

## 01:40 — P-02 Controller 决策规则去重

### 已完成

- 保留 `Conversation context rules` 作为历史事实复用、统计指标完整性和短追问继承的细节来源。
- 保留 `Decision priority` 作为唯一决策顺序；删除重复的 `Decision validity invariants` 和多步骤 `Final decision gate`。
- 将 `Decision` 小节收窄为已选择 `tool_plan` 后的调用规划与能力边界；`Direct-answer rules` 只保留非空回答和不创建 EvidenceGraph 的输出约束。
- 保留缺失统计指标的 `Completeness example`，未改变 `direct_answer`、`clarification`、`tool_plan`、`capability_boundary` 的语义边界。
- 更新 Controller system prompt golden fixture 与 focused prompt assertions。

### 验证

- `tests/test_agentic_prompts.py`：12 passed。
- Controller system prompt：39,645 字符、606 行、SHA-256 `da4de4875fe807fe10e5fd0002888ba2e86823d52de919dfe94a2c6fd0554e1b`。
- API 全量 pytest：557 passed、21 skipped、1 warning（Starlette/httpx 弃用警告）。
- 未改变 ToolRegistry、Contract、EvidenceGraph 或 API 行为。

## 02:10 — P-09 Answer 元数据规则去重

### 已完成

- 删除 `pair_lane_outcome` 展示段重复的 Catalog/STRATZ 元数据边界；全局 Catalog 段继续作为该边界的唯一 prompt 来源。
- 保留对线与整局结果分别报告、`position_ids` 范围语义及无因果推断约束。
- 未修改 `_enforce_pair_lane_boundaries()`、EvidenceGraph、合同、工具或 API 行为。

### 验证

- `tests/test_agentic_answer.py`：11 passed。
- `ruff check app tests`：通过。
- `git diff --check`：通过。
- Answer prompt：6,011 字符、SHA-256 `db8b98dbe3ce6d89b25e298cfa4b1cd4e9f63b781e0748eb19bee71fa2b1c29c`。

## 02:35 — P-08 Answer 排序口径收敛

### 已完成

- 删除“所有 Hero recommendations 均按 `wilson_rating` 排序”的错误泛化；Answer 不再以通用指令覆盖工具已产出的排序口径。
- 保留 lane/position 的 `selection_mode` 展示规则及 matchup/synergy 的 `synergy` 主排序、`pair_wilson_rating` 置信度辅助规则。
- 未修改 ToolRegistry、工具 handler、EvidenceGraph、实际排序或 API 行为；按 evidence 动态生成展示约束仍留待 P-10。

### 验证

- `tests/test_agentic_answer.py::test_natural_language_answer_receives_catalog_rules_and_real_evidence`：1 passed。
- `git diff --check`：通过。
- Answer prompt：5,723 字符、SHA-256 `1e185c1e0c964ac4d515467b9a70826b3883567358d2c1e7cbe06b37e918b5c1`。

## 03:05 — P-04 scope 工具特例迁入 ToolRegistry 描述

### 已完成

- 将 STRATZ pair-lane、matchup、synergy、lane meta 与 position stats 对 bracket、weeks_back、position、region、game mode 的支持或不支持语义写入各 `ToolDefinition.description`。
- Controller 删除 region/mode、pair-lane、lane-meta 及 player scope 特例；保留跨工具 context、位置别名和周窗口的通用说明。
- 修正 Controller 中“所有位置过滤都写入 `context.position_ids`”的过度表述：依据所选工具的声明使用 context 或 tool-call 参数；`hero_position_stats` 明确使用 `position_id` 参数。
- 不新增 scope metadata、Validator 规则或运行时拒绝逻辑；当前 `validate_context_scope()` 行为不变。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_uses_one_generic_history_first_decision_order`：2 passed。
- `git diff --check`：通过。
- Controller prompt：38,875 字符、585 行、SHA-256 `63a52b7f1aef5dabae91761a6770b05a7b0f75b1961cf651a8dc4d65559af118`。

## 03:25 — P-03 ranking 工具特例迁入 ToolRegistry 描述

### 已完成

- 删除 Controller 中 `lane_meta_global`、`hero_position_stats`、matchup/synergy 的 `selection_mode`、排序与 Wilson 特例。
- 将 lane meta / position stats 的用户意图到 `strong` / `popular` 映射及 Sample-size policy 指引迁入对应工具 description。
- 将 matchup / synergy 的 `synergy` 主排序、`pair_wilson_rating` 置信度辅助和本地 Wilson z=1.96 边界迁入对应工具 description。
- Controller 仅保留“从渲染工具目录与 Sample-size policy 推导所选工具参数、排序语义和证据解释”的通用规则；未修改 handler 排序、参数 schema、EvidenceGraph、Answer 或 API 行为。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_uses_one_generic_history_first_decision_order`：2 passed。
- `git diff --check`：通过。
- Controller prompt：38,390 字符、560 行、SHA-256 `c7e545208975f0b0d872a09d865cb56f7cdb14b4fd3836bce21d768afc6ba67a`。

## 04:00 — P-03 玩家工具特例迁入 ToolRegistry 描述

### 已完成

- 删除 Controller 中 Steam32、profile 前置、近期战绩/英雄表现用途与 `match_take` / `take` / `days` / `min_match_count` 的玩家工具特例。
- 将身份解析、confirmed Steam32 引用、工具用途及参数映射写入三个玩家 ToolDefinition description/ArgContract。
- 实测 STRATZ schema 与带过滤请求接受玩家 `regionIds: [Int]`、`gameModeIds: [Byte]`；当前 DotaMind v1 仍因 QueryContext 字符串枚举没有数值映射与透传而未暴露该能力，Validator 行为不变。
- 未修改 player handler、QueryContext、Validator、EvidenceGraph 或 API 行为。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_uses_one_generic_history_first_decision_order`：2 passed。
- `git diff --check`：通过。
- Controller prompt：37,855 字符、537 行、SHA-256 `15a30518728547d268c0f1db90dc68921605be4b518191666ea119dfed5dde0d`。
