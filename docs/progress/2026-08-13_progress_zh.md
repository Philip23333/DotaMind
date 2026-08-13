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

## 04:15 — 收窄玩家过滤能力边界披露

### 已完成

- 玩家工具 prompt 只声明当前 DotaMind v1 不支持地区/游戏模式过滤；删除不必要的上游 STRATZ 数值类型、映射和透传实现细节。
- 只有用户明确要求地区或游戏模式过滤时，Controller 才应返回该能力边界，不应在普通玩家查询中主动披露。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_uses_one_generic_history_first_decision_order`：2 passed。
- `git diff --check`：通过。
- Controller prompt：37,781 字符、537 行、SHA-256 `3888cccbd0f4da92a49d6fd03c7f24b68fa20fbe828da440814b5072d216fce3`。

## 04:35 — P-03 Catalog 工具链特例迁入 ToolRegistry 描述

### 已完成

- 删除 Controller 中完整/单项技能、属性/天赋、物品定义/配方的 Catalog 工具链规则与固定问句示例。
- `resolve_hero`、hero attributes/abilities/talent、`resolve_item` 与 item info 的 ToolDefinition description 承接对应工具链、解析引用和 required evidence 语义。
- Controller 保留静态定义不能替代统计证据的跨工具边界，并从渲染工具目录获取 Catalog 工具链。
- 未新增 intent 路由或固定 pipeline，未修改 Catalog handler、ArgContract、EvidenceGraph、Answer 或 API 行为。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_declares_catalog_static_and_statistical_boundaries`：2 passed。
- `git diff --check`：通过。
- Controller prompt：37,516 字符、510 行、SHA-256 `f5c99b431247ce203a1963f76f0fec3916cacd2942497022aeabb5c3798712cc`。

## 15:43 — 记录 P-14 Catalog 工具说明去编排化目标

### 已完成

- 在 Prompt 职责边界复盘中新增 P-14：识别 P-03 迁移后的 6 个 Catalog ToolDefinition description 仍重复规定调用顺序、工具组合、引用写法和跨工具 evidence。
- 后续将 description 收窄为能力、数据范围和本工具局部产出条件；依赖关系以 `ArgContract` / `AcceptedRef` / `OutputPathContract` 为唯一来源，并由模型据此规划。
- 若定向评估证明需要示范，仅保留一个非固定 pipeline 的代表性规划案例；技能/天赋等展示范围归 P-10/P-11。
- 本次只更新重构计划与进度文档，未修改 Prompt 或运行时行为。

### 验证

- `git diff --check`：通过。

## 16:27 — P-14 第 1 项：收窄 `resolve_hero` 工具说明

### 已完成

- `resolve_hero` description 删除 `call once first`、下游 `dota.hero_*` 工具指令和具体 plan-local 引用写法，只保留英雄名称解析能力、Valve Catalog 数据来源与三种解析状态。
- 英雄 ID 的输出路径以及下游工具必须接受该引用的约束仍由 `OutputPathContract`、`AcceptedRef` 和 `requires_reference` 表达；未修改 handler、参数合同、EvidenceGraph 或 API 行为。
- P-14 其余 9 个明确过度编排的工具尚未修改，将逐项审阅。

### 验证

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` 与 `::test_controller_prompt_declares_catalog_static_and_statistical_boundaries`：2 passed。

## 16:31 — P-14 第 2 项：收窄 `dota.hero_attributes` 工具说明

### 已完成

- `dota.hero_attributes` description 删除 `Use after resolve_hero`、与天赋工具配对及跨工具 required evidence，只保留官方静态属性和战斗字段的数据能力。
- 英雄 ID 引用依赖继续由 `ArgContract` / `AcceptedRef` 强制；未修改工具 handler、参数合同、证据产出或 API 行为。
- P-14 其余 8 个明确过度编排的工具尚未修改。

### 验证

- 两条相关 Controller prompt 测试：2 passed。

## 16:35 — P-14 第 3 项：收窄 `dota.hero_abilities` 工具说明

### 已完成

- `dota.hero_abilities` description 删除 resolver 顺序、完整技能强制配对天赋树、单技能调用指令及跨工具 required evidence，只保留按顺序返回非天赋技能定义的数据能力。
- 保留 `non-talent` 作为真实数据范围；是否同时查询或展示天赋由用户请求及后续 presentation scope 决定。
- 未修改引用合同、工具 handler、证据产出或 API 行为；P-14 其余 7 个明确过度编排的工具尚未修改。

### 验证

- 两条相关 Controller prompt 测试：2 passed。

## 16:46 — P-14 第 4 项：收窄 `dota.hero_talent_tree` 工具说明

### 已完成

- `dota.hero_talent_tree` description 删除 resolver 顺序、与技能/属性工具配对及共享引用的自然语言指令，只保留按 10/15/20/25 级返回天赋树的数据能力。
- 英雄 ID 引用依赖继续由结构化参数合同表达；是否组合技能、属性和天赋工具由模型根据当前请求规划。
- 未修改工具 handler、证据产出或 API 行为；P-14 其余 6 个明确过度编排的工具尚未修改。

### 验证

- 两条相关 Controller prompt 测试：2 passed。

## 16:49 — P-14 第 5 项：收窄 `resolve_item` 工具说明

### 已完成

- `resolve_item` description 删除固定调用顺序、下游 `dota.item_info` 指令和具体 plan-local 引用写法。
- 保留“明确配方措辞选择 recipe scope”，因为这是 resolver 对 `recipe` / `图纸` / `配方` 输入的真实局部解析行为。
- 未修改结构化引用合同、resolver handler 或 API 行为；P-14 其余 5 个明确过度编排的工具尚未修改。

### 验证

- 两条相关 Controller prompt 测试：2 passed。

## 16:51 — P-14 第 6 项：收窄 `dota.item_info` 工具说明

### 已完成

- `dota.item_info` description 删除 resolver 顺序以及价格/配方问题的跨工具 required evidence 组合。
- 保留并改写配方证据的条件性产出：只有物品存在组件或升级关系时才产生 recipe evidence；价格仍属于物品定义，不强制要求配方证据。
- 未修改引用合同、工具 handler、evidence extractor 或 API 行为；P-14 其余 4 个明确过度编排的工具尚未修改。

### 验证

- 两条相关 Controller prompt 测试：2 passed。
