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

## 阶段 2：比赛选择 Checkpoint 适配器

阶段 2 只接入 `pandascore.resolve_match_games` 的 `data.status=ambiguous`：

- 适配器只在带有 ChatRun `internal_run_id` 的执行中启用；无状态 `/plan` 调试入口不创建
  持久化 Checkpoint。
- `tools` 节点在该工具返回候选 Fixture 时立即构造
  `checkpoint_type=pandascore_match_selection`，选项由候选的 UTC `scheduled_at`
  （缺失时 `begin_at`）生成；不继续执行 Valve 映射或 OpenDota 详情工具。
- 每个选项只把服务端生成的 `scheduled_date` 放入 `value`；`source_tool_call_id`
  固定为产生歧义的工具调用，`resume_node=tools`。
- 用户通过既有 resume API 选择 option 后，Executor 从快照按 option id 查找该值，
  将 `scheduled_date` 写回原 `pandascore.resolve_match_games` 调用，再从同一 Run
  进入 `tools`。Controller 不会二次调用，客户端不能提交日期或 Plan patch。
- 恢复执行复用前序成功工具的 fingerprint；会先删除产生 Checkpoint 的旧 ambiguous
  工具结果、dispatch record 和 fingerprint，再以新日期重新执行该比赛解析调用，随后
  才允许继续 Valve/OpenDota 工具链。

本阶段不处理其它工具的 ambiguous、自由文本选项、同日多候选的额外判定、自动猜测、
超时或过期策略，也不包含前端 CheckpointCard。因为首期 resume patch 只有日期，候选
中任意两个比赛同日时适配器不创建选择卡片，保留既有 explicit ambiguous 边界。

## 阶段 3：ChatRun 前端恢复交互

阶段 3 将阶段 0/1/2 的事件和 resume API 接入 `apps/chat`：

- 前端补齐 `checkpoint` 事件与 `waiting_input` 状态类型，并将每个事件的 `sequence` 保存在
  assistant message runtime metadata，作为恢复后的 `after` 游标。
- `CheckpointCard` 只展示服务端生成的 `question` 与 `options[].label`；点击后提交
  `checkpoint_type + option_id`，不读取或拼装 `options[].value`。
- 选择成功后调用同一个 `run_id` 的 `/resume`，再通过 assistant-ui 的 `resumeRun` 从原消息
  分支继续订阅；续订使用 Checkpoint 后的 sequence，因此不重复展示旧事件，也不重新调用
  Controller。请求失败时保留卡片并允许再次选择。
- 刷新页面沿用现有活动 Run 的 `unstable_resume` 与 `after=0` replay，重新得到 Checkpoint
  事件和选择卡片；等待阶段不触发取消，也不调用 Valve/OpenDota。

本阶段不接入其它 ambiguous 类型、自由文本选择、过期/超时策略或服务端 Checkpoint
快照扩展；Checkpoint 的 `value` 仍只由后端解释。

## 阶段 4：测试与文档交付

阶段 4 不扩展运行时能力，只对阶段 0—3 的闭环做回归验收：

- API 定向测试覆盖 Checkpoint 契约、暂停时下游工具零调用、快照恢复、Controller 不重跑、
  resume 参数校验、事件顺序与 `waiting_input` 生命周期。
- Chat 定向测试覆盖 Checkpoint metadata、同一 `run_id` 的 sequence cursor 续订、resume
  请求体和前端构建边界。
- 使用 fixture 验收 `resolve_comp → resolve_games(ambiguous) → waiting_input → resume`
  的跨节点契约；不固定实时 PandaScore ID、比分或日期。
- 更新 API、运行时架构、总体架构、Tool 层、节点清单、API/Chat README 与当日中英文进度；
  不新增其它 ambiguous 适配器、自动选择、超时策略或通用依赖失效图。
