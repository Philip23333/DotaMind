# Prompt 职责边界与重构复盘

> 用途：记录 DotaMind Controller / Answer prompt 的已验证问题、设计取舍和后续修改验收点，供迭代复盘与面试准备使用。
>
> 状态：问题清单；不是运行时合同、工具事实源或实现计划。工具名/参数/证据种类以 ToolRegistry 为准，输出合同以 Contract Registry 为准。

## 复盘背景

当前系统包含两条主要 LLM prompt：

- Controller：根据当前请求、对话上下文、工具目录和合同返回 `ControllerDecision`；只有 `tool_plan` 才进入工具执行与 EvidenceGraph。
- Natural-language Answer Synthesizer：根据 `ExecutionPlan` 和 `EvidenceGraph` 生成用户可读回答。

审查目标不是一味缩短 prompt，而是使每条规则处于可执行、可验证、单一事实源明确的层：

```text
语义理解 / 取舍       -> LLM prompt
工具参数 / 引用 / 能力 -> ToolRegistry + Validator
输出形态 / 必需证据    -> Contract Registry + EvidenceGraph
稳定数据口径           -> Tool normalization / evidence extractor
固定格式和禁止泄漏     -> renderer / deterministic postcondition
最终输出质量           -> Critic + focused tests
```

## 当前问题清单

| ID | 优先级 | 问题 | 已验证事实 | 建议归属 | 状态 |
|---|---|---|---|---|---|
| P-01 | P0 | Controller 决策状态名称不一致 | prompt 曾在 region/mode 不支持时要求返回 `insufficient_tools`，但合法 `ControllerDecision.kind` 是 `capability_boundary`；前者是 Graph 映射后的公开状态。 | Controller prompt 已统一为 `capability_boundary`；Graph 保持状态映射。 | 已完成（2026-08-12） |
| P-02 | P1 | Controller 决策优先级重复 | history rules、Decision priority、Decision invariants、Direct-answer rules、Final decision gate 多次重复 direct answer/tool plan 的判断。 | 保留一处可读的决策优先级；删除或合并重复提醒。 | 已完成（2026-08-13） |
| P-03 | P1 | 全局 Controller prompt 承担过多工具特例 | 除动态渲染的工具名、参数、引用、证据之外，prompt 还手写 Catalog/STRATZ 工具链、玩家参数语义和 ranking 语义；scope、ranking 与玩家特例已迁出。 | ToolRegistry description / ArgContract 为工具语义来源；Controller 只保留跨工具的规划原则。后续单独迁移 Catalog 工具链特例。 | 进行中（2026-08-13） |
| P-04 | P1 | Controller 将 scope 工具特例写在全局 prompt | region/mode、位置和周窗口等工具特例曾集中写在 Controller；部分 scope 已有 validator，但本批不扩展验证合同。 | 各 ToolDefinition description 声明所消费、忽略或不支持的 scope；Controller 只保留通用 context 放置和枚举语义。静默忽略的强制拒绝留待出现实测失败再单独处理。 | 已完成（2026-08-13） |
| P-05 | P1 | 历史统计复用 guard 只检查指标词和数字 | `missing_historical_statistical_metrics()` 未比对主体、分段、位置、时间窗、来源；例如历史“斧王对线胜率 55%”与当前“Lina 对线胜率？”会通过该 guard。 | 不要扩张脆弱文本正则；保留模型语义判断并用 e2e 评估覆盖错配，若需硬保证则引入结构化 fact provenance。 | 待处理 |
| P-06 | P1 | 自然语言 Answer 的证据绑定不可审计 | LLM 最终只输出 `summary` 文本；自然语言 `claims` / `recommendations` 不含逐项 evidence refs，Critic 也未校验文本事实与证据的一致性。 | 评估结构化 claim + evidence refs 输出，或至少增加按 evidence kind 的确定性覆盖检查。 | 待讨论 |
| P-07 | P1 | pair-lane 规则在 prompt 与字符串后处理间分裂 | prompt 禁止 Catalog 元数据泄漏和无证据因果推断；`_enforce_pair_lane_boundaries()` 又按关键词删除行并补说明。 | 将稳定、可判定的展示/元数据规则下沉到 renderer 或 typed answer；保留 prompt 的一般证据约束。 | 待处理 |
| P-08 | P2 | Synthesizer 的 Wilson 规则过度泛化 | 曾先称“Hero recommendations”均按 `wilson_rating`，随后又规定 lane/position 按 `selection_mode`，matchup/synergy 则以 `synergy` 为主。 | 已删除泛化 Wilson 句；现有 evidence-kind 专属规则保持不变。动态生成 presentation constraints 留待 P-10。 | 已完成（2026-08-13） |
| P-09 | P2 | Synthesizer 存在重复元数据规则 | Catalog metadata 不得作为 STRATZ statistics metadata 的限制曾在 Catalog 段与 pair-lane 段重复出现。 | 通用 Catalog/STRATZ 边界保留在 Catalog 段；pair-lane 段只保留对线与整局分别报告。 | 已完成（2026-08-13） |
| P-10 | P2 | 单一总 Answer prompt 混入不相关格式细则 | 物品合成表、完整技能清单、单技能、天赋表、周趋势、对线结果、推荐排序规则每次请求都会一并发送。 | 依据 `plan` / evidence kinds 渲染请求专属 presentation constraints；稳定 Catalog 表格优先做确定性 renderer。 | 待处理 |
| P-11 | P2 | Answer 无法可靠判断部分查询粒度 | prompt 需要区分“完整技能列表”和“单技能”，但 Answer 输入只有 `plan.goal`、required evidence 和 EvidenceGraph，没有原始 query。 | 在计划或输出合同中显式携带 answer/presentation scope，或确保规范化 goal 是足够的合同字段。 | 待讨论 |
| P-12 | P2 | “仅用证据”与“可给无证据 hypothesis”边界含混 | prompt 一方面要求只用 EvidenceGraph，另一方面允许无明确证据的解释作为 hypothesis。 | 决定是否支持策略性推演；若支持，明确其触发条件与标签，且不得混同统计结论。 | 待讨论 |
| P-13 | P2 | prompt 规模已经影响维护性 | 当前默认 Registry（25 个工具）渲染的 Controller system prompt 约 40,859 字符、627 行；Synthesizer static prompt 约 6,155 字符。 | 以职责收敛为主，修改后记录 prompt size 与回归结果，不设脱离效果的硬性压缩指标。 | 待处理 |

### 批次 1：结构拆分（已完成，2026-08-12）

- 新增 `apps/api/app/agentic/prompts/controller_rules.py`，承载 Controller 静态规则；`controller.py` 保留唯一动态 bundle/system/message renderer。
- 新增 `apps/api/app/agentic/prompts/answer.py`，承载自然语言 Answer system prompt 与固定消息 renderer；`answer/synthesizer.py` 只负责调用和结果包装。
- 本批次未删除重复规则，也未修改工具合同、决策合同、Answer 后置边界或运行时 schema。
- Controller prompt 仍为 40,860 字符、627 行，SHA-256 为 `f73db2aa56ee4021ba8deeae28b27697c4dc560e391c27814be5278fd54cce73`；Answer prompt 仍为 6,155 字符，SHA-256 为 `1ad1d6236b62f47898c95926d931b0d35edb7dbc6922a68bbbf79de9bf910986`。
- 定向回归 64 passed，Ruff 通过；P-02 规则去重仍待后续批次处理。

### 批次 2：Controller 决策规则去重（已完成，2026-08-13）

- 保留 `Conversation context rules` 作为历史事实复用、统计指标完整性和短追问继承的细节来源。
- 保留 `Decision priority` 作为唯一决策顺序；删除重复的 `Decision validity invariants` 和多步骤 `Final decision gate`。
- 将 `Decision` 小节收窄为已选择 `tool_plan` 后的调用规划与能力边界；`Direct-answer rules` 只保留非空回答和不创建 EvidenceGraph 的输出约束。
- 保留缺失统计指标的 `Completeness example`，未改变 direct_answer、clarification、tool_plan、capability_boundary 的语义边界。
- Controller system prompt 现为 39,645 字符、606 行，SHA-256 为 `da4de4875fe807fe10e5fd0002888ba2e86823d52de919dfe94a2c6fd0554e1b`。
- 定向回归 `tests/test_agentic_prompts.py`：12 passed。
- API 全量 pytest：557 passed、21 skipped、1 warning（Starlette/httpx 弃用警告）。

### 批次 3：Answer 元数据规则去重（已完成，2026-08-13）

- 删除 `pair_lane_outcome` 展示段中重复的 Catalog/STRATZ 元数据边界；全局 Catalog 段仍是该边界的唯一 prompt 来源。
- pair-lane 段继续要求分别报告对线与整局结果，并保留位置范围与无因果推断约束。
- 未修改 `_enforce_pair_lane_boundaries()`、EvidenceGraph、合同、工具或 API 行为。
- 定向 Answer 回归 `tests/test_agentic_answer.py`：11 passed；`ruff check app tests` 通过。

### 批次 4：Answer 排序口径收敛（已完成，2026-08-13）

- 删除“所有 Hero recommendations 均按 `wilson_rating` 排序”的错误泛化。
- 保留 lane/position 的 `selection_mode` 口径及 matchup/synergy 的 `synergy` 主排序、`pair_wilson_rating` 置信度辅助口径。
- 未改动 ToolRegistry、工具 handler、EvidenceGraph 或实际排序；按 evidence 动态生成 presentation constraints 留待 P-10。

### 批次 5：Controller scope 说明迁入工具目录（已完成，2026-08-13）

- 将 STRATZ 工具的 bracket、weeks_back、position、region 和 game mode scope 语义写入各 `ToolDefinition.description`。玩家 STRATZ 上游请求也接受 region/game mode，但其数值类型与当前 `QueryContext` 字符串枚举不兼容，DotaMind v1 尚未暴露该过滤。
- Controller 保留通用 context 放置、位置别名和周窗口语义；删除 region/mode、pair-lane、lane-meta 与 player 的全局工具特例。
- 不新增 scope metadata、Validator 规则或运行时拒绝；若后续出现工具静默忽略 scope 的实测失败，再单独决定是否强化合同。
- 定向 Controller prompt 回归：2 passed；`git diff --check` 通过。

### 批次 6：Controller ranking 规则迁入工具目录（已完成，2026-08-13）

- 删除 Controller 中 lane meta、position stats、matchup/synergy 的 `selection_mode`、排序与 Wilson 特例。
- `stratz.lane_meta_global` 与 `stratz.hero_position_stats` description 承接用户意图到 `strong`/`popular` 的映射及 Sample-size policy 的取值指引。
- `stratz.hero_matchup_ranking` 与 `stratz.hero_synergy_ranking` description 承接 `synergy` 主排序、`pair_wilson_rating` 置信度辅助和 z=1.96 的边界。
- Controller 仅保留从动态 ToolRegistry 目录和 Sample-size policy 推导已选工具参数、排序语义与证据解释的通用规则；不改 handler 排序、参数 schema、EvidenceGraph 或 Answer 展示规则。
- 定向 Controller prompt 回归：2 passed；`git diff --check` 通过。

### 批次 7：Controller 玩家工具特例迁入工具目录（已完成，2026-08-13）

- 删除 Controller 中 Steam32、profile 前置、近期战绩/英雄表现用途及 `match_take` / `take` / `days` / `min_match_count` 的玩家工具特例。
- 三个玩家 ToolDefinition description 与参数合同承接身份解析、必须引用 confirmed Steam32、各查询用途及参数映射。
- 修正上游能力表述：实际 STRATZ schema 与带过滤请求均接受玩家 `regionIds: [Int]`、`gameModeIds: [Byte]`；当前 DotaMind v1 因未定义字符串 context 到数值 ID 的映射和透传而未暴露该能力。
- 不改变 Validator 的当前拒绝、玩家 handler、QueryContext、EvidenceGraph 或 API 行为。
- 定向 Controller prompt 回归：2 passed；`git diff --check` 通过。

## 已确认的保留原则

- `intent` 是语义标签，不能变回固定 pipeline 路由键。
- `direct_answer` 可以复用同主体、同范围、同版本/时效条件下的稳定历史事实；历史缺少当前所需的任一统计指标或数值时，必须重新走同一次 `tool_plan`。
- 统计工具、Catalog 定义工具和其证据边界必须保持清晰，不能用静态定义替代 popularity、胜率或推荐证据。
- 对线结果与整局结果必须分别表述；不能仅依两者差异推断中后期、翻盘能力或因果。
- 工具合同应保持单一事实源：工具名、参数、引用路径、可产生证据和输出路径以 ToolRegistry 为准。

## 推荐修改顺序

1. **P-01**：无行为争议的 schema 用词统一，先避免无效 JSON/retry。
2. **P-03（下一小批）**：将 Catalog 完整技能/单技能、属性/天赋、物品配方的工具链特例迁入 ToolRegistry；保留 Controller 的通用工具规划规则。
5. **P-07 / P-10 / P-11**：设计 answer presentation scope 与稳定 renderer 边界，避免一次性重写所有自然语言回答。
6. **P-05 / P-06 / P-12**：涉及历史事实 provenance、回答结构和产品能力边界，先形成小设计决策，再实现。

## 每项修改的验收模板

每次只处理一个或一组强相关条目，并记录：

```text
问题 ID：
修改前职责归属：
修改后职责归属：
删除/新增的 prompt 规则：
新增或更新的合同/validator/renderer：
覆盖的正例、反例与回归测试：
未改变的语义边界：
prompt 字符数（若有变化）：
```

## 相关实现入口

- `apps/api/app/agentic/prompts/controller.py`
- `apps/api/app/agentic/planning/contracts.py`
- `apps/api/app/agentic/planning/decisions.py`
- `apps/api/app/agentic/answer/synthesizer.py`
- `apps/api/app/agentic/critic/reviewer.py`
- `apps/api/app/agentic/tools/stratz_tools.py`
