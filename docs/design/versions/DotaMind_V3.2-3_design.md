# DotaMind V3.2-3 有界缺证 Recovery/Replan 设计

> 状态：已实现，待最终提交验收。本文是 V3.2-3 的阶段实施蓝图；总体阶段顺序和
> 后续幂等、Redis、可观测性边界以
> [`DotaMind_V3.2_design.md`](./DotaMind_V3.2_design.md) 为准。

## 1. 阶段目标

V3.2-3 首版只关闭一个真实可达的运行缺口：

> Attempt 0 因全局 required evidence 缺失而终止，并且 Registry 中存在此前未使用、
> 能覆盖全部缺口的工具时，允许 Controller 追加补证调用并启动唯一一次 Attempt 1。

该阶段保持 v2.5 constrained tool calling 不变量：`intent` 只是语义标签，执行完全由
校验后的 `tool_calls` 决定，响应形状由 `output_contract` 决定，证据义务由 contract、
plan 和 Registry 共同决定。

## 2. 明确非目标

- 不实现 Critic Recovery 或 Critic `issue_codes`；等出现稳定且 Graph 可达的结构化
  质量失败码后再设计。
- 不重试工具错误，不 fallback、换源或静默放宽用户约束。
- 不允许超过一次 Replan，不引入通用 autonomous loop。
- 不增加业务工具、intent 路由、第二个 Reviewer 或自然语言约束解析器。
- 不增加跨 Run cache、`request_id`、Redis、指标系统或 in-flight 强制取消。
- 不增加 `reused_tool_result_ids`、duplicate 配置开关或工具级 TraceEvent。

## 3. 运行图与 Attempt 生命周期

```text
业务节点
  -> attempt_finalize
  -> recovery
      -> terminal -> run_finalize -> response
      -> replan   -> attempt_reset -> controller
```

- `attempt_finalize` 只解析并封存当前 Attempt，追加一次不可回写的 `AttemptRecord`。
- `recovery` 是确定性规则节点，不调用 LLM。
- `attempt_reset` 只调用 `reset_attempt_working_state()`，不维护第二套 reset 逻辑。
- `run_finalize` 不创建 Attempt，只归约最终公开终态和 Run 总耗时。
- Run 只能产生 `[Attempt 0]` 或 `[Attempt 0, Attempt 1]` 两种连续记录。
- Graph 只有 `attempt_reset -> controller` 一条受控回边。

## 4. Recovery 分类

Attempt 0 只有同时满足以下条件才进入 Replan：

1. 当前终态是 evidence 缺失。
2. 所有 missing 项都是全局/effective evidence kind；不含
   `<call_id>:<kind>`、tool failure 或 extractor failure。
3. 每个 missing kind 都存在本计划尚未使用、声明可产出该 kind 的注册工具。
4. monotonic deadline 尚未到达。
5. replan、Controller budget 均有剩余，且 `min(Run 剩余 tool budget, 原 plan 的
   max_tool_calls 剩余容量)` 足以容纳覆盖全部缺口的最小未使用 producer 集合。

固定终态映射：

| 场景 | 公开结果 |
|---|---|
| Attempt 0 缺证但无未使用 producer | `insufficient_evidence / insufficient_evidence` |
| 缺口可恢复但 replan/controller/tool budget 不足 | `insufficient_evidence / replan_exhausted` |
| Attempt 1 仍缺证 | `insufficient_evidence / replan_exhausted` |
| Attempt 执行中的新 handler 超过预算 | `error / execution_budget_error` |
| 相同 fingerprint 换 call id | `error / execution_budget_error` |
| deadline 到达 | `error / execution_timeout` |
| Controller/validation/tool/Answer 错误 | 保持原错误类型 |

Recovery 不覆盖已经发生的 tool、Answer 或 Critic 错误。

## 5. RecoveryFeedback 与 Controller 消息

首版只有一个机器码：

```text
RecoveryCode = "missing_evidence"
```

内部反馈固定为：

```json
{
  "code": "missing_evidence",
  "failure_stage": "evidence",
  "missing_evidence": ["sample_size"],
  "executed_calls": [
    {"id": "matchup", "tool": "stratz.hero_matchup_ranking", "status": "ok"}
  ],
  "remaining_tool_budget": 3,
  "replan_index": 1
}
```

第二次 Controller 调用的消息顺序固定为：

```text
system: 与 Attempt 0 相同的 system prompt
user: 原 query/game/history envelope
assistant: Attempt 0 已接受的完整 ControllerDecision JSON
user: recovery rules + RecoveryFeedback JSON
```

`controller.recovery_rules=v1` 进入 `RunContext.prompt_versions`。Recovery 动态内容不
进入 system hash、日志、公开响应、AttemptRecord 或 Session。System prompt 正文和
V3.2-2 golden fixture保持不变。

## 6. Replan 不变量

Attempt 1 必须返回完整 `tool_plan`，并满足：

- `intent`、`goal`、`output_contract`、`context`、`constraints` 完全一致。
- `required_evidence` 规范化后完全相等，不允许增加或删除。
- Attempt 0 全部调用以相同顺序、`id/tool/args` 作为完整前缀。
- 至少追加一个调用；新 id 不与旧 id 重复。
- 追加工具此前未在计划中使用，追加数量不超过 Run 与原 plan 剩余容量的较小值。
- 每个追加工具都至少声明一种 `missing_evidence`；它们的 evidence kinds 合集覆盖
  所有 `missing_evidence`。
- 完整候选计划重新经过 sample policy、catalog、contract、reference、args 和
  producibility 校验。

不维护 Recovery 专用 `allow_mock` 规则；constraints 完全相等和通用计划校验已经覆盖。

## 7. 指纹、复用与 duplicate

Run 内工具指纹固定为：

```text
sha256(canonical_json({
  "tool": tool_name,
  "args": resolved_args,
  "context": full_query_context
}))
```

Canonical JSON 使用 UTF-8、稳定 key 排序和紧凑分隔符。引用先解析，call id 不进入
指纹；args 或 context 变化必须改变指纹。

`executed_call_fingerprints` 保存当前 Run 的成功或失败结果：

- 相同 fingerprint、相同 call id、成功：复制结果，`latency_ms=0`，不进入 handler，
  不增加工具预算。
- 相同 fingerprint、相同 call id、失败：复用失败结果，不重试。
- 相同 fingerprint、不同 call id：阻断并返回 `execution_budget_error`。
- cache 只存在于内部 state，不进入 Attempt payload、公开响应或持久化。

公开复用状态只来自 dispatch summary：`attempts[].tool_call_statuses[].reused`。

## 8. Deadline 与预算 Guard

Graph wrapper 在以下节点入口统一检查 monotonic deadline：

```text
controller / decision validation / plan validation / conversation answer
tools / evidence / answer / critic
```

- Controller 和 Answer 入口同时检查各自预算。
- tools 入口检查 deadline；每个未复用、已经通过 Registry/input validation 的 handler
  进入前再次检查 deadline 和 tool budget。
- `attempt_reset` 在 Attempt 1 启动前再次检查 deadline。
- 允许越过 guard 的收口路径只有 `attempt_finalize`、Recovery terminal、
  `run_finalize` 和 `response`。
- 已经开始的 LLM/HTTP/handler 不强制取消；返回后由下一个入口 guard 归约。

## 9. 状态与公开接口

内部 state 增加：

```text
recovery_action
recovery_feedback
recovery_baseline_decision
executed_call_fingerprints
runtime_failure_code
```

`recovery_code` 表示“当前 Attempt 因何被启动”：

- Attempt 0 永远为 `null`。
- 实际启动的 Attempt 1 为 `missing_evidence`。
- Recovery 未启动 Attempt 1 时，不回写 Attempt 0。
- `attempt_finalize` 后不得修改历史 AttemptRecord。

公开 runtime 增加：

```text
attempts[].recovery_code: "missing_evidence" | null
attempts[].tool_call_statuses[].reused: bool
```

顶层 plan/tool results/evidence/answer/review 始终来自最终 Attempt；早期 Attempt 仅公开
allowlist 摘要。`/debug/plan` 继续消费 runtime JSON，不新建兼容 UI。

## 10. 隐私边界

下列内部内容不得进入公开 DTO、trace、Session、AttemptRecord 或持久化：

- RecoveryFeedback 正文和完整 baseline decision；
- fingerprint 和结果 cache；
- Prompt 正文、validation/retry feedback 和原始模型 output；
- history 全文、早期 Attempt 的完整 ToolResult data 和 Critic reasons。最终 Attempt 的
  顶层 `tool_results` 保持既有公开语义。

现有 attempt-local Controller diagnostics 继续保持内部瞬态语义。

## 11. 验收矩阵

使用合成 Registry、FakeController/FakeClock 和参数化用例，不依赖 STRATZ 动态数值：

1. 缺证后补证成功，产生两个 Attempt，旧成功 handler 只进入一次。
2. Attempt 1 仍缺证，返回 `replan_exhausted`，没有 Attempt 2。
3. 无未使用 producer 时保持单 Attempt `insufficient_evidence`。
4. replan/controller/tool budget 或原 plan 的 `max_tool_calls` 剩余容量不足时返回
   `replan_exhausted`。
5. 前缀、scope、contract、constraints、required evidence、每个追加工具的相关性和
   coverage 不变量均被校验。
6. duplicate、失败复用、fingerprint canonicalization 和预算计数准确。
7. 共享入口、逐 handler 和 Attempt 1 启动 deadline guard 均可确定性验证。
8. deadline 后仍能完成 attempt/recovery/run/response 收口。
9. Reset 保留 RunContext、Budget、history、attempts、trace、feedback、baseline 和 cache。
10. 公开 1/2 Attempt、`recovery_code`、`reused` 与隐私 allowlist 正确。
11. 初次 Controller system golden/hash 不变，Recovery renderer 版本进入 manifest。
12. 既有单 Attempt、safe failure、错误优先级和 Session 隐私回归全部通过。

## 12. 完成定义

- Graph 只有一条受控回边，Run 最多两个 Attempt。
- 只有真实可达的全局 missing-evidence 路径能够 Replan。
- 成功工具调用不会重复访问上游，失败调用不自动重试。
- `replan_exhausted`、`execution_budget_error`、duplicate 和 deadline 语义区分准确。
- 历史 Attempt 封存后不回写。
- Critic Recovery、工具重试、幂等和 Redis 均未接入。
- `ruff check .`、完整 `pytest`、`uv lock --locked`、`git diff --check` 全部通过。
- 总设计、技术/API 文档和当日中英文进度快照保持一致。
