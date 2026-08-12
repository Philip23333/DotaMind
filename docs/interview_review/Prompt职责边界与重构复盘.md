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
| P-02 | P1 | Controller 决策优先级重复 | history rules、Decision priority、Decision invariants、Direct-answer rules、Final decision gate 多次重复 direct answer/tool plan 的判断。 | 保留一处可读的决策优先级；删除或合并重复提醒。 | 待处理 |
| P-03 | P1 | 全局 Controller prompt 承担过多工具特例 | 除动态渲染的工具名、参数、引用、证据之外，prompt 还手写 Catalog/STRATZ 工具链、位置/时间 scope 特例、玩家参数语义和 ranking 语义。 | ToolRegistry metadata / ArgContract / context-capability validator；prompt 只保留跨工具的规划原则。 | 待处理 |
| P-04 | P1 | scope 支持性没有完全由合同强制 | region/mode 已有 context validator；但 `lane_meta_global` 忽略 `position_ids`、`hero_daily_trends` 不应携带 `weeks_back` 等仍主要依赖 prompt。 | 为每个工具声明 context 支持/禁止/忽略语义，并在 Validator 拒绝会导致静默忽略的计划。 | 待处理 |
| P-05 | P1 | 历史统计复用 guard 只检查指标词和数字 | `missing_historical_statistical_metrics()` 未比对主体、分段、位置、时间窗、来源；例如历史“斧王对线胜率 55%”与当前“Lina 对线胜率？”会通过该 guard。 | 不要扩张脆弱文本正则；保留模型语义判断并用 e2e 评估覆盖错配，若需硬保证则引入结构化 fact provenance。 | 待处理 |
| P-06 | P1 | 自然语言 Answer 的证据绑定不可审计 | LLM 最终只输出 `summary` 文本；自然语言 `claims` / `recommendations` 不含逐项 evidence refs，Critic 也未校验文本事实与证据的一致性。 | 评估结构化 claim + evidence refs 输出，或至少增加按 evidence kind 的确定性覆盖检查。 | 待讨论 |
| P-07 | P1 | pair-lane 规则在 prompt 与字符串后处理间分裂 | prompt 禁止 Catalog 元数据泄漏和无证据因果推断；`_enforce_pair_lane_boundaries()` 又按关键词删除行并补说明。 | 将稳定、可判定的展示/元数据规则下沉到 renderer 或 typed answer；保留 prompt 的一般证据约束。 | 待处理 |
| P-08 | P2 | Synthesizer 的 Wilson 规则过度泛化 | 先称“Hero recommendations”均按 `wilson_rating`，随后又规定 lane/position 按 `selection_mode`，matchup/synergy 则以 `synergy` 为主。 | 删除泛化 Wilson 句；按 evidence kind / selection_mode 生成具体呈现约束。 | 待处理 |
| P-09 | P2 | Synthesizer 存在重复元数据规则 | Catalog metadata 不得作为 STRATZ statistics metadata 的限制在 Catalog 段与 pair-lane 段重复出现。 | 保留通用 Catalog/STRATZ 边界；pair-lane 段只保留对线与整局分别报告。 | 待处理 |
| P-10 | P2 | 单一总 Answer prompt 混入不相关格式细则 | 物品合成表、完整技能清单、单技能、天赋表、周趋势、对线结果、推荐排序规则每次请求都会一并发送。 | 依据 `plan` / evidence kinds 渲染请求专属 presentation constraints；稳定 Catalog 表格优先做确定性 renderer。 | 待处理 |
| P-11 | P2 | Answer 无法可靠判断部分查询粒度 | prompt 需要区分“完整技能列表”和“单技能”，但 Answer 输入只有 `plan.goal`、required evidence 和 EvidenceGraph，没有原始 query。 | 在计划或输出合同中显式携带 answer/presentation scope，或确保规范化 goal 是足够的合同字段。 | 待讨论 |
| P-12 | P2 | “仅用证据”与“可给无证据 hypothesis”边界含混 | prompt 一方面要求只用 EvidenceGraph，另一方面允许无明确证据的解释作为 hypothesis。 | 决定是否支持策略性推演；若支持，明确其触发条件与标签，且不得混同统计结论。 | 待讨论 |
| P-13 | P2 | prompt 规模已经影响维护性 | 当前默认 Registry（25 个工具）渲染的 Controller system prompt 约 40,859 字符、627 行；Synthesizer static prompt 约 6,155 字符。 | 以职责收敛为主，修改后记录 prompt size 与回归结果，不设脱离效果的硬性压缩指标。 | 待处理 |

## 已确认的保留原则

- `intent` 是语义标签，不能变回固定 pipeline 路由键。
- `direct_answer` 可以复用同主体、同范围、同版本/时效条件下的稳定历史事实；历史缺少当前所需的任一统计指标或数值时，必须重新走同一次 `tool_plan`。
- 统计工具、Catalog 定义工具和其证据边界必须保持清晰，不能用静态定义替代 popularity、胜率或推荐证据。
- 对线结果与整局结果必须分别表述；不能仅依两者差异推断中后期、翻盘能力或因果。
- 工具合同应保持单一事实源：工具名、参数、引用路径、可产生证据和输出路径以 ToolRegistry 为准。

## 推荐修改顺序

1. **P-01**：无行为争议的 schema 用词统一，先避免无效 JSON/retry。
2. **P-02 / P-09**：删除严格重复的 prompt 文本，运行现有 focused tests，建立缩短不改语义的基线。
3. **P-08**：收窄错误泛化的 ranking 表述，确保各 evidence kind 的排序口径单一。
4. **P-04 / P-03**：逐项把可机读的 scope 和工具能力移入 registry/validator；每迁一项，删掉对应静态 prompt 特例。
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
