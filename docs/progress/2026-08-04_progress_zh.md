# DotaMind 进度快照 — 2026-08-04

## 16:42 — 主线与历史版本引用收敛

### 已完成

- 将远端 `master` 无强制快进到 V3.2 完成提交 `0040c00`，并设为 GitHub 默认分支。
- 创建并推送三个 annotated version tag：`v3.0.0 -> 5251258`、
  `v3.1.0 -> f7779cb`、`v3.2.0 -> 0040c00`。
- 删除已被主线覆盖的本地与远端开发分支：`feature/v3-functional-loop`、
  `feature/v3.1-agentic-loop`、`codex/langgraph-migration` 和
  `codex/v3.2-agent-runtime-foundation`。
- 按用户决定删除未合入主线的 `feature/llm-rebuild` CROO 原型分支，不创建归档 tag，
  也不把其独有提交合入 `master`。
- 刷新 `origin/HEAD` 与远端跟踪引用；本地和远端最终均只保留 `master` 活动分支。

### 最终状态

- 活动分支：`master -> 0040c00`，跟踪 `origin/master`。
- 历史版本：通过 `v3.0.0`、`v3.1.0`、`v3.2.0` 三个不可变 tag 保留。
- 本次仅调整 Git refs 与进度文档，不改变 V3.2 已验收的运行时行为。

## 20:10 — V3.3 聊天前端原型

### 已完成

- 在 `v3.3` 分支新增独立 Product Design 原型 `prototypes/v3.3-chat/`，采用用户选定的
  第一套视觉方向：深色战术分析风、左侧会话栏、中央聊天流和右侧证据面板。
- 实现新对话、会话选择、侧栏收起/恢复、证据面板开关、追问发送、分析中状态和完成
  状态；桌面、900px 平板和 390px 手机宽度均有响应式布局。
- 使用内置 Image Gen 生成三张项目本地英雄头像资产，并使用 Inter 与 Phosphor Icons
  实现字体和标准 UI 图标；原型数据明确标记为非实时演示数据。
- 新增 `design-qa.md`、桌面/平板/手机截图和同尺寸组合对比证据；按视觉稿完成两轮
  P1/P2 修正后，最终设计 QA 为 `passed`。

### 已验证

- `npm run build`：成功。
- `npm run test:sites`：4 passed。
- 浏览器验证：证据面板与侧栏开关、新对话、输入发送、loading 和完成状态均通过；
  目标桌面视口无页面溢出，浏览器 console 无 error/warning。

### 边界

- 本阶段是独立、可运行的高保真前端原型，尚未连接 `/api/v1/plan`，未实现真实会话
  持久化、流式响应或部署。
- 未恢复已删除的 legacy `apps/web`；现有 `/debug/plan` 内部调试界面和 V3.2 后端行为
  保持不变。

## 20:27 — 撤销 V3.3 聊天原型

### 已完成

- 按用户决定删除本轮新增的 `prototypes/v3.3-chat/` 整个目录，包括原型源码、生成的
  英雄头像、QA 截图、设计 QA 报告、依赖和构建产物。
- 停止该原型的 Vite 本地预览进程；删除后未保留空的 `prototypes/` 目录。

### 最终状态

- `v3.3` 分支继续保留，先前生成的三套视觉方向仍可作为后续重新设计的参考。
- 工作树不再包含 V3.3 前端原型；`/debug/plan` 和 V3.2 后端行为未改变。

## 21:00 — V3.3 assistant-ui 最小聊天前端

### 已完成

- 新增 `apps/chat/` Next.js 16 / React 19 应用，使用 assistant-ui `LocalRuntime` 提供
  消息列表、Markdown、输入发送、取消、复制和重新生成等最小聊天交互。
- 新增薄 API 适配器，只调用现有 `POST /api/v1/plan`：每次页面会话生成一个 UUID v4
  `session_id`，每次请求生成新的 UUID v4 `request_id`，并将回答摘要、建议、依据、限制和
  非成功状态整理为可读消息。
- 删除 assistant-ui 初始化模板自带的 OpenAI / AI SDK Route 和未使用的附件、工具调用、
  推理组件，未引入第二套模型调用或后端运行时。
- 更新根 README、聊天应用 README 和技术架构文档，补充启动方式、唯一 API 边界和当前
  非目标。

### 已验证

- `npm run lint`：通过。
- `npm run build`：通过；Next.js 生产构建和 TypeScript 检查成功。
- 真实浏览器验证：首轮消息成功返回 DotaMind 回答，第二轮追问成功复用服务端会话并
  引用上一轮内容；1280px 视口无横向溢出，浏览器 console 无 error/warning。

### 边界

- 当前接口为一次性 JSON 响应，前端显示真实加载状态，不伪造 token streaming。
- 本阶段不包含刷新后的消息恢复、会话列表、服务端流式响应、附件和用户认证；刷新页面
  会创建新会话。
- `/debug/plan` 继续作为内部运行时调试界面；本轮未修改 V3.2 API 或 Agent Runtime 行为。

## 21:47 — V3.3 真实流式输出与轻量运行信息

### 已完成

- 新增 `POST /api/v1/plan/stream`：同一 `PlanRequest` 通过 POST 返回 NDJSON 的阶段、工具、
  自然语言回答增量和唯一终态事件；已有 `/api/v1/plan` 不绑定流发布器，保持原有响应行为。
- 以请求级 `ContextVar` 在后台 `PlanService.run()` Task 创建前绑定安全事件发布器；Graph、
  工具节点和自然语言答案节点只发布 allowlist 字段。工具仅在通过校验、实际进入 handler 前
  显示运行中；复用、引用解析、预调度阻断和 handler 失败均提供安全终态。
- OpenAI-compatible Provider 使用上游 SSE `stream: true` 逐增量读取并累计完整摘要供原有
  Critic 流程使用；直接回答和确定性结构化回答不伪造 token 流。
- 聊天前端将 LocalRuntime 适配器改为异步生成器，跨网络 chunk 解析 NDJSON 并累计临时正文；
  收到正式 `result` 后以公开响应替换正文，失败、取消或未通过核验时不保留临时文本。
- 新增每消息聚合运行卡：显示“分析问题 → 使用工具 → 整理回答 → 核验依据”、中文工具名与
  状态；运行中展开，成功后自动折叠，失败或取消保持展开。
- 更新 API、架构和聊天应用文档，明确 NDJSON 协议、事件隐私 allowlist、无重连等非目标和
  反向代理必须关闭该路径响应缓冲的要求。

### 已验证

- `apps/api/.venv/Scripts/python.exe -m ruff check app tests`：通过。
- `apps/api/.venv/Scripts/python.exe -m pytest tests/test_plan_route.py tests/test_agentic_answer.py tests/test_agentic_recovery.py tests/test_agentic_runtime.py -q`：`74 passed`。
- `apps/api/.venv/Scripts/python.exe -m pytest -q`：`465 passed, 14 skipped`（另有既有的 FastAPI TestClient 弃用警告）。
- `apps/chat`：`npm run lint` 与 `npm run build` 均通过。

### 边界

- 第一阶段不提供断线重连、心跳、后台恢复、跨页面会话历史或单独逐工具卡片。
- 仅自然语言 synthesizer 可在 Critic 前以“生成中 · 待核验”展示真实增量；最终公开响应是唯一
  正式答案，Critic 或执行失败会撤回临时正文。

## 21:55 — 7.41e 官方补丁快照

### 已完成

- 通过现有离线同步脚本直接读取 Valve 官方 Dota 2 datafeed，新增
  `apps/api/app/data/patches/7_41e.json`。
- 生成的 schema v1 快照记录 7.41e 发布时间 `2026-07-30T07:00:00Z` 和 151 条变更：
  2 条通用、31 条普通物品、5 条中立物品、3 条附魔、110 条英雄变更。
- 同步脚本同时检查了官方英雄列表；仍为 127 个英雄，已提交的英雄快照没有实际差异。
- 将补丁工具的 latest 版本断言从 7.41d 更新为 7.41e；运行时仍只读取已审查的本地快照，
  不在请求链路访问官网。

### 已验证

- JSON 结构、必填变更字段、polarity 枚举和 151 条记录均通过断言；`load_patch("latest")`
  正确返回 7.41e。
- `uv run pytest tests/test_agentic_patch_tools.py -q`：`4 passed`。
- `uv run ruff check tests/test_agentic_patch_tools.py scripts/sync_game_data.py app/integrations/patch_notes.py`：通过。

### 边界

- polarity 延续现有保守规则分类；方向不明确的官方文本保留为 `neutral`，未引入人工改写。
- Valve 列表无法为部分中立物品/附魔 ID 和实体 `1961` 提供名称；与 7.41d 相同，快照保留
  `neutral_<id>` 或数字 target 及官方原文，不用人工映射掩盖上游缺口。
