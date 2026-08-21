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
