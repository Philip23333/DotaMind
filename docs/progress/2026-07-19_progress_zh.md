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

## 15:09 — V3.2 Agent Runtime Foundation 目标设计

- 新建 `codex/v3.2-agent-runtime-foundation` 分支，冻结新增业务工具，将下一阶段
  定位为 Agent 运行时架构完善。
- 新增 `docs/design/DotaMind_V3.2_design.md`。目标设计覆盖 `RunContext`、
  `RunBudget`、`AttemptRecord`、有界 Recovery/Replan、跨 attempt 工具指纹复用、
  `request_id` 幂等、`RedisSessionStore`、Prompt Registry、可观测性与隐私边界。
- Replan 设计固定采用全局预算：`max_replans=1`、总工具调用和总运行时间上限；
  tool/transport、非法计划、Answer 失败和用户明确约束导致的稀疏结果不自动重试。
- 分阶段顺序为 Run/Attempt/Budget、Prompt Registry、有界 Replan、请求幂等、
  Redis Session Store、观测与故障注入；完成前不解冻业务工具开发。
- 更新根 README 与 `docs/README.md`，区分 V3.0 已实现能力、V3.2 目标运行时设计
  和 v2.5 constrained tool calling 底座，并同步每日累计快照说明。
- 本阶段仅完成设计和文档入口，没有把目标节点、Redis、Replan 或幂等行为描述为
  已实现功能。

### 验证

- `git diff --check` 通过；仅输出既有 LF/CRLF 转换提示。
- V3.2、V3.0、v2.5 和 technical architecture 的文档入口目标均存在。
- 本阶段未修改 API 运行代码，因此未运行 API 测试、DeepSeek 或 STRATZ 请求。

## 16:12 — V3.2-0 冻结与护栏收口

- 更新 `DotaMind_V3_node_tool_edge_inventory.md`，保留当前 V3.0 单 attempt
  运行图，并单独列出 V3.2 目标 `run_init`、`attempt_finalize`、`recovery`、
  `attempt_reset` 和 `run_finalize` 节点；所有目标节点均明确标记为尚未实现。
- 为五类 Controller decision、当前 Graph 分支、终态错误优先级、Session 隐私、
  Tool/Evidence contract 和已删除 legacy route 建立现有 characterization tests
  的可审计映射，作为后续 V3.2 阶段的行为基线。
- 将默认 Tool Registry 测试从“包含已知工具子集”收紧为冻结目录的精确集合断言；
  V3.2 期间新增或删除业务工具都会直接触发测试失败。
- 本阶段没有增加运行时状态、目标 Graph 节点、Replan、`request_id` 或 Redis
  行为；STRATZ 易变数据仍不固定精确胜率或场次数值。

### 验证

- V3.2-0 定向护栏：`87 passed, 1 warning`。
- API 完整测试：`356 passed, 1 warning`。warning 为 FastAPI/Starlette 上游
  `httpx` 弃用提示。
- `uv run ruff check .` 通过。
- `uv lock --check` 通过。
- `git diff --check` 通过；仅输出既有 LF/CRLF 转换提示。
- 本阶段未运行真实 DeepSeek/STRATZ 网络请求。

## 16:50 — V3.2-1 蓝图与 design 文档分类

- 新增 `docs/design/versions/DotaMind_V3.2-1_design.md`，将 V3.2-1 固化为
  Run / Attempt / Budget 单 attempt 实施蓝图；明确目标运行图、runtime package、
  `RunContext`、`RunBudget`、`AttemptRecord`、Trace、终态收口、公开 runtime
  allowlist、配置、工作包、测试矩阵和完成定义。
- V3.2-1 保持单次 Graph 执行：只新增目标 `run_init_node` 和
  `run_finalize_node`；预算在本阶段建模和计数但不产生新错误路由，
  `attempt_finalize_node`、Recovery/Replan、工具指纹、`request_id`、Prompt
  Registry 和 Redis 继续留在后续既定阶段。
- 将 `docs/design/` 整理为四类：`versions/` 版本蓝图、`architecture/` 分层与
  运行时架构、`tools/` 工具专项设计、`roadmaps/` 能力缺口与优先级；新增
  `docs/design/README.md` 作为分类和阅读顺序入口。
- 同步更新根 README、`docs/README.md`、`AGENTS.md`、archive 入口、设计文档
  内部链接、technical reference 和代码注释中的规范路径。移动后的 design 目录内
  本地 Markdown 链接均可解析，当前文件中不再存在旧分类路径；历史 progress
  快照保持原样。
- 本阶段只修改文档、文档路径和相关注释/文档生成字符串，没有实现 V3.2-1
  运行时代码，也没有改变 Tool Registry 或 API 行为。

### 验证

- API 完整测试：`356 passed, 1 warning`。warning 为 FastAPI/Starlette 上游
  `httpx` 弃用提示。
- `docs/design/` 本地 Markdown 链接解析检查通过；当前非历史文件旧路径检索为空。
- `uv run ruff check .` 通过。
- `uv lock --check` 通过。
- `git diff --check` 通过；仅输出既有 LF/CRLF 转换提示。
- 本阶段未运行真实 DeepSeek/STRATZ 网络请求。
