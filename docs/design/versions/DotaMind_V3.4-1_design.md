# DotaMind V3.4-1 — ChatRun Checkpoint 试点

## 阶段 0 契约

本阶段只冻结动态执行试点所需的 Checkpoint 与 ChatRun 状态契约，不改变
Graph 的执行入口，不接入具体 ambiguous 适配器，也不提供前端交互。

Checkpoint 是 ChatRun 内部的持久化暂停状态，不是新的 Run 类型：

```text
queued -> running -> waiting_input -> running -> completed
```

`waiting_input` 仍属于活跃 Run，但不持有 Worker、session lease 或 heartbeat，
也不参与失联 Run 扫描。

## Checkpoint 契约

```python
class CheckpointOption(BaseModel):
    id: str
    label: str
    value: dict[str, Any]

class Checkpoint(BaseModel):
    checkpoint_type: str
    question: str
    options: list[CheckpointOption]
    source_tool_call_id: str
    resume_node: Literal["controller", "tools"]
```

阶段 0 的持久化 `CheckpointSnapshot` 只包含恢复所需的 plan、成功工具结果、
dispatch records、RunBudget、attempt 信息和 fingerprint cache。Prompt、raw model
output、历史上下文和 Answer 不进入快照。

resume 请求只携带：

```json
{
  "checkpoint_type": "pandascore_match_selection",
  "option_id": "..."
}
```

服务端必须从当前 Run 的 Checkpoint 校验 option；客户端不能提交日期或任意 Plan
patch。resume handler 和 Graph 恢复执行属于后续阶段，阶段 0 仅提供其稳定模型、
数据库字段和状态集合。

## 持久化边界

`chat_runs.checkpoint_state` 为 nullable JSONB。活跃 Run 的 session 唯一索引包含
`waiting_input`，因此等待用户选择时同一 session 不能创建另一个 Run。

进入等待状态时，后续实现必须先写入快照，再发布 Checkpoint/status 事件，最后释放
Worker lease。恢复时使用同一个 `run_id`；前序结果缓存的复用和源工具重跑由阶段 1
实现。

## 非目标

- 不接入英雄、赛事、战队或跨源映射的其它 ambiguous。
- 不做 Controller 二次调用、自动重试、默认候选、自由文本解析或通用依赖失效图。
- 不在阶段 0 改变现有 Graph、Executor、Redis event replay 或 Chat 前端行为。

## 阶段 1：动态暂停与同 Run 恢复

阶段 1 已实现通用运行时骨架：

- Graph 的 `tools` 节点可路由到 Checkpoint 终点，不经过 evidence、Answer、Critic 或 response。
- `AgentGraphRunner` 根据 `resume_node` 从 `tools` 继续，跳过 Controller；恢复时重建 RunContext、预算、计划、工具结果、证据义务和 fingerprint cache。
- Executor 在 Graph 返回 `waiting_input` 后先写入快照，再发布 `checkpoint` 与 `status=waiting_input`，随后释放 Worker lease，不提交 assistant Turn。
- `POST /api/v1/chat/runs/{run_id}/resume` 只接收 Checkpoint 类型和 option id，服务端校验后将同一个 Run 排队恢复。
- Redis event replay 支持 Checkpoint 事件；`waiting_input` 会结束当前订阅片段，恢复后从同一 Run 的新 sequence 继续。

阶段 1 不生成任何领域 Checkpoint。`pandascore.resolve_match_games` 的 ambiguous 适配器、
选项构造和 `scheduled_date` patch 属于阶段 2。
