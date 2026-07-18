# DotaMind MVP 设计文档 v2.5（受约束 Tool Calling 架构）

> 本文替代 v2.1 的内部执行架构方向。v2.1 已经明确 Agent 与 Tool 的边界，但当前实现仍以 `task_type -> 固定服务链路` 为核心。v2.5 将主链路升级为 **受约束 Tool Calling / Execution Plan 架构**，让 Orchestrator 不只是选择服务，而是规划需要调用哪些工具、需要哪些证据、如何组合结果。

本文目标不是新增某个单点功能，而是避免后续每增加一种能力都重新写一条固定 pipeline。后续实现应以本文为主线推进。

> 当前实现注记（2026-06-30）：旧固定 report/query 链路已删除。当前 API 只保留
> `POST /api/v1/plan`、`GET /debug/plan` 和 `GET /health`；后续能力应继续通过
> agentic tools、EvidenceGraph、answer contracts 扩展，不恢复旧 endpoint 兼容层。

---

## 1. 问题定义：当前架构哪里不够 Agentic

### 1.1 当前实现形态

当前主链路是：

```text
User Query
  ↓
OrchestratorAgent
  - LLM function calling 选择一个 report service
  ↓
ReportRequest
  - task_type = meta_report | patch_impact | team_report | claim_verification
  ↓
ReportPipeline.run()
  - if task_type == ...
  ↓
RetrieverTool.retrieve_*
  ↓
AnalyzerAgent.analyze_*
  ↓
CriticAgent.review_report()
  ↓
FormatterTool
  ↓
Response
```

Orchestrator 当前输出类似：

```json
{
  "task_type": "team_report",
  "team_name": "XG",
  "time_range": "last_30_days"
}
```

这说明当前 Orchestrator 主要在回答：

```text
这个用户问题属于哪个预定义服务？
```

### 1.2 当前架构的问题

这种结构稳定、易测，但智能化边界较低：

- 新增能力通常需要新增 `report_type + retriever + analyzer + schema + route`。
- Orchestrator 不能自主组合多个数据工具。
- Retriever 的能力被服务函数封装死，不能被不同任务复用。
- Critic 只能审核最终报告，难以检查“计划中本该有的证据是否缺失”。
- Draft advice 这类组合型任务会被迫写成一条新固定链路。

典型失败例：

```text
用户：对手选择了 Lina，我要选什么英雄克制？
```

当前系统最多能路由到泛化 `meta_report`，但无法自然规划：

```text
resolve_hero("Lina")
get_hero_matchups(hero=Lina)
filter_candidates_by_role(...)
get_patch_context(latest)
rank_counter_picks(...)
```

---

## 2. v2.5 目标：从 Service Routing 到 Tool Planning

### 2.1 目标主链路

v2.5 主链路：

```text
User Query / Structured Request
  ↓
Orchestrator Agent [LLM]
  - intent 识别
  - evidence 需求规划
  - tool_calls 生成
  ↓
ExecutionPlan
  ↓
ToolExecutor [deterministic]
  - 校验工具名、参数、调用上限
  - 执行 tools
  - 聚合 ToolResult
  ↓
EvidenceGraph / EvidenceBundle
  ↓
Analyzer Agent [LLM + rules]
  - 基于 evidence 生成结论
  ↓
Critic Agent [rules, later LLM]
  - 检查 required_evidence 是否满足
  - 检查 freshness/sample/mock/confidence
  ↓
Formatter Tool
  ↓
Response
```

核心变化：

```text
当前：LLM 选择一个服务，代码走固定链路
目标：LLM 规划多个受约束工具调用，代码执行并校验证据
```

### 2.2 什么叫“受约束”

不能让 LLM 无限制自由调用任意 API。v2.5 的 Tool Calling 必须受约束：

- 工具列表固定。
- 每个工具有严格 schema。
- 每个 intent 有 allowed tools。
- 每个 intent 有 required evidence。
- 每个 plan 有最大 tool call 数。
- 工具执行由代码完成，LLM 不拼 URL、不直接写 SQL。
- ToolExecutor 校验工具名、参数和依赖顺序。
- Critic 检查 required evidence 是否满足，不满足时返回 insufficient data。

---

## 3. Agent 与 Tool 边界

### 3.1 v2.5 组件分类

| 组件 | 类型 | 是否 LLM | 职责 |
|---|---|---:|---|
| Orchestrator / Planner | Agent | 是 | 识别 intent，生成 ExecutionPlan |
| ToolExecutor | Tool runtime | 否 | 校验并执行 tool_calls |
| Data Tools | Tool | 否 | OpenDota、Patch、Hero、Team 等确定性取数 |
| Analyzer | Agent | 是/规则混合 | 基于 evidence 生成回答 |
| Critic | Agent | 规则优先，后续可加 LLM | 审核 evidence completeness 与报告质量 |
| Formatter | Tool | 否 | 输出 API schema / markdown / debug 展示结构 |

### 3.2 Agent 智能化体现在哪里

智能化不体现在“每个服务都有一个类”，而体现在：

- Orchestrator 能根据问题规划工具组合。
- Analyzer 能基于多来源 evidence 生成面向用户目标的答案。
- Critic 能判断计划所需证据是否满足，必要时阻止或降级。

---

## 4. 核心数据结构

### 4.1 ExecutionPlan

```json
{
  "intent": "draft_advice",
  "goal": "Recommend position 4 heroes that synergize with Legion Commander",
  "output_contract": "draft_advice",
  "tool_calls": [
    {
      "id": "t1",
      "tool": "resolve_hero",
      "args": {"name": "Legion Commander"}
    },
    {
      "id": "t2",
      "tool": "get_hero_synergies",
      "args": {"hero_ref": "$t1.hero_id", "role": "support"}
    },
    {
      "id": "t3",
      "tool": "get_patch_context",
      "args": {"patch": "latest"}
    }
  ],
  "required_evidence": [
    "hero_identity",
    "synergy_win_rate",
    "sample_size",
    "role_fit"
  ],
  "constraints": {
    "max_tool_calls": 6,
    "min_sample_size": 100,
    "allow_mock": false
  }
}
```

### 4.2 ToolDefinition

```python
ToolDefinition(
    name="get_hero_synergies",
    description="Return heroes with strong win-rate synergy with a target hero.",
    input_schema=HeroSynergyInput,
    output_schema=HeroSynergyOutput,
    evidence_kinds=["synergy_win_rate", "sample_size"],
)
```

### 4.3 ToolCall

```json
{
  "id": "t2",
  "tool": "get_hero_synergies",
  "args": {
    "hero_ref": "$t1.hero_id",
    "role": "support"
  }
}
```

### 4.4 ToolResult

```json
{
  "tool_call_id": "t2",
  "tool": "get_hero_synergies",
  "status": "ok",
  "records": [
    {
      "hero": "Skywrath Mage",
      "with_hero": "Legion Commander",
      "win_rate": 0.548,
      "sample_size": 1240,
      "role_fit": "position_4"
    }
  ],
  "evidence": [
    {
      "id": "e_synergy_1",
      "kind": "synergy_win_rate",
      "subject": "Skywrath Mage + Legion Commander",
      "value": {"win_rate": 0.548, "sample_size": 1240},
      "source": "stratz",
      "fetched_at": "2026-06-23T00:00:00Z"
    }
  ],
  "missing": []
}
```

### 4.5 EvidenceGraph

v2.5 从单一 EvidenceBundle 演化为 EvidenceGraph：

```json
{
  "intent": "draft_advice",
  "tool_results": [...],
  "evidence": [...],
  "missing": ["lane_matchup_data"],
  "data_quality": {
    "mock_used": false,
    "freshness_days_max": 2,
    "min_sample_size": 1240,
    "completeness": 0.8
  }
}
```

第一版实现时可以继续复用现有 `EvidenceBundle`，但要预留 `tool_results` / `required_evidence`。

---

## 5. Tool Registry 设计

### 5.1 第一批工具

从现有 Retriever 能力拆出工具：

| Tool | 来源 | 用途 |
|---|---|---|
| `resolve_team` | 现有 team resolver | team_name/tag -> candidates/team_id |
| `get_team_report_data` | OpenDotaTeams.get_report_data | 战队近期比赛、英雄、选手、freshness |
| `get_meta_heroes` | OpenDotaHeroes.get_stats_for_role | 按 role 获取英雄 meta 候选 |
| `get_patch_records` | patch_notes loader | 获取版本改动 |
| `verify_claim_rules` | 当前 claim placeholder | 基础 claim rule evidence |

新增 draft 方向工具：

| Tool | 数据源 | 用途 |
|---|---|---|
| `resolve_hero` | OpenDota hero stats / local aliases | 英雄名称标准化 |
| `get_hero_matchups` | STRATZ 或离线 OpenDota Explorer | counter pick 数据 |
| `get_hero_synergies` | STRATZ 或离线 OpenDota Explorer | 搭配数据 |
| `filter_heroes_by_role` | local role map / OpenDota roles | 按位置过滤候选 |

### 5.2 工具命名原则

- 工具名描述数据能力，不描述产品服务。
- 避免 `get_draft_advice` 这类大而全工具。
- 工具输出必须结构化，不能直接输出自然语言结论。
- 工具必须暴露 `source`、`sample_size`、`freshness`、`missing`。

### 5.3 Tool Contract Runtime

`ToolDefinition` 是工具字段契约的唯一事实源：

- `input_model` 负责参数类型和必填字段校验。
- `arg_contracts` 负责字段语义和允许接收的引用来源。
- `output_paths` 负责声明稳定可引用输出，路径必须匹配
  `ToolResult.model_dump(mode="json")` 的 `$<call_id>.<output_path>`。
- `evidence_kinds` 负责声明工具可以产出的 evidence kind。

Planner prompt renderer 和 validator 必须消费同一份 `ToolDefinition`
契约。`resolve_hero`、`stratz.lane_outcome`、`team_id`、`hero_id`
这类业务名只能出现在工具注册 metadata、测试 fixture、prompt 输出断言或
文档中，不能散落在 validator 的 `if call.tool == ...` 业务分支里。

Reference validator 只做通用规则：

```text
$<call_id>.<output_path>
```

- `call_id` 必须指向前序 tool call。
- `output_path` 必须等于源工具 `ToolDefinition.output_paths` 声明的 path。
- 当前参数必须通过 `ArgContract.accepts_refs` 声明接受该
  `from_tool + path + type`。
- 路径拆分和查找语义必须与执行器 `_resolve_reference()` 一致。
- 当前第一版只要求顶层参数引用的 placeholder 类型准确。validator 可以发现
  list/dict 内部的 `$...` 引用，但 `_replace_references()` 对嵌套
  `list[T]` / `dict[K,V]` 元素类型还不是完整类型感知。后续如果允许
  `hero_ids: ["$a.data.hero.hero_id", "$b.data.hero.hero_id"]` 这类列表内引用，
  需要补递归 annotation 传递。

---

## 6. Intent 与 Required Evidence

### 6.0 Intent 语义边界

`intent` 是用户目标的语义标签，不是路由键，也不能选择固定执行路径。
执行路径只由经过校验的 `tool_calls` 决定；响应形态由
`output_contract` 决定；证据义务由 `required_evidence` 和 contract rules
决定。

它不应该表示：

```text
intent=lane_outcome
  -> 走 lane_outcome 专用 pipeline
```

也不应该成为旧时代 `task_type` 的替身：

```text
intent=team_report
intent=meta_report
intent=patch_impact
```

它应该表示更轻量的东西：用户目标/问题类别的语义标签，用来辅助
contract 校验、Critic 解释、trace 可读性、质量策略和 analytics，而不是
决定执行路径。

例如：

```json
{
  "intent": "lane_outcome",
  "output_contract": "natural_language_answer",
  "tool_calls": [
    {"id": "resolve_lina", "tool": "resolve_hero", "args": {"query": "Lina"}},
    {
      "id": "get_lane_outcome",
      "tool": "stratz.lane_outcome",
      "args": {
        "hero_id": "$resolve_lina.data.hero.hero_id",
        "is_with": false
      }
    }
  ],
  "required_evidence": ["hero_identity", "lane_outcome", "sample_size"]
}
```

执行时只看：

```text
resolve_hero -> stratz.lane_outcome -> evidence -> natural_language_answer
```

而不是因为 `intent=lane_outcome` 去找某个 lane outcome branch。

合理用途：

- Trace / observability：让 debug 页面和 logs 显示 planner 认为用户在问什么。
- Contract-level guardrail：例如临时限制某些 output contract 的支持范围。
- Quality policy hint：后续可以按 intent 增加质量阈值。
- Answer framing：自然语言回答可以参考 intent 调整措辞，但不能改变执行路线。
- Analytics：统计用户主要询问 counter、lane、team、patch 等问题。

不允许用途：

- 选择固定 service。
- 决定硬编码 pipeline。
- 替代 `tool_calls`。
- 替代 `required_evidence`。
- 限制 planner 只能从预设 intent 列表里挑一个固定流程。
- 在代码里出现 `if intent == "lane_outcome": run_lane_outcome_flow()`。

核心原则：

```text
intent describes why
tool_calls describe how
output_contract describes response shape
required_evidence describes proof obligations
```

Planner 应从 tool schema 推导必填参数，而不是依赖 intent 专属 example。
例如 `stratz.lane_outcome` 的 `input_model` 要求 `hero_id` 和 `is_with`，
planner 就应该填：

```json
{
  "hero_id": "$resolve_lina.data.hero.hero_id",
  "is_with": false
}
```

当前代码中 `draft_advice` 对 `counter_pick` 的绑定只能视为临时 guardrail。
长期应优先通过 output contract、required evidence 和 evidence quality rules
表达约束，避免把 `intent` 固化成旧链路路由键。

### 6.1 初始 Intent 集合

| Intent | 用户问题 | Required Evidence |
|---|---|---|
| `team_analysis` | “XG 最近打得怎么样？” | team_identity, recent_matches, match_detail_sample, current_players |
| `meta_recommendation` | “当前版本 3 号位练什么？” | hero_stats, role_fit, patch_context |
| `patch_impact` | “7.41d 改了什么？” | patch_records |
| `claim_verification` | “Beastmaster 是强势英雄吗？” | claim_entity, relevant_stats |
| `counter_pick` | “对手 Lina，我选什么克制？” | target_hero_identity, matchup_win_rate, sample_size, role_fit |
| `synergy_pick` | “队友军团，我选什么 4 号位配合？” | ally_hero_identity, synergy_win_rate, sample_size, role_fit |
| `draft_advice` | 同时包含敌方/己方阵容上下文 | hero_identity, matchup, synergy, role_fit, patch_context |

### 6.2 Critic 与 Required Evidence

Critic 不只看最终报告，还要检查：

```text
plan.required_evidence - evidence.kinds = missing_required_evidence
```

如果缺少关键证据：

```json
{
  "severity": "failed",
  "reason": "missing required evidence: synergy_win_rate",
  "retry_hint": "call get_hero_synergies or return insufficient_data"
}
```

---

## 7. 控制流

### 7.1 标准流程

```python
async def run_query(query: str):
    plan = await orchestrator.plan(query, tool_registry)
    validate_plan(plan)

    tool_results = await tool_executor.execute(plan.tool_calls)
    graph = evidence_builder.build(plan, tool_results)

    analysis = await analyzer.analyze(plan, graph)
    review = critic.review(plan, graph, analysis)

    if review.severity == "failed":
        return insufficient_data_or_quality_failure(plan, graph, review)

    return formatter.format(plan, analysis, review)
```

### 7.2 重试策略（后续阶段）

第一版不做自动重试，只做 failed trace。后续可加：

```text
Critic failed due to missing evidence
  ↓
Orchestrator receives retry_hint
  ↓
Plan patch: add tool call
  ↓
execute remaining tools
  ↓
reanalyze
```

必须限制：

```text
max_replans = 1
max_tool_calls_total = 8
same_tool_same_args 不允许重复执行超过 1 次
```

---

## 8. 当前实现到 v2.5 的迁移清单

### 8.1 Domain 新增

新增：

```text
apps/api/app/domain/planning.py
  ExecutionPlan
  ToolCall
  ToolResult
  RequiredEvidence
  PlanValidationError

apps/api/app/domain/tools.py
  ToolDefinition
  ToolRegistry
```

### 8.2 Tool 层新增

新增：

```text
apps/api/app/tools/
  registry.py
  executor.py
  opendota_tools.py
  patch_tools.py
  hero_tools.py
```

现有：

```text
apps/api/app/pipeline/retriever.py
```

逐步迁移为工具实现，不再作为“按 report_type 取数”的主入口。

### 8.3 Orchestrator 修改

当前：

```text
plan_query() -> ReportRequest
```

目标：

```text
plan_query() -> ExecutionPlan
```

中间兼容阶段：

```text
ReportRequest -> LegacyPlanAdapter -> ExecutionPlan
```

这样可以先不破坏 API。

### 8.4 Runner 修改

当前：

```python
if request.task_type == "team_report":
    bundle = retrieve_team(...)
    report = analyze_team(...)
```

目标：

```python
plan = orchestrator.plan(...)
tool_results = tool_executor.execute(plan.tool_calls)
graph = evidence_builder.build(plan, tool_results)
report = analyzer.analyze(plan, graph)
```

### 8.5 Analyzer 修改

当前：

```text
analyze_meta(bundle, role)
analyze_patch(bundle, game, patch)
analyze_team(bundle, game, team_name, time_range)
```

目标：

```text
analyze(plan, evidence_graph) -> AnalysisResult
```

中间阶段可以保留旧方法，由 `analyze(plan, graph)` 分发。

### 8.6 Critic 修改

当前：

```text
review_report(report, bundle)
```

目标：

```text
review(plan, evidence_graph, analysis)
```

新增检查：

- required evidence 是否满足。
- tool failure 是否被解释。
- mock/fallback 是否违反 plan constraints。
- sample size 是否满足 plan constraints。

### 8.7 API Schema 修改

当前 agentic endpoint：

```text
POST /api/v1/plan
```

Request：

```json
{
  "query": "enemy picked Lina, what should I pick?",
  "game": "dota2",
  "include_trace": true
}
```

Response：

```json
{
  "intent": "counter_pick",
  "status": "ok|warning|failed",
  "plan": {...},
  "quality": {...},
  "result": {...},
  "trace": [...]
}
```

---

## 9. 分阶段实施计划

### Stage 0：文档与测试护栏

- 新增本文档。
- 保留现有 API 与测试。
- `/api/v1/plan` route tests 和 `/debug/plan` 继续作为回归入口。

### Stage 1：Planning Domain + Tool Registry 骨架

目标：不改外部 API 行为，只引入内部结构。

- 新增 `ExecutionPlan` / `ToolCall` / `ToolResult`。
- 新增 `ToolRegistry` 和 `ToolExecutor`。
- 把现有 `retrieve_meta`、`retrieve_patch`、`retrieve_team` 包成工具。
- 加 plan validation 单测。

### Stage 2：LegacyPlanAdapter

目标：把现有 `ReportRequest` 映射成 `ExecutionPlan`。

示例：

```text
task_type=team_report
  -> resolve_team
  -> get_team_report_data
```

此阶段外部行为不变，但内部 runner 开始执行 tool_calls。

### Stage 3：Orchestrator 输出 ExecutionPlan

目标：LLM 不再只选 service，而是输出 plan。

- 更新 Orchestrator function schema。
- 限制 allowed tools。
- 加 fallback：LLM plan 失败时走 LegacyPlanAdapter。

### Stage 4：EvidenceGraph + Required Evidence Critic

目标：Critic 开始检查 plan.required_evidence。

- ToolResult 聚合为 EvidenceGraph。
- Critic 检查 required evidence coverage。
- failed 仍先只进入 trace，不阻断 API。

### Stage 5：Draft Advice 能力

目标：实现用户设想的 counter/synergy 场景。

- 新增 `resolve_hero`。
- 新增 `get_hero_matchups` / `get_hero_synergies` 工具。
- 数据源可先用 fixture 或离线样本，后续接 STRATZ/OpenDota Explorer。
- Orchestrator 规划 `counter_pick` / `synergy_pick`。

### Stage 6：Agent API Envelope

目标：对外暴露 v2.5 形态。

- 保留并强化 `/api/v1/plan`。
- 返回 plan、quality、result、trace。
- 不恢复旧 endpoint 兼容。

---

## 10. 与当前代码的映射

| 当前文件 | v2.5 目标 |
|---|---|
| `agentic/planner.py` | Planner：输出 ExecutionPlan |
| `agentic/registry.py` | ToolRegistry / ToolExecutor |
| `agentic/graph.py` | LangGraph StateGraph orchestration |
| `agentic/answer.py` | 从 EvidenceGraph 生成 answer contract |
| `agentic/critic.py` | `review(plan, evidence_graph, answer)` |
| `integrations/opendota/*` | 继续作为底层 client，不暴露给 LLM |
| `api/v1/routes.py` | 只保留 `/plan` |
| `config/policy.yaml` | 增加 planning/tool 限制配置 |
| `resources/plan_console.html` | 展示 plan/tool trace |

---

## 11. 不做什么

v2.5 第一阶段不做：

- 不让 LLM 直接写 SQL。
- 不让 LLM 直接拼外部 API URL。
- 不做无限 replan。
- 不恢复已删除的旧 endpoint。
- 不把所有报告文本都交给 LLM 自由生成。
- 不为了“看起来 Agentic”牺牲 evidence 与 schema 稳定性。

---

## 12. 成功标准

当 v2.5 架构落地后，新增“队友军团我选什么 4 号位配合”不应该再新增一条完整固定 pipeline，而应该是：

```text
新增/接入工具：
  resolve_hero
  get_hero_synergies

Orchestrator 生成 plan：
  resolve_hero -> get_hero_synergies -> get_patch_context

Analyzer 生成 draft_advice
Critic 检查 synergy_win_rate/sample_size/role_fit
Formatter 输出推荐
```

这才是 v2.5 要达到的 Agentic 能力边界。

---

## 13. 一句话总结

> v2.5 的核心不是“更多 Agent”，而是把 Orchestrator 从服务选择器升级为受约束工具规划器：LLM 负责决定需要哪些证据，代码负责安全、可测地获取证据，Critic 负责确认这些证据足够支撑回答。

