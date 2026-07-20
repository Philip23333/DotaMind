# DotaMind V3.2-2：Prompt Registry

## 目标

将 Controller 的 Prompt 组成、retry feedback 与审计版本从 Controller 实现中拆出，
在不改变 Graph、公开 API、Attempt 数量或终态语义的前提下，提供可复现的 Prompt
配置证据。

## 实现边界

- `prompts.controller` 负责 system prompt、catalog/contract/sample-policy 组合和用户消息渲染。
- `prompts.feedback` 保留既有 validation retry 文本，并提供尚未接线的 recovery rules renderer。
- `prompts.versions` 记录 renderer 版本，并对完整 configured/prepared system prompt 的 UTF-8
  bytes 计算 SHA-256。
- `controller.system.sha256` 证明本 Run 已配置并准备使用的 Prompt；不证明 LLM 请求已发送、
  到达模型或成功返回。
- 动态 query、game、history、validation errors 与 retry messages 不进入 hash；对应 renderer
  仅由版本键覆盖。

## Registry 不变量

`AgentController` 在渲染并缓存 Prompt bundle 前调用 `ToolRegistry.freeze()`。冻结后
`register()` 稳定抛出 `RuntimeError`；ToolDefinition 的 arg contracts、output paths 与
metadata 被深度只读快照替换，而 get/list、validation、executor 与 evidence 的读取行为不变。
Controller 同时持有只读 Contract Registry 和 Sample Policy 快照。因此：

```text
Prompt catalog = validation catalog = executor catalog
```

## Run 审计

`controller_node` 在调用 Controller 前复制 prompt manifest 到
`RunContext.prompt_versions`，所以 LLM disabled 的 planning error 也保留同一份
configured/prepared 审计信息。当前 manifest 包含 base、conversation、catalog、contract、
sample-policy、history、user-message、validation-retry renderer 版本、system SHA-256，以及只含
`history_window` / `history_max_chars` 的 history-policy SHA-256。
`recovery_rules` 具有独立版本，但在 V3.2-2 仍是 dormant，绝不进入 Prompt、messages 或 manifest。

## 隐私与非目标

不新增 Prompt 正文存储。Prompt、validation errors 与模型输出不进入 manifest、AttemptRecord、
公开 DTO、trace、Session 或持久化存储；既有 attempt-local Controller diagnostics 保持内部瞬态。
本阶段不引入 recovery/replan、第二 Attempt、预算 gate、registry fingerprint 或 API 字段。

## 验收

golden fixture 必须为 UTF-8、无 BOM、LF，并按原始 bytes 与默认 frozen registry/policy 的
完整 system prompt 比较。测试覆盖 enabled/disabled manifest、实际发送 system message hash、
冻结后注册失败、双向 fresh-import，以及 tool/contract/sample-policy 变化改变 hash。
