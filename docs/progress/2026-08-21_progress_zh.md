# 2026-08-21 进度快照

## 01:14 — TI 最新战况 Answer 输出示例

### 已完成

- 在赛事/比赛 evidence 对应的自然语言 Answer Prompt 中加入 TI 最新战况 Markdown 版式示例，固定赛事概况、当前比赛、关键赛果、后续赛程和数据说明的章节顺序。
- 修正关键比赛表格为 `对阵 | 比分 | 结果` 三列，队名、系列赛比分和晋级结果分别落入对应列。
- 示例明确标为 presentation-only；队伍、比分、日期、时间、阶段、赛区、赛制和来源声明不得脱离当前 EvidenceGraph 复用，未知届数不得输出字面量 `X`。
- 示例继续由 evidence kinds/source 动态选择，不读取 `intent`、工具名或关键词，不改变 Controller 规划、工具链、output contract 或 evidence 义务。

### 验证

- Answer 定向测试：18 passed。
- API 全量：622 passed、21 skipped、1 warning。
- `uv run --project apps/api ruff check apps/api/app/agentic/prompts/answer.py apps/api/tests/test_agentic_answer.py` 通过。

### 已知边界

- 当前仍是 `natural_language_answer` 的 LLM 版式示例，不是确定性 `tournament_schedule_report` 结构化 contract；具体栏目只在当前 evidence 足以支撑时生成。

## 09:30 — PandaScore Match List 最新排序

### 已完成

- `pandascore.list_matches` 对 `upcoming`、`running`、`past` 三个 PandaScore Fixture 请求统一下推 `sort=-scheduled_at`，并在合并去重后继续按赛程时间降序排列。
- 默认 `limit=20` 现在也下推为每个状态请求的 `page[size]=20`，最终返回全状态中最新的 20 个 Fixture；不再因 PandaScore 默认升序第一页优先返回最早的小组赛。
- 工具说明与 PandaScore API inventory、Tool 层契约已更新，明确默认的最新优先语义。

### 验证

- 已用项目配置的 PandaScore token 实测：`GET /dota2/matches/past?filter[serie_id]=10828&sort=-scheduled_at&page[size]=20` 返回 20 条，首条为 `2026-08-20T13:25:00Z`、末条为 `2026-08-15T05:20:00Z`。
- 通过实际 `pandascore.list_matches` handler 验证默认输出恰为 20 条；同一 Series 的最新三条赛程为 `2026-08-23T05:00:00Z`、`2026-08-23T02:00:00Z`、`2026-08-22T11:00:00Z`。
- Fixture 列表排序/请求参数与 Agentic PandaScore 工具定向测试：21 passed。
- `ruff check` 已通过本次涉及的 PandaScore 实现与测试文件。

### 已知边界

- 默认集合仍包含未来、进行中和已结束 Fixture；“最新”按 `scheduled_at`（缺失时 `begin_at`）降序定义，而非只筛选已结束赛果。调用方需要仅看赛果时应传入 `statuses=["finished"]`。

## 10:00 — 跨工具 dict 引用规划校验

### 已完成

- 修复规划期的引用占位：`dict` 参数不再被模拟为 `{}`，而是非空的类型占位字典。
- 因此 `dota.resolve_valve_matches.competition` 可合法引用 `pandascore.resolve_competition.data.competition`，不会在真实工具调用前被 `Field(min_length=1)` 误拒绝。
- 为 PandaScore Competition → Game context → Valve Match Resolution 的完整计划校验链加入回归断言。

### 验证

- 最小定向测试：`tests/test_agentic_match_resolution_tools.py`，3 passed。

### 已知边界

- 该改动只修正规划阶段的静态类型占位；运行时仍要求上游工具真实返回非空赛事上下文，引用解析或上游执行失败会按既有错误路径显式返回。

## 10:30 — 跨源 Valve 映射不依赖 OpenDota Series ID

### 已完成

- `dota.resolve_valve_matches` 不再将 OpenDota `series_id` 或由其计算的局号作为硬过滤条件。
- 唯一映射仍同时要求目标联赛、无序两队 ID、1800 秒内开赛时间、5 秒内时长及可用时的胜者一致性；多个候选继续返回 `ambiguous_match`，不按最近时间选择。
- 覆盖了 OpenDota 比赛缺失 `series_id` 但其余强信号唯一命中的真实数据形态，并同步更新跨源映射技术契约。

### 验证

- 最小定向测试：`tests/test_cross_source_match_resolution.py`，15 passed。
- 使用 Iron Wing vs Team Spirit 的两局真实 PandaScore 上下文实测，已解析为 Valve `8955197224`、`8955247801`。

### 已知边界

- 对缺失或无唯一 Valve ID 的上游映射，后续 Match Details 调用仍需要图执行层显式短路并生成能力边界；这不是通过 Controller Prompt 文案可以可靠解决的问题。

## 11:00 — OpenDota 比赛英雄与物品 Catalog 名称

### 已完成

- `opendota.match_details` 的选手面板现在保留原始英雄/物品 ID，同时确定性追加 Valve Catalog 的中英文名称；覆盖英雄、六格装备、背包、中立物品与 BP 英雄。
- 空槽位保持空；Catalog 缺失的英雄或物品 ID 显式标记 `not_found` 且不生成猜测名称。
- 记分板和 BP evidence 带入 Catalog 快照元数据；Answer Prompt 只允许使用 evidence 中的 `*_name_en` / `*_name_zh` 字段展示名称，禁止由模型根据 ID 自行翻译或猜测。

### 验证

- 最小定向测试：`tests/test_agentic_opendota_match_tools.py`，4 passed。
- 本次涉及文件的 `ruff check` 通过。

### 已知边界

- 名称取自提交的 Valve Catalog 快照；该快照未收录的新 ID 会保持无名称状态，直到按仓库脚本更新 Catalog。

## 15:00 — 英雄与物品图片离线缓存

### 已完成

- 在 `apps/api/app/data/catalog/images/` 提交当前 Catalog 的 127 张英雄图片和 414 张非配方物品图片，共 541 张、约 21.1 MiB。
- `sync_game_data.py` 增加 `--images-only`，从 Valve 官方 React 图片 CDN 下载图片到临时目录，全部成功后替换本地图片目录；下载失败时不会先覆盖旧目录。
- API 通过 `/api/v1/assets/dota/heroes/{id}.png` 和 `/api/v1/assets/dota/items/{id}.png` 提供本地静态访问。
- `resolve_hero`、`dota.hero_attributes`、`resolve_item`、`dota.item_info` 的实体结果和对应身份 Evidence 增加确定性的 `image_path`。
- Chat 从 `tool_results` 读取 `image_path`，去重后追加 Markdown 图片；图片地址由 API 基地址和本地路径组成，模型不生成图片 URL。

### 验证

- 图片资源实际下载完成：541 张，目录总大小 22,121,037 bytes。
- Catalog、同步、Graph、工具链定向测试：71 passed；图片静态路由与解析器测试：2 passed。
- Chat 图片格式化测试：3 passed。
- API 定向 Ruff 检查通过；同步脚本编译检查通过。

### 已知边界

- 当前阶段不缓存技能、天赋、先天技能、比赛面板、战队或联赛图片。
- 图片本身不做 SHA、尺寸、PNG 结构或启动时扫描；同步阶段只要求 HTTP 请求成功且响应体非空。

## 15:30 — 英雄与物品标题内联缩略图

### 已完成

- Chat 不再在回答尾部追加“相关图片”图片区块。
- `formatPlanResponse()` 从 `tool_results.data.hero` / `data.item` 提取本地 `image_path`，去重后只装饰第一个匹配到实体名称的 Markdown 标题。
- 名称匹配优先中文名，其次英文名和内部名；匹配名称前插入图片 Markdown，未匹配标题时保持原回答不变。
- Markdown `img` renderer 仅为 `/api/v1/assets/dota/` 图片添加 28×28、圆角、裁切和垂直对齐样式，普通 Markdown 图片不受影响。

### 验证

- Chat 全量测试：16 passed。
- ESLint：通过。
- Next.js production build：通过。

### 已知边界

- 只处理英雄/物品查询标题，不处理正文重复名称、比赛面板、队伍、技能或联赛实体。

## 15:30 — TI 按日期赛程输出模板

### 已完成

- 将 Answer Prompt 的 TI 最新战况示例替换为以 UTC 日期为一级粒度的布局，不再跨多个日期优先按赛事阶段聚合。
- 固定章节顺序为：当前日期（进行中 → 已结束 → 后续比赛）→ 后续日期正序 → 历史日期倒序；每个 UTC 日期最多渲染一次，空日期与空小节省略。
- 当前日期只有在 evidence 能确定时才标记“今日”；否则只显示具体日期。示例仍为 presentation-only，不得用其占位队伍、比分或赛程填补 EvidenceGraph 未支持的内容。

### 验证

- 最小 Prompt 定向测试：`tests/test_agentic_answer.py -k ti_status_example`，1 passed（17 deselected）。
- 本次涉及 Prompt 与测试文件的 `ruff check` 通过。

### 已知边界

- 该模板仅约束 LLM 的展示结构，当前仍不是确定性的赛事赛程输出 contract；“今日”与日期归属依赖运行时 evidence 提供的时间信息。

## 16:00 — 比赛详情逐局 BP 与次级数据说明

### 已完成

- 为含比赛结果、跨源映射、选手面板或 BP evidence 的自然语言 Answer 注入独立的比赛详情版式示例；赛事状态与比赛详情模板现在按所需 evidence kinds 分别选择，避免比赛详情混入 TI 赛程示例。
- 逐局固定展示顺序为：时长/人头比/胜方摘要 → 以队伍分开的两张完整 BP 表 → 双方选手数据。BP 表按每队的 Ban 1–7 与 Pick 1–5 展开，缺少的真实动作行省略，不补占位英雄。
- Valve Match ID 仅在可映射时以局标题后括号展示；整篇末尾的“数据说明”固定为 blockquote + `<sub>` 脚注式次级视觉内容，不使用 CSS 或 HTML 颜色样式。
- 同步更新 Answer 架构文档，明确比赛详情模板只约束展示，不扩张 EvidenceGraph 的事实边界。

### 验证

- 最小 Prompt 定向测试：`tests/test_agentic_answer.py -k ti_status_example`，1 passed（17 deselected）。
- 本次涉及 Prompt 与测试文件的 `ruff check` 通过。

### 已知边界

- `<sub>` 的缩小效果取决于最终 Markdown 渲染器；不支持时仍保留 blockquote 和内容，来源与事实约束不变。

## 15:45 — 闪烁匕首“跳刀”别名

### 已完成

- 为 Valve Catalog 的 `item_blink` 增加中文常用别名“跳刀”，`resolve_item("跳刀")` 将可解析为闪烁匕首（Item ID 1）。
- 同步器保留该别名规则，后续刷新 Catalog 快照不会覆盖。

### 验证

- 按请求未运行测试。

### 已知边界

- 本次只补充“跳刀”这一明确别名，不扩展通用物品同义词词典。

## 16:00 — OpenDota 比赛实体图片与上下文缩略图

### 已完成

- `opendota.match_details` 的选手英雄、BP 英雄、最终装备、背包和中立物品详情现在携带确定性的 `hero_image_path` / `item_image_path`；英雄或物品 ID 缺失、Catalog 未命中时为 `null`。
- Chat 递归读取 `tool_results[*].data` 中的 Catalog 实体，仍只接受 `/api/v1/assets/dota/.../*.png` 本地路径，并按路径去重元数据。
- 删除仅装饰首个标题的旧逻辑，改为按 Markdown 上下文插入受控图片 fragment：一级实体标题 `lg`（56×56）、普通列表/叙述 `md`（32×32）、表格及 BP/阵容/pick/ban 区域 `sm`（20×20）。同一实体在不同选手行或对局中可分别显示。
- fenced code、行内代码、Markdown 链接、表格分隔行不会被改写；不再追加“相关图片”图片区块，图片 URL 仍由结构化后端字段确定。
- Markdown `img` renderer 会移除 `#dota-size=sm|md|lg` fragment，并仅对本地 Catalog 图片应用三档样式；普通 Markdown 图片保持原行为。

### 验证

- API OpenDota 定向测试：5 passed。
- Chat 图片格式化定向测试：8 passed。
- Chat ESLint：通过。

### 已知边界

- 本次不处理技能、队伍、联赛或用户消息图片，也不改变图片缓存、静态路由、工具注册、Evidence kind 或 Prompt 合同。

## 16:15 — 比赛选手列图片误注入修复

### 已完成

- 修正 Chat 的实体提取：`hero_image_path` 仅匹配 `hero_name_zh` / `hero_name_en`，`item_image_path` 仅匹配物品专属名称；选手对象的 `name` 不再被误作英雄别名。
- 本地 Catalog 图片改为左右各 `1px` 间距，并移除图片 Markdown 与实体名称之间的文本空格，避免额外视觉间隙。

### 验证

- 新增选手名不被英雄图标替换的前端回归测试。

### 已知边界

- 仍只在服务端结构化图片引用支持的英雄或物品名称前插入图片。

## 16:30 — 比赛详情 Markdown 与选手装备表

### 已完成

- 比赛详情模板不再输出 `<sub>` 或 `<br>`；数据说明改为纯 Markdown blockquote，避免未启用原始 HTML 解析时显示标签字面量。
- 系列赛结果改为“队伍A（胜场） ： 队伍B（胜场）”单行；BP 表调整为“顺序 | 选择 | 禁用”，去除 Ban/Pick 括号和单元格内阶段标签。
- 选手表移除独立等级列，等级附在英雄名后；经济要求使用千分位；新增最后一列“装备”，Answer 只输出由 evidence 支撑的物品名，Chat 将已解析物品替换为中尺寸图标且不显示名称。

### 验证

- 补充比赛详情 Prompt 与装备列图片替换的回归断言。
- API 定向 Prompt 测试：1 passed（17 deselected）；API 全量：629 passed、21 skipped、1 warning。
- `ruff check`、Chat 20 项测试、ESLint 与 Next.js production build 均通过。

### 已知边界

- Catalog 未命中的物品保留原名称，避免将 evidence 中的装备信息静默隐藏。

## 17:00 — ChatRun Checkpoint 阶段 0 契约

### 已完成

- 新增 `Checkpoint`、`CheckpointOption` 与 `CheckpointSnapshot` 契约；快照只保留恢复所需的计划、工具结果/dispatch、预算、attempt 和 fingerprint，不保存 Prompt、模型 raw output、历史上下文或 Answer。
- ChatRun 增加 `waiting_input` 活跃状态与 `checkpoint_state` JSONB 持久化字段；等待状态不参与失联 Run 扫描，并从 Worker/lease 视角保持未占用。
- 增加 resume 请求契约，只允许 `checkpoint_type + option_id`，不接受客户端日期或任意 Plan patch；Repository 已具备 Checkpoint 选项校验和等待/排队状态转换原语，Graph/Executor resume 行为留到下一阶段。
- 新增 Alembic migration `20260821_01_chat_run_checkpoint`，更新状态约束和 session 活跃 Run 唯一索引。

### 验证

- Checkpoint 与 ChatRun 契约定向测试：5 passed。
- ChatRun 相关回归测试：19 passed、1 warning。
- 涉及 Python 文件 Ruff 检查通过。

### 已知边界

- 阶段 0 尚未接入 `resolve_match_games` ambiguous 适配器、Graph 暂停出口、同一 Run 恢复执行、Checkpoint 事件或前端卡片。

## 18:00 — ChatRun Checkpoint 阶段 1 动态暂停与恢复骨架

### 已完成

- Graph 的 `tools` 节点现在可进入 Checkpoint 终点；`waiting_input` 不经过 evidence、Answer、Critic、response 或 assistant Turn 提交。
- Executor 在 Graph 返回等待状态后先持久化最小快照，再发布 `checkpoint` 与 `status=waiting_input`，停止 heartbeat 并释放 Worker lease。
- 新增 `POST /api/v1/chat/runs/{run_id}/resume`；服务端只接受并校验 Checkpoint 类型与 option id，然后将同一 `run_id` 重新排队。
- 恢复时重建最小 Agent 状态，从快照声明的 `resume_node` 进入 Graph；阶段 1 的 `tools` 恢复路径跳过 Controller，并保留计划、工具结果、证据义务、预算与 fingerprint cache。
- Redis event parser 支持 Checkpoint 事件；等待状态结束当前事件流片段，客户端可用同一 Run 的新 sequence 继续订阅。

### 验证

- 阶段 1 定向测试：28 passed、1 warning。
- API 全量：641 passed、21 skipped、1 warning。
- 变更 Python 文件 Ruff 检查通过。
- Alembic head 为 `20260821_01`；Checkpoint migration offline SQL 生成通过。

### 已知边界

- 阶段 1 还没有生成领域 Checkpoint；`resolve_match_games` ambiguous 适配器、候选选项和 `scheduled_date` patch 留到阶段 2。
- 前端尚未渲染 CheckpointCard；当前阶段只完成后端事件与恢复契约。

## 20:00 — ChatRun Checkpoint 阶段 2 比赛歧义适配

### 已完成

- `pandascore.resolve_match_games` 返回 `data.status=ambiguous` 时，`tools` 节点立即
  生成 `pandascore_match_selection` Checkpoint；选项从候选 Fixture 的 UTC
  `scheduled_at`（缺失时 `begin_at`）确定性生成，随后停止执行，不调用 Valve 映射或
  OpenDota 详情。
- 适配器只对带有 ChatRun `internal_run_id` 的执行启用；无状态 `/plan` 调试路径不创建
  持久化 Checkpoint。
- Checkpoint 选项只暴露服务端生成的 `scheduled_date`，恢复时由 Executor 按已校验的
  `option_id` 写回原 `resolve_match_games` 调用；不接受客户端日期或任意 Plan patch，
  不重新调用 Controller。
- 恢复计划保留原 fingerprint cache：前序成功调用可复用，带日期的比赛解析调用重新
  执行，成功后才继续下游工具链。
- 补齐 `agent_run_waiting_input` 观测事件白名单，避免真实 Graph 进入等待状态时被观测
  层拒绝。
- 同步更新 V3.4-1 设计、整体架构、节点/工具清单、API、Tool 层和 API README。

### 验证

- 阶段 2 定向测试：32 passed、1 warning。
- API 全量：644 passed、21 skipped、1 warning。
- 变更 Python 文件 Ruff 检查通过。

### 已知边界

- 当前只适配 `pandascore.resolve_match_games` 的比赛选择歧义；其它工具的 ambiguous、
  自由文本选择、同日多候选消歧、自动猜测、超时/过期策略和前端 CheckpointCard 均未接入。

## 20:30 — Checkpoint 阶段 2 恢复语义修复

### 已完成

- 恢复比赛选择 Checkpoint 时，先剔除产生 Checkpoint 的旧 ambiguous `ToolResult`、
  dispatch record 与 fingerprint；前序成功调用继续复用，重新带日期执行的
  `resolve_match_games` 成为该 call id 的唯一结果。
- 首期日期 patch 无法区分同日候选；适配器发现任意候选缺少日期或出现同一 UTC 日期时，
  不生成选择卡片，保留既有 explicit ambiguous 边界，避免用户选择后再次停在同一歧义。
- Controller Prompt 明确：赛事总览或“最新战况”在赛事解析后使用
  `pandascore.list_matches`；只有明确要求逐局详情、BP、记分板等比赛拆解时才规划跨源
  比赛详情链。

### 验证

- Checkpoint 匹配选择与 Controller Prompt 定向测试通过。

### 已知边界

- 同日多候选不会进入本期 Checkpoint；它仍需要未来新增可区分的恢复参数后才可接入。

## 20:45 — Checkpoint 阶段 3 前端恢复交互

### 已完成

- `apps/chat` 补齐 `checkpoint` 事件、`waiting_input` 状态和比赛选择 Checkpoint 类型，
  并在 assistant message runtime metadata 中保存 `run_id`、session/request 标识与最后事件序号。
- 新增 `resumeChatRun` API 封装；`CheckpointCard` 只展示服务端问题和选项标签，点击只提交
  `checkpoint_type + option_id`，不把 `value` 或任意计划参数交给客户端解释。
- 等待状态不再被事件转换器当作失败；选择成功后使用 assistant-ui `resumeRun` 在同一
  `run_id` 上从旧消息分支继续订阅，并以 Checkpoint 后的 sequence 作为 `after` 游标。
- 活动 Run 刷新沿用既有 `unstable_resume` 的 `after=0` replay，能够重新得到选择卡片；
  选择失败会保留卡片并允许再次提交。
- 更新 ChatRun 阶段设计、技术架构/API、总体架构和 Chat 前端说明。

### 验证

- `apps/chat`: `npm test`，8 个测试文件、22 个测试通过。
- `apps/chat`: `npm run lint` 通过。
- `apps/chat`: `npm run build` 通过。

### 已知边界

- 阶段 3 仍只支持 `pandascore.resolve_match_games` 的比赛选择歧义；其它 ambiguous、
  自由文本选择、超时/过期策略和同日候选判定不在本阶段。

## 21:00 — Checkpoint 阶段 4 测试与文档交付

### 已完成

- 完成 API 全量回归：Checkpoint 契约、Graph 暂停/恢复、resume 路由、事件回放、取消与
  recovery 边界均纳入当前测试集。
- 补充前端恢复游标测试，验证 Checkpoint 后仍以同一 `run_id` 和指定 `after` sequence
  继续订阅。
- 完成阶段设计蓝图的阶段 4 交付说明；阶段 0—3 的实现边界、API、架构和 Chat 行为文档
  保持一致。

### 验证

- `apps/api`: `uv run pytest -q`，646 passed，21 skipped，1 warning。
- `apps/chat`: `npm test`，8 个测试文件、23 个测试通过。
- `apps/chat`: `npm run lint` 通过。
- `apps/chat`: `npm run build` 通过。

### 已知边界

- 阶段 4 只完成当前比赛选择 Checkpoint 的回归与文档交付，不扩展其它 ambiguous 来源，
  不新增自由文本、默认选择、超时/过期或通用依赖失效机制。

## 21:30 — Checkpoint 恢复执行态重复 dispatch 修正

### 已完成

- 修复 `waiting_input → 同一 run_id resume → tools` 的恢复状态：持久化快照中的旧
  `ToolResult` 与 `ToolDispatchRecord` 继续作为审计数据保存，但不再注入新的内存执行态。
- 恢复状态只保留暂停前成功调用的 fingerprint cache，并排除产生歧义的源调用；前序调用
  cache reuse 时产生本次 Attempt 的新记录，比赛解析调用按已选日期重跑。
- 补充前缀成功调用 + ambiguous 源调用的恢复测试，覆盖计划日期 patch、handler 不重复执行、
  新 dispatch 顺序和 `build_attempt_record` 唯一性校验。
- 更新 V3.4-1 设计和运行时架构文档；不改数据库、API、前端、Checkpoint 契约或工具链。

### 验证

- Checkpoint 恢复定向测试：6 passed。
- 变更 Python 文件 Ruff 检查通过。

### 已知边界

- 本修正只解决恢复后同一 Attempt 的结果/dispatch 重复问题；其它 ambiguous 来源、自由文本
  选择、超时/过期策略和通用依赖失效机制仍未接入。

## 22:00 — Checkpoint 精确 Fixture 选择

### 已完成

- `pandascore.resolve_match_games` 增加可选 `pandascore_match_id` 输入；Provider 在已解析
  Series 与两队匹配的 Fixture 集合中按该 ID 精确选择比赛。
- `pandascore_match_selection` 的服务端 option value 改为精确 Fixture ID，恢复时写回原
  比赛解析调用；日期继续只用于候选标签展示。
- 删除同日候选拒绝逻辑；同日、同两队的多个 Fixture 现在可用既有 CheckpointCard 选择，
  并沿用同一 `run_id` 恢复、前序 fingerprint cache 复用与后续 Valve/OpenDota 工具链。
- 未新增 Checkpoint 类型、Controller 二次调用、数据库迁移、前端请求字段或其它 ambiguous
  适配器。

### 验证

- Checkpoint、PandaScore Provider 与工具定向测试：28 passed。
- API 全量：649 passed、21 skipped、1 warning。
- 本次涉及 Python 文件 Ruff 检查通过。

### 已知边界

- 当前仍只适配 `pandascore.resolve_match_games` 的比赛详情歧义；选项 ID 仅在已解析 Series
  和两队匹配的 Fixture 集合内生效，不是 Valve Match ID。

## 22:30 — OpenDota 比赛选手购买与加点数据透传

### 已完成

- `opendota.match_details` 的选手标准化现在保留完整 `purchase_log` 顺序（包括负数开局前
  时间、消耗品、同秒事件），并生成主栏、背包、当前中立物品、中立强化和中立更换历史。
- 从 `ability_upgrades_arr` 生成按英雄等级位置编号的加点序列；`special_bonus_*` 机械归类为
  天赋，`special_bonus_attributes` 单独标为属性加点，并生成 `talent_selections`。
- Catalog 新增严格的 `get_item_by_internal_name()`，只接受原始内部名及 `item_` 前缀变体；
  未命中保留原始 key 和 `not_found`，不走模糊匹配。
- `opendota.match_details` 新增三个可选 Evidence kind：
  `player_purchase_timeline`、`player_skill_build`、`player_talent_selection`；仅在比赛已解析
  且对应数据非空时产生，旧 `player_scoreboard` 与装备字段保持不变。
- 不改前端、Answer Prompt、输出格式、历史 Catalog、天赋左右分支推断或技能时间轴。

### 验证

- OpenDota match details 与 Registry 定向测试：33 passed。
- 变更 Python 文件 Ruff 检查通过。

### 已知边界

- OpenDota 只提供“第几级选择了什么”，没有技能选择时刻；当前 Catalog 不能可靠还原历史
  天赋左右分支或层级，因此这些事实不会被补造。

## 22:45 — OpenDota 选手进度数据最终验证

### 验证

- Controller golden fixture 已按动态工具目录重新生成，保持 UTF-8、无 BOM、LF。
- OpenDota、Registry、Prompt 定向测试：49 passed。
- API 全量：653 passed、21 skipped、1 warning。
- 本次涉及的 OpenDota、Catalog、工具和测试文件 Ruff 检查通过。
- 全仓 `ruff check apps/api` 仍有 25 个既有 migration 风格诊断，未在本阶段修改。

## 23:00 — OpenDota 选手进度数据收尾

### 验证

- 补充 `test_opendota_domains.py` 的标准化回归后，OpenDota/Registry 定向测试：39 passed。
- 最终 API 全量：654 passed、21 skipped、1 warning。

## 23:15 — OpenDota 装备空槽位标准化修复

### 已完成

- OpenDota 原始装备栏位中的 `0` 或 `"0"` 现在与缺失值一样标准化为 `null`；主栏、背包、中立物品和中立强化不再把空槽位误报为 Catalog `not_found` 物品。
- 补充主栏、背包、中立物品和中立强化四类零值空槽位回归断言。

### 验证

- OpenDota、Registry 定向测试：40 passed。
- 本次涉及 Python 文件 Ruff 检查通过。
- `git diff --check` 通过。
