# 2026-08-16 进度快照

## 12:30 — P2.2 赛事届次解析、运行时失败状态与 Chat UI

### 已完成

- `pandascore.resolve_competition` 增加可选 `year`，兼容从 query 中解析四位年份，并在参数年份冲突时返回受控 validation error。
- 赛事候选按 series/full label、parent league、label substring 采用 3/2/1 匹配等级；缺省年份时按进行中、最近历史、最近未来的时间语义选择，不依赖 API 数组顺序、当前年份或固定赛事 ID。
- 成功解析结果增加 `selection` 元数据；`competition_identity` 仍是唯一 mandatory evidence，ambiguous/not_found 不产生身份 evidence。
- 公共 runtime 工具状态增加 `handler_entered`、`dispatch_stage` 和安全映射后的 `failure_code`；实时工具事件同步带有执行阶段信息，raw exception、内部引用和上游正文仍不公开。
- Chat UI 增加 PandaScore/OpenDota 中文工具名、友好失败文案和“未执行”展示；持久化响应与实时事件使用同一稳定错误映射。
- 未新增 intent 路由、固定 TI ID、当前年份硬编码、API endpoint 或 fallback。Controller 增加的是跨赛事通用的范围澄清与年份保留规则，并同步动态目录 golden；未加入固定问句路由。

### 验证

- `uv run --project apps/api pytest apps/api/tests -q`：610 passed，21 skipped，1 warning。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests`：通过。
- `apps/chat`：`npm test` 10 passed；`npm run lint` 通过；`npm run build` 通过。

### 已知边界

- 当前 Controller prompt 仍遵循动态 ToolRegistry 目录与已有通用澄清语义；未按 intent 增加赛事固定 pipeline。
- PandaScore 免费 Fixture 的 Valve ID 缺口和第二阶段跨源推断边界不变；本阶段只改赛事届次选择和公开错误展示。

## 13:42 — P2.2.1 修复赛事默认届次与历史年份查询

### 已完成

- Controller 规则明确：已命名周期性赛事缺少年份不需要澄清，调用 resolver 时省略 `year`；显式年份必须保留；真正缺少赛事/战队/选手主体时仍返回 clarification。
- `pandascore.resolve_competition` 描述同步声明缺少年份时选择最新届，且不允许仅因年份缺失追问。
- `PandaScoreCompetitions.list_series(year=...)` 在明确年份时发送 `filter[year]`，缺省年份不发送；resolver 先按年份建立 eligible rows，再进行名称匹配和主赛事/资格赛消歧。
- 保留无年份的 active → latest historical → nearest future 语义，显式年份不存在时返回 `not_found`，不回退到其他年份。

### 实时联调

- 独立 8002 API 矩阵：`现在TI的最新战况如何？` 与 `The International 最新战况如何？` 均生成 `tool_plan` 且省略 `year`；`TI 2025 最新战况如何？` 生成 `year=2025`；`现在最新战况如何？` 返回 clarification。
- 真实执行确认：无年份选择 Series `10828` / year `2026`；显式 2025 选择 Series `9555` / year `2025`，后续 `pandascore.list_matches` `handler_entered=true`；独立 API 已停止，8001 未修改。

### 边界

- 未增加 Controller 决策校验器、intent 路由、历史 fallback、固定年份或 Series ID；Runtime 与前端错误展示保持不变。

### 最终验证

- `apps/api/.venv/Scripts/python.exe -m pytest -q`：612 passed，21 skipped，1 warning。
- `apps/api/.venv/Scripts/python.exe -m ruff check app tests`：通过。
- `apps/chat`：`npm test -- --run` 为 10 passed（5 files）；`npm run lint` 通过；`npm run build` 通过。
