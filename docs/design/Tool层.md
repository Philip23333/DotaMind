# Tool 层工作链路详解

> 本文描述 MetaMind v2.5 架构中的 Tool 层。Tool 层是确定性执行边界：Planner 只声明要调用什么工具，Tool 层负责解析引用、校验参数、调用 handler、捕获错误，并把结果封装成 `ToolResult`。

## 1. 层定位

Tool 层位于 validator 之后、evidence 之前：

```text
validate_plan_node
  -> tool_executor_node
  -> ToolExecutor
  -> ToolDefinition.handler
  -> ToolResult[]
  -> evidence_node
```

它的职责是执行经过校验的 `tool_calls`，但不负责最终解释结果。

## 2. ToolDefinition 是能力契约

每个工具由 `ToolDefinition` 注册：

```python
ToolDefinition(
    name="stratz.hero_matchup_ranking",
    description="...",
    input_model=HeroMatchupRankingInput,
    handler=_hero_matchup_ranking_handler(settings),
    source=ToolSource(...),
    evidence_extractor=hero_matchup_ranking_evidence,
    evidence_kinds=("matchup_ranking_row", "sample_size"),
    arg_contracts={...},
    output_paths={...},
    metadata={...},
)
```

字段含义：

- `name`: Planner 可见的工具名。
- `description`: Planner 用来理解能力边界的文字。
- `input_model`: 参数 schema，由 Pydantic 校验。
- `handler`: 实际执行函数。
- `source`: 数据来源。
- `evidence_extractor`: ToolResult -> EvidenceItem 的转换器。
- `evidence_kinds`: 该工具能产出的证据类型。
- `arg_contracts`: 参数语义和可接受引用来源。
- `output_paths`: 后续工具可引用的稳定输出路径。
- `metadata`: trace 和结果附加元信息。

ToolDefinition 同时服务三层：

```text
Planner prompt renderer
Validator
ToolExecutor / EvidenceGraph
```

因此它是工具契约的单一事实源。

## 3. Registry 构建链路

当前默认 registry 由 `build_default_tool_registry(settings)` 构建：

```text
ToolRegistry()
  -> register_stratz_tools
  -> register_opendota_tools
  -> register_patch_tools
```

`PlanService` 初始化时创建 registry，并把同一份 registry 传给：

- `AgenticPlanner`
- `AgentGraphRunner`
- `ToolExecutor`
- `EvidenceGraph` builder

这保证 Planner 看见的工具目录、Validator 校验的目录、Executor 执行的目录一致。

## 4. ToolExecutor Node 链路

`tool_executor_node` 接收已通过 validator 的 `state.plan`：

```text
for call in plan.tool_calls:
  resolved_args = _resolve_args(call.args, previous_results)
  result = executor.execute(ToolCall(call.id, call.tool, resolved_args), context)
  state.tool_results.append(result)
  previous_results[call.id] = result
```

执行顺序就是 `tool_calls` 数组顺序。

如果某个调用的引用解析失败：

- 该调用被跳过。
- 错误写入 `state.errors`。
- 后续依赖它的调用也会因为 reference target unavailable 失败。

如果任一工具返回 `status="error"`：

- 错误写入 `state.errors`。
- node 最终 `state.status="error"`。
- graph 进入 evidence node，不继续正常 answer 链路。

## 5. Runtime Reference 解析

Validator 只验证 `$ref` 合法性；Tool node 才解析真实值。

解析规则：

```text
$<call_id>.<path>
```

例如：

```json
"hero_id": "$resolve_lina.data.hero.hero_id"
```

Runtime 查找流程：

```text
parse_reference()
  -> results_by_id[call_id]
  -> result.status must be ok
  -> lookup_path(result.model_dump(mode="json"), path_parts)
  -> resolved value
```

如果引用目标不存在、目标工具失败、或 path 找不到，就返回解析错误。

## 6. ToolExecutor 执行单个工具

`ToolExecutor.execute(call, context)` 的内部流程：

```text
registry.get(call.tool)
  -> definition.input_model.model_validate(call.args)
  -> definition.handler(validated_args, context)
  -> await if awaitable
  -> ToolResult(status="ok", data=data, source=source, metadata=metadata)
```

如果过程中抛异常：

```text
Exception
  -> ToolResult(status="error", error="TypeError: ...")
```

ToolExecutor 不抛出业务异常给上层，而是把异常结构化为 `ToolResult`，让 evidence/critic/response 能统一处理。

## 7. QueryContext 的作用

`QueryContext` 是 plan-level scope，不属于单个 tool args：

```json
"context": {
  "bracket": ["DIVINE_IMMORTAL"],
  "weeks_back": 2,
  "position_ids": ["POSITION_4"],
  "region_ids": null,
  "game_mode_ids": null
}
```

Tool handler 接收：

```python
handler(validated_args, context)
```

这样同一个 scope 可以应用到 plan 中多个工具，Planner 不需要把 bracket、weeks_back 等重复塞进每个 tool args。

STRATZ 特别规则：

- Planner 只输出 `weeks_back`。
- STRATZ handler 解析最近 N 个已完成 week epoch。
- 每个 epoch 单独调用底层 STRATZ client。
- 返回 per-week bucket，并在 filters/evidence 中标注完整周口径。

## 8. 底层 integration 与 agentic tool 的边界

底层 integration 负责 provider-native API：

```text
app/integrations/stratz/heroes.py
app/integrations/opendota/*
```

Agentic tool 负责把 provider 能力包装成 v2.5 工具：

```text
app/agentic/tools/stratz_tools.py
app/agentic/tools/opendota_tools.py
app/agentic/tools/patch_tools.py
```

LLM 不直接接触底层 client，不知道 URL、GraphQL body 或 token。它只看 ToolDefinition 渲染出的工具目录。

## 9. ToolResult 结构

工具返回统一包装：

```json
{
  "tool_call_id": "matchups",
  "tool": "stratz.hero_matchup_ranking",
  "status": "ok",
  "data": {...},
  "source": {
    "name": "STRATZ",
    "kind": "public_graphql_api",
    "url": "..."
  },
  "latency_ms": 123,
  "error": null,
  "metadata": {...}
}
```

`data` 是工具自己的结构化结果。Evidence 层通过对应 extractor 读取它。

## 10. 失败路径

```text
unknown tool
  -> Validator 应提前拦截
  -> Executor 若遇到仍返回 ToolResult error

args invalid
  -> Validator 应提前拦截
  -> Executor 再次 model_validate，失败返回 ToolResult error

reference target failed
  -> tool node 解析失败
  -> state.errors

upstream API error
  -> handler 抛错
  -> ToolResult(status="error")

missing token / config
  -> handler 抛错
  -> ToolResult(status="error")
```

项目偏好是暴露错误，而不是用 mock 或 fallback 掩盖缺口。

## 11. 层边界

Tool 层负责：

- 解析真实 `$ref` 值。
- 校验并执行工具参数。
- 调用 deterministic handler。
- 捕获 upstream/config/runtime 错误。
- 返回结构化 ToolResult。

Tool 层不负责：

- 自然语言回答。
- 判断 required_evidence 是否满足。
- 生成 EvidenceGraph。
- 根据 `intent` 选择固定 pipeline。
- 把 upstream 错误伪装成成功。

## 12. 新增工具流程

推荐步骤：

1. 定义 `input_model`。
2. 实现 deterministic `handler(args, context)`。
3. 声明 `ToolSource`。
4. 声明 `evidence_extractor` 和 `evidence_kinds`。
5. 如需被后续工具引用，声明 `output_paths`。
6. 如需接收前序工具引用，声明 `arg_contracts.accepts_refs`。
7. 注册到默认 registry。
8. 增加 validator、executor、evidence tests。

