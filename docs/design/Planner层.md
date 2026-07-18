# Planner 层工作链路详解

> 本文描述 DotaMind v2.5 架构中的 Planner 层。Planner 是 LLM 驱动的规划器，但它只负责产出受约束的 `ExecutionPlan`，不执行工具、不取数、不拼外部 API，也不决定固定业务 pipeline。

## 1. 层定位

Planner 层位于用户请求进入 agentic graph 后的第一站：

```text
POST /api/v1/plan
  -> PlanService
  -> AgentGraphRunner
  -> planner_node
  -> AgenticPlanner.plan()
  -> ExecutionPlan / insufficient_tools / error
```

它的职责是把自然语言问题转换成结构化计划：

```text
用户目标
  -> intent 语义标签
  -> output_contract 响应形态
  -> context 全局过滤条件
  -> tool_calls 工具调用序列
  -> required_evidence 证据义务
  -> constraints 执行约束
```

核心原则：

```text
intent describes why
tool_calls describe how
output_contract describes response shape
required_evidence describes proof obligations
```

`intent` 不是路由键，不能触发固定分支。执行路线只由通过校验的 `tool_calls` 决定。

## 2. 输入与输出

输入：

- `query`: 用户自然语言问题。
- `game`: 当前游戏标识，默认 `dota2`。
- `ToolRegistry`: 当前可用工具目录。
- `policy.yaml`: LLM 温度、token、planner retry 次数等策略。

输出：

- `status="planned"`: 返回合法的 `ExecutionPlan`。
- `status="insufficient_tools"`: 当前工具无法支撑问题，直接暴露能力边界。
- `status="error"`: LLM 或计划格式/校验失败。

Planner 的 public result 是 `AgenticPlannerResult`，随后由 `planner_node` 写入 `AgentRunState.planning`、`state.plan`、`state.reason` 和 `state.errors`。

## 3. Prompt 构建链路

Planner prompt 不是手写完整工具说明，而是由静态模板加 registry 渲染组成：

```text
_PLANNER_SYSTEM_PROMPT
  + render_planner_tools(registry)
  + render_planner_contracts(registry)
  -> final system prompt
```

`render_planner_tools()` 从每个 `ToolDefinition` 读取：

- `name`
- `description`
- `input_model` 字段
- `arg_contracts`
- `output_paths`
- `evidence_kinds`

`render_planner_contracts()` 从 output contract catalog 读取：

- contract 名称
- route 类型
- required evidence
- allowed evidence

因此，Planner 看到的工具能力来自同一份 registry 契约；新增工具时应优先更新 `ToolDefinition`，而不是在 prompt 里硬编码新规则。

## 4. LLM 返回 envelope

Planner 要求 LLM 只返回 JSON，形态之一：

```json
{
  "status": "insufficient_tools",
  "reason": "...",
  "plan": null
}
```

或：

```json
{
  "status": "planned",
  "reason": "...",
  "plan": {
    "intent": "...",
    "goal": "...",
    "output_contract": "natural_language_answer",
    "context": {
      "bracket": ["DIVINE_IMMORTAL"],
      "weeks_back": 2,
      "position_ids": null,
      "region_ids": null,
      "game_mode_ids": null
    },
    "tool_calls": [
      {
        "id": "resolve_lina",
        "tool": "resolve_hero",
        "args": {"query": "Lina"}
      },
      {
        "id": "matchups",
        "tool": "stratz.hero_matchup_ranking",
        "args": {"hero_id": "$resolve_lina.data.hero.hero_id"}
      }
    ],
    "required_evidence": ["hero_identity", "matchup_ranking_row", "sample_size"],
    "constraints": {"max_tool_calls": 6, "allow_mock": false}
  }
}
```

这里的 `weeks_back` 是 STRATZ 的相对时间窗口，LLM 不输出 raw STRATZ week epoch。后端工具层负责解析为具体已完成周。

## 5. Planner 内部校验与重试

LLM 返回后，Planner 先做 Pydantic envelope 校验：

```text
raw JSON
  -> PlannerEnvelope.model_validate()
  -> ExecutionPlan / ValidationError
```

这一层会挡住：

- envelope 形状错误。
- `planned` 但 `plan=null`。
- `context` 出现未知字段。
- `weeks_back=0` 这类字段范围错误。
- `ToolCall.id` 或 `tool` 为空。

如果 envelope 合法，再进入 catalog validator：

```text
ExecutionPlan
  -> validate_plan_against_catalog(plan, registry)
  -> [] / errors
```

如果 validator 返回错误，Planner 会把错误作为 `_retry_feedback()` 追加到消息中，让 LLM 重新输出完整 plan。重试次数来自：

```text
policy.llm.orchestrator.planner_max_retries
```

可重试错误包括：

- JSON decode error。
- envelope shape error。
- `planned` 缺失 plan。
- catalog validation errors。

终止状态：

- `insufficient_tools`: 直接返回，不重试。
- 显式 `error`: 直接返回，不重试。
- LLM transport/runtime exception: 直接返回 error。
- retry 耗尽: 返回最后一次错误。

## 6. Graph 中的 Planner 节点

`planner_node` 接收 `AgentRunState`：

```text
AgentRunState(query, game)
  -> planner.plan(query, game)
  -> state.planning
  -> state.plan
  -> state.status
```

路由规则：

```text
if state.status in {"error", "insufficient_tools"}:
  -> response_node
else:
  -> validate_plan_node
```

这意味着 planner 如果暴露能力边界或返回错误，不会进入工具执行。

## 7. 与相邻层的边界

Planner 层负责：

- 识别用户目标。
- 选择 output contract。
- 规划工具调用序列。
- 填写工具参数或 `$ref`。
- 声明 required evidence。
- 设置全局 context。

Planner 层不负责：

- 校验工具是否真实存在。
- 解析 `$ref`。
- 执行工具。
- 访问 STRATZ/OpenDota。
- 计算 STRATZ week epoch。
- 合并或解释工具结果。
- 判断最终回答是否可靠。

## 8. 失败路径

```text
LLM JSON 无法解析
  -> retry feedback
  -> retry exhausted => planner error

Pydantic 校验失败
  -> retry feedback
  -> retry exhausted => planner error

Catalog validator 失败
  -> retry feedback
  -> retry exhausted => planner error

工具能力不足
  -> insufficient_tools
  -> response_node
```

## 9. 扩展规则

新增能力时，优先顺序是：

1. 新增 deterministic tool。
2. 在 `ToolDefinition` 声明 input/output/evidence/ref 契约。
3. 如需要，新增或扩展 output contract。
4. 让 prompt renderer 自动暴露新能力。
5. 用 validator tests 确认错误 plan 会被拒绝。

不要通过下面方式扩展：

- 在 `intent` 上增加固定分支。
- 在 Planner prompt 里硬编码某个工具的复杂业务流程。
- 让 LLM 直接拼 URL、SQL 或 provider-specific epoch。

