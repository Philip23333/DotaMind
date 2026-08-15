# 2026-08-14 进度快照

## 00:08 — P-10 Answer presentation rules 动态组装

### 已完成

- 将自然语言 Answer 的单一总 system prompt 拆为核心证据规则和 Catalog 属性、技能、天赋、物品、STRATZ 元数据边界、周趋势、pair-lane、排名及日趋势规则片段。
- renderer 合并 required evidence 与实际 evidence kinds，并依据 EvidenceGraph / ToolResult 的 STRATZ source 加载跨来源元数据边界；规则选择不读取 `intent`、工具名或自然语言关键词。
- 完整技能与具名单技能的粒度继续由 Answer LLM 结合 `current_query` / `reconstructed_goal` 判断；只有存在或要求 `hero_talent_tree` 时才注入天赋表规则。
- Catalog 与 STRATZ 混合回答必须把来源元数据局部归属到相关事实；仅统计查询不得把身份解析携带的 Catalog patch/generated_at 当作统计版本。
- 未新增 `presentation_scope`、output contract、intent 分支或确定性 Catalog Renderer；未修改 Answer 节点、Synthesizer 接口、EvidenceGraph、工具或 API 行为。

### 验证

- `tests/test_agentic_answer.py`：16 passed。
- `tests/test_agentic_prompts.py`、`tests/test_agentic_runtime.py`、`tests/test_agentic_recovery.py`：68 passed。
- 相关文件 Ruff：通过。
- 代表性 system prompt：core 432 字符、属性 891、技能 2,065、技能+天赋 2,446、物品配方 1,741；含 STRATZ 来源边界的 pair-lane 2,249、synergy 1,766、日趋势 1,251 字符。

## 01:23 — P-07 删除 pair-lane 关键词后处理

### 已完成

- 删除 `_enforce_pair_lane_boundaries()` 调用和函数；自然语言 Answer 完成后只清理首尾空白，不再按“中后期”“翻盘”或 Catalog patch 等关键词删除整行。
- 保留 evidence-specific pair-lane、STRATZ/Catalog 来源归属和无证据因果结论限制；这些规则只在相关 EvidenceGraph 中进入 system prompt。
- 修复正确否定表述及混合 Catalog + STRATZ 定义段可能被误删的问题；流式 delta 与最终 summary 不再经过不同的内容改写路径。
- 未修改 EvidenceGraph、Controller、工具、Critic、输出 schema 或 API 行为；自然语言事实审计留给 P-12/P-06。

### 验证

- Answer、runtime 与 recovery 定向测试：72 passed。
- 相关文件 Ruff：通过。

## 01:26 — P-12 禁止无证据 hypothesis

### 已完成

- 删除 pair-lane Prompt 中“缺少明确证据时仍可标记为 hypothesis”的例外，统一以 EvidenceGraph 作为自然语言 Answer 的事实边界。
- 无证据时只允许报告统计差异，不添加玩法解释或假设；因果/玩法解释只有在 EvidenceGraph 明确支持时才允许，并必须归属到相关证据。
- 未增加 hypothesis schema、Critic 文本分类、字符串过滤或确定性 Answer 路由；未来若需要策略推演，应另设可验证合同。
- 自然语言 `summary` 尚未逐项绑定 evidence refs，该问题进入 P-06。

### 验证

- Answer、prompt、runtime 与 recovery 定向测试：84 passed。
- 相关文件 Ruff：通过。

## 01:31 — P-06 接受自然语言逐句审计边界

### 决策

- 将 P-06 标记为“不处理（接受风险）”：当前自然语言 Answer 不提供逐句 claims/evidence refs，Critic 也不声称复核每个数字、主体和来源。
- 目前没有真实评估表明模型在获得明确 EvidenceGraph 后会稳定抄错数据；不为低概率模型质量风险增加结构化 claims、二次 LLM Critic、领域字段解析或流式兼容层。
- 若以后出现可稳定复现的转述错误，优先评估模型更换/升级、Prompt 长度、EvidenceGraph 结构及生成参数；这些措施不足时再重开合同级审计。
- 本项只更新设计决策与文档，没有修改代码或测试。
