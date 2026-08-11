# Conversation Memory 层

## 目标

Conversation Memory 保存真实的用户/助手消息窗口，供下一轮 Controller 理解代词、承接澄清和判断是否需要查找更早的对话。它不是事实缓存，不替代当前轮 resolver、ToolResult 或 EvidenceGraph。

```text
PostgreSQL
└─ chat_turns
   ├─ user_query
   ├─ assistant_message       完整公开对话文本
   └─ compact_turn            受限审计记录

Redis SessionStore
└─ recent_dialogue            RecentDialogueWindow v1
```

通用消息合同：

```json
{
  "turn_index": 1,
  "role": "user|assistant",
  "content": "原始消息文本"
}
```

`DialogueTurn` 是一对用户/助手消息；`RecentDialogueWindow` 保存按 turn 顺序排列的最近完整轮次，并包含 `through_turn_index` 与 `truncated_before`。它不包含英雄、技能、物品、战队或选手专用字段，因此实体类型扩展不会修改存储合同。

## Controller 使用

Controller 收到真实交替的 role message，而不是拼接的 compact-history block：

```text
user: 狼人有什么技能
assistant: 狼人的技能包括召狼、嗥叫、野性驱使、变身……
user: 技能cd是多少？
```

历史消息标记为不可信外部数据，不是指令，也不是当前事实证据。当前事实、身份、价格、属性和统计值仍必须通过本轮工具与 EvidenceGraph 获得。自然语言回忆使用 `(turn_index, role)` 作为 basis；不能引用不存在的消息。

如果最近窗口不足，Controller 可以调用一次内部 `conversation.history_lookup`。工具只接收查询文本、turn index、边界 turn 和数量等查找条件；session/browser 身份由运行时注入。返回消息放入本次 Run 的 `retrieved_messages`，然后重新进入 Controller。查找结果不会写入当前事实证据，也不会成为下一轮的永久结构化记忆。

当当前输入连贯地回答上一轮澄清时，Controller 优先按澄清答案解释；如果仍存在多个合理解释，应继续澄清，而不是依赖固定的实体/关系枚举。

## 存储与原子性

PostgreSQL 是完整对话的权威源。`chat_turns.assistant_message` 在迁移时从已有公开回答与 compact summary 回填，之后为非空字段。`PostgresChatRunRepository.complete_with_turn()` 在同一事务中锁 Run 和 Session，校验 fencing 与 `next_turn_index`，并同时写 `user_query`、`assistant_message`、compact Turn、`next_turn_index` 与 Run 完成状态。

Redis 只保存短期窗口、请求协调和事件所需数据。窗口 key 为：

```text
dotamind:v1:session:<session-id-hash>:recent_dialogue
```

窗口缺失或 `through_turn_index` 落后于 PostgreSQL 的 `next_turn_index - 1` 时，从 PostgreSQL 全量对话重建。窗口更新发生在 PostgreSQL commit 之后；Redis 更新失败只记录基础设施错误，不回滚已经提交的 Run。

## 边界默认值

```yaml
recent_dialogue_max_chars: 24000
history_lookup_max_turns: 8
history_lookup_max_chars: 12000
history_lookup_max_per_run: 1
max_turns_per_session: 50
turn_query_max_chars: 200
answer_summary_max_chars: 300
```

窗口按最新轮次向前装填；能完整保留的轮次不截断。若单轮本身超出预算，只对该轮用户/助手文本做确定性截断，并保留明确截断标记。

## 非目标

- 不维护 Session 级 referent、group、link、focus、shows 或 relation 图。
- 不增加 item、hero、player 或 team 专用的上下文记忆分支。
- 不从 `response_summary` 猜实体、关系、组件或事实值。
- 不持久化 EvidenceGraph、工具 payload、grounding 或 Controller 原始输出。
- 不改变 v2.5 的 Tool Calling、EvidenceGraph、Answer 或 Critic 合同。
