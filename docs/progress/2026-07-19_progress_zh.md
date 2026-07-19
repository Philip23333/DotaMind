# DotaMind 进度快照：2026-07-19

## 14:16 — Recall 自由回答确定性清除

- Controller 对通过 schema 校验的 recall 决策执行幂等归一化：
  `quote_user_query`、`recall_entity` 和 `recall_assistant_summary` 的自由
  `answer` 强制清除为 `null`；`social` answer 保持不变。
- `decision_validate_node` 在 Graph 运行时再次归一化并写回 decision、kind 与
  tool plan，确保自定义 Controller 不能绕过该规则。清除行为只记录 mode，
  不记录模型答案内容。
- 历史 `basis` 校验不变：不存在的 Turn、错误字段、失败轮次和不匹配实体仍然
  返回 decision validation error。纵深校验反馈现在直接要求 recall answer 使用
  JSON `null`。
- Controller Prompt 明确区分 recall 与 social：recall 只选择非空 basis，最终
  文本由服务端从经过校验的 Turn 生成；social 使用空 basis 和文本 answer。
- 回归测试覆盖三种 recall mode、social 保留、归一化幂等、错误 basis，以及
  模型返回“影魔”但历史为 Lina 时单次调用后确定性回答 Lina。

### 验证

- API 完整测试：`356 passed, 1 warning`。warning 为 FastAPI/Starlette 上游
  `httpx` 弃用提示。
- `uv run ruff check .` 通过。
- `uv lock --check` 通过。
- `git diff --check` 通过；仅输出仓库既有的 LF/CRLF 转换提示。
- 本阶段未运行真实 DeepSeek/STRATZ 网络请求。
