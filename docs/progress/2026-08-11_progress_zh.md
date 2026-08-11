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

## 17:01 — 历史事实复用与最小澄清策略

### 已完成

- 新增 `history_grounded_answer` direct-answer 模式：模型可以引用已注入的 assistant 历史回答生成简洁答案；validator 只校验 basis 存在、角色和内容，不建立领域专用路由。
- Controller Prompt 改为通用原则：默认优先回答；只有歧义会阻止准确、有界且有用的回答时才澄清；可由短答案覆盖的多个解释直接合并回答；当前输入优先理解为最近未完成澄清的回答。
- 历史事实不再被硬性标记为自动失效或自动可信。模型根据主题、属性、范围、来源、版本、时效和冲突情况决定复用；当前、最新、易变、版本变化或来源不确定时重新规划工具。
- 为 Controller 注入请求级 `request_time`、Catalog patch 和 snapshot 生成时间，避免把动态时效判断写成固定领域规则。
- 修复 PostgreSQL 提交前事件总线失败未调用 `mark_failed()` 的边界；补充 `history_lookup_max_per_run + 最终 Controller 调用` 配置校验和回归测试。
- 同步 Conversation Memory、Controller 和总架构文档；继续明确不维护 Session 级 discourse graph、referent、group、link、focus 或 shows。

### 验证

- API 全量 pytest：`551 passed, 21 skipped`，1 个既有 Starlette/httpx deprecation warning。
- `ruff check app tests`：通过；`git diff --check`：通过。
- 新增历史依据回答、运行时 freshness context、提交前事件失败、History Lookup 预算和配置边界测试。

### 当前边界

- 本阶段不恢复或扩展结构化指称记忆，不添加英雄、物品、选手或战队专用状态机。
- 历史依据回答仍不会自动生成 EvidenceGraph；模型判断当前性或来源不足时必须使用工具。
- 本阶段代码与文档变更尚未提交。

## 17:09 — 完善历史依据回答审计

- `history_grounded_answer` 现在使用独立的公开 `response_type`，不再与普通 `direct_answer` 混淆。
- `conversation_answer` trace 记录实际引用的 `turn_index/role`；公开响应继续保留 `conversation_basis`。
- `ruff check app tests` 通过；全量 pytest：`551 passed, 21 skipped`，1 个既有弃用警告。

## 17:11 — 完成版本与配置文档同步

- 在 `DotaMind_MVP_v2.5.md` 与 `configuration.md` 补充 `history_grounded_answer`、answer-first、请求级 freshness context、无 discourse graph，以及 History Lookup 必须为最终 Controller 预留预算的合同说明。
- `compileall app` 与 `git diff --check` 通过；本次变更仍未提交。

## 17:26 — 最终通用 Prompt 优先级与模型边界

- 在 `tool_plan` 前增加统一优先级：先检查最近 assistant 是否已经包含当前请求的属性；同 patch、同范围且无刷新触发时优先 `history_grounded_answer`，不因“这是事实问题”而重复查询。
- 修正 runtime context 字段为 `current_catalog_patch`，与实施计划和 Prompt 合同一致。
- 最后一次全量 pytest：`551 passed, 21 skipped`；`ruff check app tests`、`compileall app` 和 `git diff --check` 均通过。
- 真实 DeepSeek 三次完整序列的模型观察：第二轮均未澄清但仍选择工具计划，第三轮有一次直接历史复用；随后一次运行首轮超过 60 秒 Run budget。代码不增加领域专用硬规则，模型复用行为仍需按模型/供应商版本持续观察。

## 18:27 — 收敛历史优先决策与提交后事件边界

### 已完成

- Controller Prompt 收敛为统一的顺序决策：先重建当前请求，再判断 assistant 历史能否提供同版本、同范围且仍有效的答案，只有未命中历史复用时才进入澄清或工具规划。
- 删除狼人等领域专用的历史回答示例；工具目录与工具规划规则明确只在需要新证据后生效，未恢复 discourse graph，也未增加英雄、技能、物品、选手或战队专用状态机。
- 增加通用的长回答抽取和短输入继承规则：历史答案的长度不是刷新理由；只提供实体或选项名的追问继承上一轮属性或动作，历史依据回答不得扩展到未请求的属性。
- 在 Prompt 末尾增加最终决策门，避免长工具目录覆盖 history-first 优先级：可复用历史已明确包含答案时，`tool_plan` 为无效选择。
- 增加 PostgreSQL commit 后事件总线抛错的故障注入测试，确认异常可以上抛，但 durable Run/Turn 保持 `completed`，且不会调用 `mark_failed()`。

### 验证

- API 全量 pytest：`553 passed, 21 skipped`，1 个既有 Starlette/httpx deprecation warning。
- 定向 Prompt 与 ChatRunExecutor 测试：`18 passed`；`ruff check app tests`、`compileall app` 和 `git diff --check` 通过。
- 使用最终 Prompt 运行三组独立真实 DeepSeek 三轮会话：三组第二轮“技能 CD 是多少”均返回 `history_grounded_answer`、0 工具，并引用第 1 轮 assistant；回答直接列出全部技能 CD，不再澄清或重复查询。
- 第三轮“变身”有两组返回只包含 105/95/85 秒的历史依据回答；一组连续生成的 JSON 未通过既有决策合同，最终暴露为 `decision_validation_error`，没有错误调用工具或伪造成功结果。

### 当前边界

- 历史事实是否可复用继续由模型按照版本、范围、来源、时效和冲突等通用标准判断，代码不硬编码领域事实路由。
- Controller 供应商仍可能产生合同不合法的 JSON；现有 bounded retry 会显式暴露失败。本阶段不为该模型格式波动增加领域 fallback。

## 19:06 — 统一当前文档、历史蓝图与实现事实

### 已完成

- 重构根 README、`docs/README.md` 与 `docs/design/README.md` 的阅读顺序和状态说明：最新 progress 与当前 technical/architecture 文档是实现事实入口；V3.2/V3.3 version 文档保留阶段设计与验收历史。
- 将整体架构统一为两类入口共用一个 Graph：无状态 `/plan` 调试入口，以及 PostgreSQL 权威、Redis 协调/缓存的 Chat Session/Run 正式多轮入口。
- 统一 Conversation Memory 口径：PostgreSQL 保存完整 user/assistant transcript；Redis `RecentDialogueWindow` 是可重建缓存；compact Turn 只作受限审计；History Lookup 是受预算限制的请求级上下文，不创建 EvidenceGraph。
- 同步 Controller、Node/Tool/Edge inventory、API 与配置文档：补齐 `history_grounded_answer`、开放 `missing_fields`、History Lookup 回边、25 个当前注册工具、Valve Catalog 五文件和 PostgreSQL/Redis/Chat Run 配置。
- 为 V3.0、V3.2、V3.2-5、V3.3-1、V3.3-2、V3.3-3、STRATZ 审计、V3.0 路线图和 SessionStore 面试复习文档增加当前覆盖或历史快照说明；不重写历史 progress 与 archive。
- 核实 `apps/chat` 仍是当前 Next.js/assistant-ui Chat Run 客户端；只有旧 `apps/web` 被删除。根 README、技术架构、Compose 部署说明和 V3.3-2 蓝图按实际前端边界校正。
- 根 `.env.example` 删除已经无人读取的旧前端变量，统一为 `NEXT_PUBLIC_DOTAMIND_API_URL=http://localhost:8001`，并补齐 Chat Run 并发、heartbeat、stale 与 sweeper 配置入口。

### 验证

- 只读构造默认 `ToolRegistry`：确认当前为 `25` 个工具，包含 6 个 Valve Catalog 工具和 `conversation.history_lookup`。
- 检查根入口、应用 README 及所有非 progress/archive Markdown 共 `38` 个文件：相对链接 `0` 个断链；同时修复 STRATZ 审计中的 5 个源码行链接。
- `git diff --check`：通过。此次只修改文档与环境变量模板，没有运行 API pytest 或前端 lint/build。

### 当前文档权威顺序

1. 最新中英文 progress 快照和当前工作树。
2. `docs/technical/architecture.md`、`api.md`、`configuration.md`。
3. `docs/design/architecture/` 当前分层文档与 `DotaMind_MVP_v2.5.md` 架构不变量。
4. V3.0/V3.2/V3.3 version、tools audit、roadmaps 和面试复习作为带覆盖说明的历史设计输入。

## 20:14 — 固化代码变更后的文档维护矩阵

### 已完成

- 在 `AGENTS.md` 中新增代码修改后的文档影响审查规则：每次完成代码变更都必须同步当天中英文 progress，并按实际影响维护入口 README、technical、architecture、工具/provider、前端/部署和文档导航。
- 明确当前事实文档与历史设计的边界：`DotaMind_MVP_v2.5.md` 只在 constrained tool calling 不变量变化时更新；已完成蓝图、路线图、审计、archive 和历史 progress 不随当前代码重写，必要时只增加 supersession 说明。
- 增加完成前校验要求：检查相对链接、术语、工具数量、配置名称和中英文 progress 对齐，只报告实际运行的验证。

### 验证

- 此次只修改维护规则和双语进度文档，未运行 API pytest 或前端 lint/build。

## 21:12 — 增加修改重量与冗余度原则

### 已完成

- 在 `AGENTS.md` 顶部增加项目级修改原则：解决问题前先权衡代码、合同和维护重量与已验证需求、潜在冗余，优先采用能闭合已证明根因的最小一致修改。
- 当重量与冗余度的取舍确实不确定且会实质影响范围或架构时，先询问用户，不默认选择更重的设计。
- 本次只更新协作规则与双语进度文档，没有修改业务代码。

### 验证

- 人工核对中英文新增章节的结构和事实顺序一致；未运行 API pytest 或前端 lint/build。

## 21:31 — 统一 Direct Answer，删除历史回忆模式与 basis

### 已完成

- `DirectAnswerDecision` 收敛为 `kind`、语义 `intent` 和非空 `answer`；删除 `DirectResponseMode`、`response_mode`、`ConversationBasis`、`basis` 与 `conversation_basis`。
- `conversation_answer_node` 直接使用 Controller 生成的答案；所有新的直接回答统一为 `response_type=direct_answer`，不再使用确定性回忆模板或 `history_grounded_answer` 分支。
- Controller Prompt 保留真实 user/assistant 对话、短追问语义继承、历史 freshness 和 History Lookup；删除 turn-index 身份清单、basis 引用规则和旧回忆模式。
- `context_missing` 仍由模型决定，没有新增历史存在性兜底；Conversation Memory、Redis、PostgreSQL、History Lookup 存储合同和 Graph 拓扑未改动。
- 新增 `docs/design/versions/DotaMind_V3.3-4_design.md`，同步当前 Controller、Conversation Memory、整体架构、节点清单、API、MVP v2.5 和 SessionStore 复习文档。
- 更新 Controller、Prompt、Runtime、Graph 决策测试与 golden prompt fixture。

### 验证

- 定向 Controller/Prompt/Runtime 测试：`86 passed`。
- API 全量 pytest：`551 passed, 21 skipped`，1 个既有 Starlette/httpx deprecation warning。
- `ruff check app tests`：通过；`compileall app`：通过；`git diff --check`：通过。
- 使用真实 DeepSeek、PostgreSQL 中原会话前 6 轮做 Controller-only 重放：最终返回 `direct_answer`，不生成旧 mode/basis，也未调用工具；模型恢复了“兽王呢”继承的分路问题。一次供应商 JSON 重试仍被现有 bounded retry 显式记录，未改变成功结果。

### 当前边界

- 模型仍可能在“我上一轮问了什么”这类回忆问题中附带历史回答细节；本阶段不增加确定性截断或领域专用回答模板。
- 旧 PostgreSQL `public_response` 历史 JSON 不迁移；新 Run 不再生成旧 `history_grounded_answer`、`response_mode` 或 `conversation_basis` 字段。
