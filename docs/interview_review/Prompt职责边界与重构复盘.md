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
| P-05 | P1 | 历史统计复用 guard 只检查指标词和数字 | `missing_historical_statistical_metrics()` 未比对主体、分段、位置、时间窗、来源；但当前尚未出现稳定可复现的错配。 | 不扩张脆弱文本正则或 provenance 合同；保留模型语义判断，只在真实失败稳定出现后重开。 | 暂不处理（未稳定复现，2026-08-15） |
| P-06 | P1 | 自然语言 Answer 不提供逐句证据绑定 | LLM 最终输出 `summary` 文本；自然语言 `claims` / `recommendations` 不含逐项 evidence refs，Critic 不逐句复核数字与证据。当前没有真实评估表明模型在获得明确 EvidenceGraph 后会稳定抄错数据。 | 接受该模型能力边界，不增加结构化 claims、二次 LLM Critic 或 evidence-kind 字段核验。若以后出现可稳定复现的转述错误，优先评估模型、Prompt 长度、证据结构和生成参数，再决定是否重开合同级审计。 | 不处理（接受风险，2026-08-14） |
| P-07 | P1 | pair-lane 规则在 prompt 与字符串后处理间分裂 | prompt 禁止来源混淆和无证据因果推断；`_enforce_pair_lane_boundaries()` 曾按“中后期”“翻盘”及 Catalog 值等关键词删除整行，误删否定表述和混合回答中的合法 Catalog 段，且无法撤回已流式发送的 delta。 | 删除关键词后处理；保留 P-10 按 evidence 加载的 pair-lane 与跨来源元数据规则。自然语言事实审计留给 P-12/P-06，不继续扩张字符串规则。 | 已完成（2026-08-14） |
| P-08 | P2 | Synthesizer 的 Wilson 规则过度泛化 | 曾先称“Hero recommendations”均按 `wilson_rating`，随后又规定 lane/position 按 `selection_mode`，matchup/synergy 则以 `synergy` 为主。 | 已删除泛化 Wilson 句；现有 evidence-kind 专属规则保持不变。动态生成 presentation constraints 留待 P-10。 | 已完成（2026-08-13） |
| P-09 | P2 | Synthesizer 存在重复元数据规则 | Catalog metadata 不得作为 STRATZ statistics metadata 的限制曾在 Catalog 段与 pair-lane 段重复出现。 | 通用 Catalog/STRATZ 边界保留在 Catalog 段；pair-lane 段只保留对线与整局分别报告。 | 已完成（2026-08-13） |
| P-10 | P2 | 单一总 Answer prompt 混入不相关格式细则 | 物品合成表、技能、天赋、周趋势、对线结果和推荐排序规则曾在每次请求中一并发送。 | renderer 依据 required/actual evidence kinds 与证据来源只组装相关规则；请求粒度仍由 `current_query` / `reconstructed_goal` 表达，不新增 intent 路由或确定性 Catalog Renderer。 | 已完成（2026-08-14） |
| P-11 | P2 | Answer 无法可靠判断部分查询粒度 | Answer 曾只有 `plan.goal`、required evidence 和 EvidenceGraph，无法直接看到“只回答棒击大地”“不要天赋”等当前措辞。 | 不新增固定 presentation 枚举；Answer 同时接收 `current_query` 与 Controller 的 `reconstructed_goal`，前者保留最新展示要求，后者承接多轮重建。Controller goal 必须保留具名焦点、排除项、数量和细节级别。 | 已完成（2026-08-13） |
| P-12 | P2 | “仅用证据”与“可给无证据 hypothesis”边界含混 | prompt 一方面要求只用 EvidenceGraph，另一方面曾允许无明确证据的解释作为 hypothesis；当前 Critic 不能逐句审计该标签。 | 当前自然语言 Answer 不支持无证据 hypothesis；只有 EvidenceGraph 明确支持时才允许玩法或因果解释，并要求归属到相关证据。策略推演若以后需要，应另设明确合同。 | 已完成（2026-08-14） |
| P-13 | P2 | prompt 规模已经影响维护性 | Controller 中的固定 `Supported` 能力清单与动态 ToolRegistry 目录重复，且未跟随新增赛事/比赛工具更新；P-14 真实规划评估已验证移除该清单不影响代表性规划。 | 删除固定能力清单，具体能力只从渲染的工具目录得出；`Direct-answer rules` 只规定能力类问题按任务领域概括的表达形态。 | 已完成（2026-08-15） |
| P-14 | P1 | ToolDefinition description 仍在规定调用编排 | 默认 Registry 的过度编排说明已收窄；真实规划评估进一步发现玩家 top-N 被误作内部 over-fetch、校验重试会静默删除不支持的 scope，以及 Controller `Supported` 清单仍残留固定工具路由。 | description 只保留工具能力、数据范围和本工具局部产出条件；参数合同明确最终输出语义；Controller 通用规则保留用户约束，能力不足时返回边界，并仅列能力而不列固定路由。 | 已完成（2026-08-13） |
| P-15 | P0 | Controller 对元会话回忆误判 `context_missing` | 真实持久化 Chat Run 已确认近期历史正常加载；另发现 history lookup 空结果在清空 `tool_results` 后没有任何状态进入下一次 Controller 输入，导致模型无法区分“未查”和“已查但未命中”。 | 将三处会话职责压缩为“已供应消息可用、lookup 补充旧消息且不是 Dota evidence、context_missing 需考虑已供应消息和已完成 lookup”；空结果保留最小执行摘要；由 `ToolDefinition.result_destination` 决定结果进入 Controller context 或 EvidenceGraph，不增加关键词路由或确定性回忆模板。 | 结构修复已完成，但真实复测 0/12；P0 未关闭（2026-08-15） |
| P-16 | P0 | Controller 用模型知识直接回答新的 Dota 静态事实 | 真实评估中“兽王是什么英雄”、完整技能与具名技能多次返回 `direct_answer` 且 `tool_results=[]`；Catalog 工具已注册，故障发生在是否进入 `tool_plan`，而非工具链推导。 | Controller 明确模型自身知识不是 `direct_answer` 事实证据；新事实不在当前消息/可复用历史且注册工具可提供时选择 `tool_plan`。保留 ToolRegistry 自行表达工具依赖，不恢复固定 Catalog 路由。 | 已完成（2026-08-15） |

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
- 不把“完整技能必须附带天赋”等产品展示偏好伪装成工具能力；请求粒度由 P-11 的 `current_query` / `reconstructed_goal` 表达，P-10 只按 evidence 选择相关展示规则。
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

### P-10 Answer presentation rules 动态组装（已完成，2026-08-14）

- 将自然语言 Answer 的单一总 system prompt 拆为通用证据规则及 Catalog 属性、技能、天赋、物品、STRATZ 元数据边界、周趋势、pair-lane、排名和日趋势规则片段。
- renderer 取 `graph.required_evidence` 与实际 `graph.evidence[].kind` 的并集；按 evidence kind 选择领域规则，并依据 EvidenceGraph / ToolResult 的 STRATZ source 加载跨来源元数据边界。不读取 `intent`、工具名或自然语言关键词来选择固定路线。
- `hero_ability` 规则同时说明完整技能与具名单技能的展示原则，具体粒度继续由模型结合 `current_query` / `reconstructed_goal` 判断；`hero_talent_tree` 不存在时不再注入天赋表规则。
- Catalog 与 STRATZ 混合回答要求把各自元数据局部归属到相关事实；仅统计查询中，身份解析携带的 Catalog patch/generated_at 不得作为统计版本披露。
- 未新增 `presentation_scope`、output contract、intent 分支或确定性 Catalog Renderer；未修改 Answer 节点、Synthesizer 接口、EvidenceGraph、工具或 API 行为。
- 代表性 system prompt：core 432 字符、属性 891、技能 2,065、技能+天赋 2,446、物品配方 1,741；含 STRATZ 来源边界的 pair-lane 2,249、synergy 1,766、日趋势 1,251 字符。
- `tests/test_agentic_answer.py`：16 passed；prompt/runtime/recovery 定向回归：68 passed；相关 Ruff 通过。

### P-07 删除 pair-lane 关键词后处理（已完成，2026-08-14）

- 删除 `NaturalLanguageAnswerSynthesizer` 对 `_enforce_pair_lane_boundaries()` 的调用及整个关键词删行函数；LLM 完成后的文本现在只做首尾空白清理。
- 保留 P-10 的 `PAIR_LANE_RULES`、`STRATZ_METADATA_BOUNDARY_RULES` 和混合来源局部归属规则，因此对线/整局分离、位置范围、来源边界及禁止无证据因果结论仍在相关 system prompt 中。
- 原后处理无法理解否定语义，会删除“不能证明中后期更强”等正确句子；混合 Catalog + STRATZ 回答中也可能因出现合法 Catalog patch 而误删定义段。流式路径还会先发送未经处理的 delta，导致用户所见内容与最终 `summary` 不一致。
- 定向测试改为验证包含“中后期”“翻盘能力”的否定表述保持原样，不再用脆弱关键词修改模型输出；现有流式测试继续验证 delta 拼接结果等于最终 summary。
- 未修改 EvidenceGraph、Answer prompt 选择、工具、Controller、Critic、输出 schema 或 API 行为。自然语言 claim/evidence 审计仍由后续 P-12/P-06 决定。
- Answer/runtime/recovery 定向回归：72 passed；相关 Ruff 通过。

### P-12 统一 EvidenceGraph 事实边界（已完成，2026-08-14）

- 删除 pair-lane 规则中“缺少明确证据时仍可标记为 hypothesis”的例外；`Use only the provided evidence graph` 现在是自然语言 Answer 的统一事实边界。
- 新规则要求直接报告对线与整局统计差异，不添加无证据的玩法解释或假设；只有 EvidenceGraph 明确支持时才允许因果/玩法解释，并要求将其归属到相关证据。
- 当前不增加 hypothesis schema、presentation scope、Critic 文本分类或字符串过滤。若未来需要策略推演，应通过独立且可验证的输入/输出合同表达，而不是在统计回答中混入自由推测。
- 本批只收紧 Prompt 合同，尚未解决自然语言 `summary` 的逐项 evidence refs；该可审计性问题进入 P-06。
- Answer/prompt/runtime/recovery 定向回归：84 passed；相关 Ruff 通过。

### P-06 自然语言逐句证据审计（不实施，2026-08-14）

- 当前系统能够保证工具结果进入 EvidenceGraph、所需 evidence 完整性及 Answer 只接收当前相关证据，但不形式化证明最终 `summary` 中每个数字、主体和来源均被正确转述。
- 目前没有稳定复现的转述错误，模型在明确数据下偶发抄错被视为低概率模型质量风险；为此引入结构化 claims/evidence refs、二次 LLM Critic、领域字段解析及流式兼容层，投入与维护重量不成比例。
- 当前接受这一边界，不把“缺少逐句形式证明”等同于实现缺陷，也不对外宣称现有 Critic 会审计自然语言中的每项事实。
- 若后续真实评估发现稳定错误，优先更换或升级模型、缩短 Prompt、整理 EvidenceGraph 字段和调整生成参数；只有这些措施仍不足时，才重新评估合同级审计。
- 本项只记录设计决策，不修改 Answer、Critic、schema、API 或测试。

### P-13 Controller 能力事实源收敛（已完成，2026-08-15）

- 删除 Controller 中固定维护的 `Supported in this development version`
  能力清单。该清单与动态 `Tools: {tools}` 重复，且在新增
  PandaScore/OpenDota 赛事与比赛工具后已经滞后。
- 工具名、能力、参数、输出路径和 evidence kinds 继续只由渲染后的
  ToolRegistry 目录提供；保留 Catalog 定义不能替代统计证据的跨工具边界。
- `Direct-answer rules` 增加能力类元问题的展示规则：按用户任务领域概括，
  只在用户明确询问工具名时列出内部名称，且不宣称未注册能力。
- 增加一个仅用于表达风格的中文能力概括案例；案例内容仍必须以当前渲染工具目录为准，不构成固定能力清单或 intent 路由。
- 本项不修改 ToolDefinition、调用顺序、Answer Prompt、ControllerDecision
  schema、EvidenceGraph 或 API 行为。

### P-16 Controller 新事实来源边界（已完成，2026-08-15）

- LunaMax 真实测试确认：“兽王是什么英雄”、“齐天大圣有什么技能”和
  “棒击大地是什么”可稳定或高频返回 `direct_answer`，且
  `tool_results=[]`。Catalog 工具已完整注册，一旦进入 `tool_plan`即能
  正确推导 resolve/reference 链，因此根因是决策层将模型知识误作可用事实。
- `Decision priority` 明确：Dota 事实直答只能使用当前消息或可复用历史中
  已明确存在的事实；模型自身知识不是事实证据。所需事实缺失且注册工具
  可提供时，必须选择 `tool_plan`。
- 原“不要仅因问题是事实就重查”收窄为：只有当事实已在当前消息或可复用
  历史中明确存在时才不重查，避免将该句泛化为“静态事实不需要工具”。
- `Direct-answer rules` 以分支合法性再明确一次事实来源；新增一个基于真实
  失败的 fresh-fact 反例，只要求 `tool_plan`，不指定工具名、参数、调用顺序
  或 intent 路由。
- 加载当前工作树的隔离 8002 API 复测：“兽王是什么英雄”3/3进入
  `resolve_hero + dota.hero_attributes + dota.hero_abilities`；完整技能与具名技能均进入
  `resolve_hero + dota.hero_abilities`。现有 8001 服务未热加载当前 Prompt，其结果不用于最终验收。

### P-15 Controller 会话回忆示例去偏（部分改善，2026-08-15）

- 真实持久化 Chat Run 先确认：第三轮执行前 recent history 完整包含前两轮 `user/assistant` 消息，因此问题不在 PostgreSQL、Redis、SessionStore 或消息注入。
- 修改前 6 类 × 3 次矩阵中只有 4/18 返回 `direct_answer`；工具/功能元会话后的四类用户问题回忆均为 0/3，双英雄回忆为 3/3。
- Controller prompt 原先虽然要求“历史存在时回答请求的 exchange 部分”，但唯一具体 `conversation_recall` JSON 示例固定映射到 `context_missing`，并提供可照抄的中文失败原因。
- 当前删除该语义绑定和固定失败文案，只保留中性的 `context_missing` 字段结构；未增加正则 guard、validator、关键词分类或确定性回复。
- 加载当前源码的独立 API 复测提升到 14/18 `direct_answer`：明确上一问、助手回答回忆和双英雄回忆均 3/3；泛化“我刚才问了什么”为 1/3，两种“两问”表达均为 2/3。
- 该修改方向有效但不足以完全关闭 P0；后续若继续处理，应只增加最小的正向决策区分，并用同一真实矩阵验证，而不是把自然语言表达写成代码分支。
- 后续显式增加“已注入消息就是可用会话；命中时 `context_missing` 无效且无需 history lookup”的规则，使用 7 类 × 3 次真实矩阵复测。两种泛化“刚才问了什么”均 0/3，明确上一问 2/3，哪两个问题 0/3；三个较具体场景仍为 3/3。
- 与前一矩阵相同的 18 个场景从 14/18 降至 11/18，未证明新增提醒有效。该规则及对应断言/golden 变更已撤回，避免继续累积同义 Prompt；P-15 保持部分改善状态。

### P-15 会话上下文结果去向与空 lookup 状态（已实现，2026-08-15）

- Conversation Prompt 不再从不同位置重复解释近期消息、lookup 和
  `context_missing`，统一为三条定义：请求中已供应的 user/assistant 消息是可用上下文；
  `conversation.history_lookup` 只补充更早消息且不是 Dota evidence；只有综合已供应消息和
  已完成 lookup 后仍不可用，才是 `context_missing`。
- `ToolDefinition` 新增 `result_destination = evidence | controller_context`。Graph、决策校验和
  Registry 一致性检查按 destination 工作，不再比较 `conversation.history_lookup` 工具名；
  两类 destination 不允许混在同一计划。
- `controller_context` 结果中的消息进入 `retrieved_messages`，同时保留请求级最小执行摘要。
  空 lookup 明确进入下一次 Controller system input：
  `{"tool":"conversation.history_lookup","status":"completed","matched_turns":0}`。
- 上述 destination 是运行时契约，不额外渲染到每个工具的 Prompt 条目；lookup description
  只说明检索能力，不规定模型的固定调用条件或调用顺序。
- 针对 history/context、Controller decision 和 Prompt 的定向测试为 29 passed，Registry/
  contract 测试为 52 passed，相关 Ruff 检查通过。

### P-15 结构修复后的真实复测（失败，2026-08-15）

- 使用加载当前工作树的临时 8002 API 和独立持久化 Chat Run 会话复测。工具清单后的
  “我刚才问的什么”“我刚才问了什么”“我上一个问题是什么”分别为 0/3；工具清单与
  功能两个问题后的“我刚才问过哪两个问题”为 0/3。合计 0/12 `direct_answer`、12/12
  `context_missing`，所有失败都只调用一次 Controller 且没有执行 history lookup。
- 第一条样本的公开 transcript 明确保存了上一轮 user/assistant 消息；双问题样本中还有一次
  failure reason 主动复述了“询问可用工具与功能”两条历史，却仍选择 `context_missing`。
  因此本轮失败不是消息持久化缺失，也不能由空 lookup 摘要修复。
- 另用显式 lookup 请求验证空结果链路两次：均完成一次
  `conversation.history_lookup` 并进入第二次 Controller，但模型再次规划 lookup，随后触发
  单次预算上限并映射为 `execution_error`。这说明最小摘要已解决“第二次 Controller 不知道
  lookup 已完成”的状态缺口，但当前模型没有稳定遵循该状态语义，且预算终态映射还暴露出
  一个次级问题。
- 测试会话均已删除；临时 API、8002 监听和临时日志目录均已清理。现有 8001 服务未修改。

## 已确认的保留原则

- `intent` 是语义标签，不能变回固定 pipeline 路由键。
- `direct_answer` 可以复用同主体、同范围、同版本/时效条件下的稳定历史事实；历史缺少当前所需的任一统计指标或数值时，必须重新走同一次 `tool_plan`。
- 统计工具、Catalog 定义工具和其证据边界必须保持清晰，不能用静态定义替代 popularity、胜率或推荐证据。
- 对线结果与整局结果必须分别表述；不能仅依两者差异推断中后期、翻盘能力或因果。
- 工具合同应保持单一事实源：工具名、参数、引用路径、可产生证据和输出路径以 ToolRegistry 为准。

## 推荐修改顺序

- **P-15** 暂停：元会话回忆仍可能误判 `context_missing`，但当前不继续增加同义 Prompt 提醒或固定路由。
- **P-05** 暂停：尚无稳定可复现的历史统计错配，不扩张文本正则或 provenance 合同。
- 其余已列 Prompt 重构项均已完成或明确接受风险；后续只在新的稳定失败出现时增加项目。

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
