# Validator 层

校验分为启动期、Controller 候选期和 Graph 重复校验期。

## 启动期 registry 校验

PlanService 构建完整 ToolRegistry 后执行一次 fail-fast 校验：

- mandatory evidence 必须属于工具声明的 evidence kinds；
- 声明 mandatory evidence 的工具必须有 extractor；
- evidence-producing 工具必须声明 source；
- accepted refs 的工具、路径和类型必须一致；
- contract required evidence 必须属于 registry 已知 kind。

## Controller 候选校验

ControllerDecision 先经 Pydantic discriminator 解析。tool plan 应用 sample
policy 后，计算：

```text
effective_required_evidence =
  contract evidence ∪ selected-tool mandatory evidence ∪ plan evidence
```

随后校验 decision 约束、tool call、参数、引用、output contract 和 effective
evidence producibility。失败可进入有限 LLM retry。

EvidenceGraph 的实际覆盖检查分两层：contract/plan evidence 按全局 kind 检查；
registry mandatory evidence 按每个成功 `tool_call_id` 检查。缺失项使用
`<call_id>:<kind>`，避免同类多次调用相互借用 evidence。

## Graph 重复校验

`decision_validate_node` 与 `validate_plan_node` 只验证 Controller 已接受的
最终对象，不补参数、不改 metadata。它会把重新计算的 authoritative evidence
义务覆盖写回 state，避免自定义 Controller 或测试替身绕过最低义务。校验失败直接
进入 response，不创建 EvidenceGraph。

## 结果优先级

```text
planning_error
> decision_validation_error
> tool_error
> answer_error
> insufficient_evidence (missing)
> insufficient_evidence (critic quality)
> success
```
