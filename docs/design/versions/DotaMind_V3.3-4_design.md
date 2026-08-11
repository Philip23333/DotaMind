# DotaMind V3.3-4：统一 Direct Answer 轻量收敛

> 状态：已于 2026-08-11 完成实现，并于 2026-08-12 完成验收。历史回忆的
> 程序化 response mode 与消息 basis 合同已经删除，Controller 直接基于真实对话
> 生成答案；API 全量测试、静态检查和真实 DeepSeek 重放均通过。

## 目标

- `direct_answer` 只包含 `kind`、语义 `intent` 和非空 `answer`。
- Controller 继续读取真实交替的 `user/assistant` ConversationMessage。
- 历史追问、短输入继承和稳定历史事实复用由模型结合上下文判断。
- `conversation_answer_node` 直接使用 Controller 生成的答案。
- 所有新的直接回答公开为 `response_type=direct_answer`。

## 删除范围

- `DirectResponseMode`、`response_mode`。
- `ConversationBasis`、`basis`、`conversation_basis`。
- `quote_user_query`、`recall_assistant_summary`、`history_grounded_answer`。
- 服务端确定性回忆模板和 basis 角色/turn 校验。

## 保留边界

- `context_missing` 仍由模型决定，不增加历史存在性兜底。
- `conversation.history_lookup` 仍是有预算的请求级上下文补充。
- 历史消息不成为当前 Dota EvidenceGraph，也不替代当前工具查询。
- PostgreSQL transcript、Redis RecentDialogueWindow、Chat Run 生命周期和
  History Lookup 存储合同不变。
- 不增加领域专用历史路由、关键词匹配、identity manifest 或第二次 LLM 审核。

## 实施顺序

1. 删除 decisions 中的 DirectAnswer mode/basis 字段，统一非空 answer 合同。
2. 简化 conversation answer node、runtime outcome 和 public response type。
3. 重写 Controller Prompt 的 direct-answer 规则与示例。
4. 更新 Controller、Graph、History Lookup 和 prompt 合同测试。
5. 同步当前 technical/design 文档与中英文进度快照。

## 验收

- 真实六轮对话中，“我上一轮问了什么”不因 turn-index 生成失败而退化为
  `context_missing`。
- Controller 可以结合上下文回答继承属性的短追问，而不需要 basis。
- direct answer 不调用工具、EvidenceGraph、Answer LLM 或 Critic。
- API 全量 pytest、ruff、compileall、diff check 通过。
- 使用真实 DeepSeek 做 Controller-only 重放，确认新合同下不再生成旧 mode/basis。

## 非目标

- 不迁移历史 PostgreSQL `public_response` JSON。
- 不修改数据库 schema、Redis 序列化、前端代码或工具注册表。
- 不保证模型永远做出正确语义判断；模型错误继续通过现有决策错误或明确的
  `context_missing` 暴露，不增加领域 fallback。
