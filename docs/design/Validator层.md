# Validator 层工作链路详解

> 本文描述 MetaMind v2.5 架构中的 Validator 层。Validator 是 LLM 计划进入执行环境前的硬边界：它不理解自然语言、不执行工具，只检查 `ExecutionPlan` 是否满足 registry、contract、reference、evidence 和 policy 约束。

## 1. 层定位

Validator 在两处运行：

```text
Planner 内部：
  LLM raw plan -> validate_plan_against_catalog()
  失败时回灌给 LLM retry

Graph 节点：
  validate_plan_node -> validate_plan_against_catalog()
  失败时停止工具执行
```

第一处用于提升 LLM 自修复能力；第二处是运行时保险丝。即使未来 plan 不来自 LLM，也必须先通过 graph validate node。

## 2. 输入与输出

输入：

- `ExecutionPlan`: Planner 产出的结构化计划。
- `ToolRegistry`: 当前注册工具及其契约。
- `policy.yaml`: 全局策略，例如 `stratz.weeks_back_max`。

输出：

- `[]`: 计划可执行。
- `list[str]`: 可读错误列表，用于 planner retry 或 graph error response。

Validator 不返回修正后的 plan，也不做 silent clamp。比如 `weeks_back` 超过上限时，它返回错误，而不是自动改成最大值。

## 3. 两级校验模型

第一层是 Pydantic model validation：

```text
PlannerEnvelope.model_validate(raw)
  -> ExecutionPlan
```

它负责字段形状与基础类型：

- `QueryContext.extra="forbid"`，旧字段如 `week` 会失败。
- `weeks_back: int | None = Field(ge=1)`，下限由 Pydantic 拦截。
- `constraints.max_tool_calls` 有字段范围。
- `ToolCall.id` 和 `ToolCall.tool` 不能为空。

第二层是 catalog validation：

```text
validate_plan_against_catalog(plan, registry)
```

它负责跨对象、跨工具、跨 contract 的语义约束。

## 4. Catalog Validator 总链路

`validate_plan_against_catalog()` 依次执行：

```text
ExecutionPlan
  -> validate_registry_contracts
  -> validate_tool_calls
  -> validate_references
  -> validate_tool_args
  -> validate_output_contract
  -> validate_evidence_producibility
  -> validate_context_scope
  -> errors[]
```

这些检查会累积错误，而不是遇到第一个错误就退出。这样 planner retry 能一次看到更多修正信息。

## 5. Registry Contract 校验

`validate_registry_contracts()` 检查我们自己注册的工具定义是否一致：

- `arg_contracts` 不能引用不存在的 input field。
- `AcceptedRef.from_tool` 必须是已注册工具。
- `AcceptedRef.path` 必须存在于来源工具的 `output_paths`。
- `AcceptedRef.type` 必须与来源 `output_path` 类型一致。
- `AcceptedRef.type` 必须与当前 input field 类型兼容。

这一层不是为了约束 LLM，而是为了保证工具目录本身可信。如果 registry 有错误，所有 plan 都应被拒绝。

## 6. Tool Calls 基础校验

`validate_tool_calls()` 检查：

- 每个 `tool_call.id` 唯一。
- 每个 `tool_call.tool` 已注册。
- `constraints.allow_mock` 必须为 false。
- 实际 tool call 数不能超过 `constraints.max_tool_calls`。

这里体现 v2.5 的执行约束：LLM 不能发明工具、不能无限调用、不能打开 mock 逃逸口。

## 7. Reference 校验

`validate_references()` 递归扫描 tool args 内所有 `$...` 引用。

合法引用形态：

```text
$<previous_call_id>.<declared_output_path>
```

校验规则：

- 引用字符串必须能被 `parse_reference()` 解析。
- `call_id` 必须指向前序 tool call。
- 来源 tool 必须已注册。
- `output_path` 必须是来源工具声明过的 output path。
- 当前参数必须通过 `ArgContract.accepts_refs` 声明接受该来源。
- `from_tool + path + type` 必须完全匹配。

因此，下面这种调用是允许的：

```json
{
  "id": "matchups",
  "tool": "stratz.hero_matchup_ranking",
  "args": {
    "hero_id": "$resolve_lina.data.hero.hero_id"
  }
}
```

前提是 `resolve_lina` 出现在前面，`resolve_hero` 声明了 `data.hero.hero_id`，且 `stratz.hero_matchup_ranking.hero_id` 接受这个 ref。

## 8. Tool Args 校验

`validate_tool_args()` 检查每个 tool call 的 args 是否符合目标工具的 `input_model`。

流程：

```text
args
  -> unknown arg check
  -> replace "$ref" with type placeholder
  -> input_model.model_validate()
```

为什么要替换 `$ref`？

Validator 阶段还没有执行前序工具，因此无法拿到真实值。它用 `_placeholder()` 生成类型兼容的占位值，例如：

- `int` -> `1`
- `str` -> `"ref"`
- `bool` -> `False`
- `list` -> `[]`

这样既能允许引用，又能触发 input model 的结构校验。例如某工具要求 `hero_id` 和 `position_id` 二选一，这类 Pydantic `model_validator` 会在这里生效。

当前限制：

- 顶层 `$ref` 类型校验是主要保障。
- list/dict 内部引用能被发现，但 placeholder 对嵌套元素类型还不是完全类型感知。

## 9. Output Contract 校验

`validate_output_contract()` 调用 `validate_contract_plan_with_evidence()`。

它检查：

- `output_contract` 必须存在。
- `required_evidence` 不能包含未知 evidence kind。
- structured contract 必须包含契约要求的 evidence。
- 如果 contract 有 `allowed_evidence`，不能使用 allowlist 外的 evidence。
- 如果 contract 有 `required_tools`，plan 必须调用这些工具。

自然语言 contract `natural_language_answer` 较宽：它不预设固定 evidence，但仍要求 `required_evidence` 是已知 evidence kind。

## 10. Evidence Producibility 校验

`validate_evidence_producibility()` 检查 required evidence 是否真的能由选中工具产生：

```text
selected_tools.evidence_kinds
  vs
plan.required_evidence
```

如果 Planner 声明：

```json
"required_evidence": ["pair_lane_winrate"]
```

却没有选择任何能产出 `pair_lane_winrate` 的工具，validator 会报错。

这层防止 LLM 在 `required_evidence` 里“许愿”。

## 11. Context Scope 校验

`validate_context_scope()` 检查全局 context 是否符合 policy。

当前重点是 STRATZ 时间窗口：

```text
plan.context.weeks_back <= policy.stratz.weeks_back_max
```

下限 `weeks_back >= 1` 由 Pydantic 处理；上限来自业务策略，默认建议为 8。超限时返回明确错误，触发 planner retry。

Validator 不负责把 `weeks_back` 解析成具体 week epoch。这个动作属于 STRATZ tool handler。

## 12. Graph 中的失败路径

`validate_plan_node` 的行为：

```text
if plan is None:
  state.status = "error"
  state.errors += ["missing execution plan"]
  -> response/evidence path

errors = validate_plan_against_catalog(plan, registry)
if errors:
  state.status = "error"
  state.errors += errors
  -> evidence_node
else:
  state.status = "ok"
  -> tool_executor_node
```

Validator 失败后不会执行工具。Graph 仍可进入 evidence node 以形成统一响应结构，但 `tool_results` 为空，最终 response type 会是 execution error。

## 13. 层边界

Validator 负责：

- 契约一致性。
- 工具存在性。
- 参数 schema。
- 引用合法性。
- output contract 合法性。
- required evidence 可产出性。
- context policy。

Validator 不负责：

- 判断用户意图是否合理。
- 选择工具。
- 执行工具。
- 解析真实 `$ref` 值。
- 判断证据是否真实充分。
- 生成回答。

不要在 validator 里写业务路由分支，例如：

```text
if intent == "lane_outcome": ...
```

这会把 `intent` 重新变成旧的 `task_type`。

