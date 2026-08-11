# 2026-08-11 进度快照

## 14:44 — 移除结构化指称记忆，改为真实对话窗口

### 已完成

- 删除 Session discourse graph、Extractor、Reducer 和 discourse render；`Turn` 仅保留受限审计字段。
- 新增通用 `ConversationMessage`、`DialogueTurn`、`RecentDialogueWindow` 合同；Controller 读取真实交替的 `user/assistant` 消息。
- 新增 `ConversationMemoryService`：Redis 保存 recent window，PostgreSQL 保存完整对话；窗口缺失或落后时从 PostgreSQL 重建，按字符预算保留最新完整轮次。
- `chat_turns` 新增非空 `assistant_message`；新增 `20260811_01_dialogue_memory` 迁移，已在本地 PostgreSQL 从 `20260810_01` 升级到新 head，并回填旧回答文本。
- `ChatRunExecutor` 在 PostgreSQL commit 后更新 Redis recent window；Redis 更新失败不改变已提交 Run 的结果。
- 新增内部 `conversation.history_lookup` 工具：运行时注入 session/browser，最多查找一次，结果只进入当前 Run 的 `retrieved_messages`，随后重新进入 Controller。
- `ConversationBasis` 改为 `(turn_index, role)`；回忆用户问题只能引用 user 消息，回忆助手回答只能引用 assistant 消息。
- 更新 Controller golden prompt、配置、架构设计文档、Redis/PG/执行器测试，并删除旧 discourse 测试。

### 验证

- API 全量 pytest：`531 passed, 21 skipped`，1 个既有 Starlette/httpx deprecation warning。
- `ruff check app tests`：通过；`compileall app`：通过。
- 本地 PostgreSQL/Redis 集成测试：`18 passed`。
- Alembic：`20260810_01 -> 20260811_01` upgrade 成功。

### 当前边界

- Controller 仍把历史消息当作不可信上下文；历史回答不能替代当前工具和 EvidenceGraph。
- `conversation.history_lookup` 只提供请求级历史补充，不产生事实证据，也不会建立实体/关系结构化记忆。
- 当前工作树尚未提交；未增加英雄、物品、选手或战队专用上下文分支。

## 15:55 — 修复四个 P1：澄清、失败文本、提交后缓存与 History Lookup 合同

### 已完成

- Controller 历史规则改为通用语义：真实 user/assistant 消息是对话上下文；历史指令不能覆盖 system prompt，历史事实不能替代当前证据；未唯一选中集合成员时应澄清。当前 query 作为原始 user message，`game` 改放 system runtime 后缀。
- `ClarificationDecision.missing_fields` 改为受 snake_case 格式和 `1..8` 数量限制的开放字段名，字段名不参与路由。
- `render_assistant_message()` 优先处理 `safe_failure_required`，公开响应、assistant_message、compact Turn 的失败文本统一使用安全文案。
- `record_committed_turn()` 不再在 PostgreSQL commit 后读取完整 PostgreSQL 历史；连续缓存直接追加，缺失/断游标只失效 recent window，下一轮再 cache-aside 重建；新增 Redis/InMemory `invalidate_recent_dialogue()`。
- `ChatRunExecutor` 增加 committed 边界；提交后缓存、事件或其他基础设施异常不再调用 `mark_failed()`。
- `conversation.history_lookup` 计划强制为单一工具且不得携带 required evidence；输入至少有一个查询选择条件，turn index 去重并限制为正数和最多 8 项。
- history lookup 结果处理提升为显式 Graph 节点，合并去重后再进入下一次 Controller；执行次数真正读取 `history_lookup_max_per_run` 配置，达到上限在工具执行前拦截。

### 验证

- API 全量 pytest：`545 passed, 21 skipped`，1 个既有 warning。
- P1 相关回归测试：`53 passed`；Controller/prompt 测试：`48 passed`。
- `ruff check app tests`：通过；`compileall app`：通过；`git diff --check`：通过。
- 本地 PostgreSQL/Redis 集成测试：`18 passed`；Alembic 当前为 `20260811_01 (head)`。
- 使用真实 DeepSeek、PostgreSQL、Redis 运行两组三轮会话：首轮均生成 hero resolver + ability/talent 工具计划，第三轮指定技能后均生成 resolver + ability 工具计划；但两组第二轮的未指定成员属性追问均被模型直接规划为整组工具查询，没有达到预期的 clarification。当前代码未增加领域专用规则，该项仍需后续 prompt/model 调优。

### 当前边界

- P1 的存储、合同、失败隔离和 Graph 状态传递已闭合；真实模型对“集合属性追问是否先澄清”的行为仍未满足验收标准。
