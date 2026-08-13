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
| P-03 | P1 | 全局 Controller prompt 承担过多工具特例 | 除动态渲染的工具名、参数、引用、证据之外，prompt 曾手写 Catalog/STRATZ 工具链、玩家参数语义和 ranking 语义。 | ToolRegistry description / ArgContract 为工具语义来源；Controller 只保留跨工具的规划原则。 | 已完成（2026-08-13） |
| P-04 | P1 | Controller 将 scope 工具特例写在全局 prompt | region/mode、位置和周窗口等工具特例曾集中写在 Controller；部分 scope 已有 validator，但本批不扩展验证合同。 | 各 ToolDefinition description 声明所消费、忽略或不支持的 scope；Controller 只保留通用 context 放置和枚举语义。静默忽略的强制拒绝留待出现实测失败再单独处理。 | 已完成（2026-08-13） |
| P-05 | P1 | 历史统计复用 guard 只检查指标词和数字 | `missing_historical_statistical_metrics()` 未比对主体、分段、位置、时间窗、来源；例如历史“斧王对线胜率 55%”与当前“Lina 对线胜率？”会通过该 guard。 | 不要扩张脆弱文本正则；保留模型语义判断并用 e2e 评估覆盖错配，若需硬保证则引入结构化 fact provenance。 | 待处理 |
| P-06 | P1 | 自然语言 Answer 的证据绑定不可审计 | LLM 最终只输出 `summary` 文本；自然语言 `claims` / `recommendations` 不含逐项 evidence refs，Critic 也未校验文本事实与证据的一致性。 | 评估结构化 claim + evidence refs 输出，或至少增加按 evidence kind 的确定性覆盖检查。 | 待讨论 |
| P-07 | P1 | pair-lane 规则在 prompt 与字符串后处理间分裂 | prompt 禁止 Catalog 元数据泄漏和无证据因果推断；`_enforce_pair_lane_boundaries()` 又按关键词删除行并补说明。 | 将稳定、可判定的展示/元数据规则下沉到 renderer 或 typed answer；保留 prompt 的一般证据约束。 | 待处理 |
| P-08 | P2 | Synthesizer 的 Wilson 规则过度泛化 | 曾先称“Hero recommendations”均按 `wilson_rating`，随后又规定 lane/position 按 `selection_mode`，matchup/synergy 则以 `synergy` 为主。 | 已删除泛化 Wilson 句；现有 evidence-kind 专属规则保持不变。动态生成 presentation constraints 留待 P-10。 | 已完成（2026-08-13） |
| P-09 | P2 | Synthesizer 存在重复元数据规则 | Catalog metadata 不得作为 STRATZ statistics metadata 的限制曾在 Catalog 段与 pair-lane 段重复出现。 | 通用 Catalog/STRATZ 边界保留在 Catalog 段；pair-lane 段只保留对线与整局分别报告。 | 已完成（2026-08-13） |
| P-10 | P2 | 单一总 Answer prompt 混入不相关格式细则 | 物品合成表、完整技能清单、单技能、天赋表、周趋势、对线结果、推荐排序规则每次请求都会一并发送。 | 依据 `plan` / evidence kinds 渲染请求专属 presentation constraints；稳定 Catalog 表格优先做确定性 renderer。 | 待处理 |
| P-11 | P2 | Answer 无法可靠判断部分查询粒度 | Answer 曾只有 `plan.goal`、required evidence 和 EvidenceGraph，无法直接看到“只回答棒击大地”“不要天赋”等当前措辞。 | 不新增固定 presentation 枚举；Answer 同时接收 `current_query` 与 Controller 的 `reconstructed_goal`，前者保留最新展示要求，后者承接多轮重建。Controller goal 必须保留具名焦点、排除项、数量和细节级别。 | 已完成（2026-08-13） |
| P-12 | P2 | “仅用证据”与“可给无证据 hypothesis”边界含混 | prompt 一方面要求只用 EvidenceGraph，另一方面允许无明确证据的解释作为 hypothesis。 | 决定是否支持策略性推演；若支持，明确其触发条件与标签，且不得混同统计结论。 | 待讨论 |
| P-13 | P2 | prompt 规模已经影响维护性 | 当前默认 Registry（25 个工具）渲染的 Controller system prompt 约 40,859 字符、627 行；Synthesizer static prompt 约 6,155 字符。 | 以职责收敛为主，修改后记录 prompt size 与回归结果，不设脱离效果的硬性压缩指标。 | 待处理 |
| P-14 | P1 | ToolDefinition description 仍在规定调用编排 | 默认 Registry 的过度编排说明已收窄；真实规划评估进一步发现玩家 top-N 被误作内部 over-fetch、校验重试会静默删除不支持的 scope，以及 Controller `Supported` 清单仍残留固定工具路由。 | description 只保留工具能力、数据范围和本工具局部产出条件；参数合同明确最终输出语义；Controller 通用规则保留用户约束，能力不足时返回边界，并仅列能力而不列固定路由。 | 已完成（2026-08-13） |

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

- 将 STRATZ 工具的 bracket、weeks_back、position、region 和 game mode scope 语义写入各 `ToolDefinition.description`。当前 DotaMind v1 玩家工具不支持地区或游戏模式过滤。
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
- 玩家地区/模式过滤仅作为当前 DotaMind v1 的能力边界；只有用户明确要求时才披露该边界。
- 不改变 Validator 的当前拒绝、玩家 handler、QueryContext、EvidenceGraph 或 API 行为。
- 定向 Controller prompt 回归：2 passed；`git diff --check` 通过。

### 批次 8：Controller Catalog 工具链特例迁入工具目录（已完成，2026-08-13）

- 删除 Controller 中完整/单项技能、属性/天赋、物品定义/配方的 Catalog 工具链规则与固定问句示例。
- Catalog ToolDefinition description 承接 resolve 引用、完整技能需 abilities + talent tree、单技能不追加天赋、属性+天赋组合及物品 resolve→info 的语义。
- Controller 保留“静态定义不能替代统计证据”的跨工具边界，并改为从工具目录获取 Catalog 工具链。
- 不新增 intent 路由或固定 pipeline，不修改 Catalog handler、ArgContract 引用校验、EvidenceGraph、Answer 或 API 行为。
- 本批完成的是从 Controller 移除特例；工具 description 中残留的自然语言编排将在 P-14 继续收窄。

### 后续目标：P-14 ToolDefinition description 去编排化

- `resolve_hero` / `resolve_item` description 删除 `call once first`、后续工具名和具体引用字符串，只说明名称解析能力、数据来源及解析结果。
- hero attributes/abilities/talent 与 item info description 删除 `Use after`、`pair with`、`call alone` 和跨工具 required evidence，只保留各自返回的数据、必要的范围差异（如 abilities 不含天赋）及本工具局部产出条件（如配方关系为条件性产出）。
- `requires_reference`、可接受的来源工具/路径/类型继续由 `ArgContract` / `AcceptedRef` 表达并由 Validator 强制校验；模型据此自行推导 resolve → Catalog 数据工具的依赖关系。
- 不把“完整技能必须附带天赋”等产品展示偏好伪装成工具能力；需要稳定输出模式时，在 P-10/P-11 的 presentation scope / output contract 中表达。
- 如定向规划评估显示仅靠结构化合同仍不稳定，只增加一个简短代表性案例，展示名称解析和 plan-local 引用；案例用于提示推理方式，不成为按 intent 路由的固定 pipeline，也不在每个工具 description 重复。
- 验收重点：最终 Controller prompt 仍清晰渲染 `must_reference`、`accepts_ref`、输出路径和 evidence kinds；6 个 Catalog description 不再包含调用顺序或工具组合指令；不修改 handler、实际数据、EvidenceGraph 或 API 行为。

### P-14 工具合同修正：排名候选位置过滤（已完成，2026-08-13）

- 未将位置过滤扩张为通用结果集筛选器：matchup、synergy、lane meta、position stats 与 player performance 的行结构和证据语义不同，统一动态筛选合同会引入不必要的 schema 联合与表达式复杂度。
- 工具由 `stratz.filter_heroes_by_position` 更名为 `stratz.filter_ranked_heroes_by_position`，明确其输入仅是 matchup/synergy 已排名候选，而不是任意英雄列表。
- description 只陈述位置样本过滤、保留原排名、附加位置场次/胜率以及不重排/不生成复合评分的行为；删除具体 `$ref` 写法和固定问句路由。
- `candidate_rows` 增加 `requires_reference=True`，合法来源仍限定为两个 ranking 工具的 `data.candidate_rows`；这是数据完整性合同，不规定某类 intent 必须走固定 pipeline。
- 保留 handler 的单周 STRATZ 位置统计 join、`role_filtered_candidate_row` evidence 和 API 行为；不提供旧工具名兼容别名。

### P-14 玩家工具说明去编排化（已完成，2026-08-13）

- `stratz.player_profile` description 已删除 `capability_boundary` 决策、固定问题路由、前置调用顺序及下游引用写法。
- 当前只声明玩家档案字段、confirmed Steam32 输出、仅接受数字 Steam32 和不支持名称查询的能力边界；下游依赖仍由玩家工具的 `requires_reference` / `AcceptedRef` 表达。
- `stratz.player_recent_matches` 已删除 Controller 决策、profile 依赖和重复参数映射；保留近期比赛/确定性汇总、时间顺序、原生胜负口径与 scope 能力边界。
- `stratz.player_hero_performance` 已删除 Controller 决策、profile 依赖、固定问题路由和自然语言参数映射；总说明只保留分英雄表现、胜率计算口径与 scope 边界，各 ArgContract 只描述自身参数语义。
- 至此，P-14 初审确认的 10 个明显过度编排工具已全部处理；下一阶段审阅 6 个“能力说明基本有效但夹杂跨层或命令式句子”的部分越界工具。

### P-14 部分越界工具统一收窄（已完成，2026-08-13）

- `stratz.pair_lane_outcome` 删除对 Critic 后续行为的描述，只保留无样本时不返回行的工具事实。
- matchup/synergy ranking 将 `Keep` / `never` 命令改为排序事实：`synergy` 是实际排名分数，`pair_wilson_rating` 只是输出的置信度辅助且不参与排名分数；synergy 工具删除固定队友/敌人问题路由。
- `stratz.lane_meta_global` 删除指向 pair 工具的路由、自然语言到 `selection_mode` 的重复映射及读取 Sample-size policy 的跨区块指令；真实去重、排序、指标与 scope 语义保持不变。
- `stratz.hero_position_stats` 删除“answers 某问题”、重复 selection 映射和 Sample-size 指令；将位置输入边界改为事实陈述：消费 `position_id` 参数，不消费 `context.position_ids`。
- `stratz.hero_daily_trends` 删除固定趋势问句，只保留日粒度、窗口、枚举扩展和 scope 事实。
- `conversation.history_lookup` 的近期窗口调用条件继续保留，因为它是内部会话检索安全/预算边界，不是领域工具路由。
- 至此，默认 Registry 的 ToolDefinition description 审查完成；未修改上述 6 个工具的 handler、排序、evidence 或 API 行为。

### P-14 真实规划评估与修正（已完成，2026-08-13）

- 初次真实 Controller 评估中，Catalog resolver 引用、玩家 profile 引用、matchup/synergy、位置过滤、lane meta、position stats 与日趋势均可由模型从能力和结构化合同自行推导；临时从内存移除静态 `Supported` 路由区块后，7 个代表用例仍全部形成合法工具链，因此不需要新增 few-shot 固定 pipeline。
- 评估发现三项稳定缺陷：玩家“最近 20 场中前 5 个英雄”连续生成 `take=50`；玩家地区/游戏模式过滤在首次校验失败后被重试静默删除；四号位克制请求的 goal 无依据补充“敌方中单”。
- `player_hero_performance.take` 参数合同现明确为过滤后的最终 top-N，内部 over-fetch 由工具实现；Controller 通用规则要求 goal 不得增加未声明角色/位置/范围，并禁止初次或重试计划删除、弱化显式 scope，工具不能满足时返回 `capability_boundary`。
- validation retry renderer 升级为 `v2` 并重复上述约束；Controller `Supported` 清单删除箭头、具体工具名、引用写法与固定问句路由，只保留可用能力类别。
- 修正后真实 Controller 复测 4 类用例各 3 次：top-N 参数、地区边界、模式边界与 goal 保真均 12/12 通过；未执行 STRATZ 上游数据查询。

### P-11 Answer 请求粒度输入补全（已完成，2026-08-13）

- 未新增 `presentation_scope` 枚举或按 intent 固定 Answer 路由。`answer_node` 现将当前 `state.query` 传入自然语言 Answer；renderer 以结构化 `request_context` 同时提供 `current_query` 与 `reconstructed_goal`。
- `current_query` 用于保留用户最新的具名焦点、排除项、数量与细节措辞；`reconstructed_goal` 用于承接 Controller 从多轮会话恢复后的完整主体、动作和 scope。Answer 仍只能使用 EvidenceGraph 形成事实。
- Controller goal 保真规则扩展到 named focus、exclusions 和 detail level，避免 Answer 收到已被上游泛化的目标。
- 真实 Answer 使用同一份齐天大圣技能 evidence 验证：完整普通技能请求列出全部普通技能且不含天赋；“只回答棒击大地”仅输出该技能，没有扩展其他技能或天赋。
- 本批只补 Answer 输入语义，不拆分总 Answer prompt；按 evidence kinds 选择 presentation constraints 留给 P-10。

## 已确认的保留原则

- `intent` 是语义标签，不能变回固定 pipeline 路由键。
- `direct_answer` 可以复用同主体、同范围、同版本/时效条件下的稳定历史事实；历史缺少当前所需的任一统计指标或数值时，必须重新走同一次 `tool_plan`。
- 统计工具、Catalog 定义工具和其证据边界必须保持清晰，不能用静态定义替代 popularity、胜率或推荐证据。
- 对线结果与整局结果必须分别表述；不能仅依两者差异推断中后期、翻盘能力或因果。
- 工具合同应保持单一事实源：工具名、参数、引用路径、可产生证据和输出路径以 ToolRegistry 为准。

## 推荐修改顺序

1. **P-10**：按 `current_query` / `reconstructed_goal` 与 evidence kinds 动态渲染请求相关的 Answer 规则。
2. **P-07**：基于新的展示边界收敛 pair-lane 字符串后处理与重复 prompt 规则。
3. **P-12 / P-06 / P-05**：依次确定 hypothesis 边界、claim/evidence 绑定和历史事实 provenance。

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
