# DotaMind 进度快照 — 2026-08-07

## 20:17 — V3.3-3 Valve 静态游戏目录设计合同

### 已完成

- 新增 `docs/design/versions/DotaMind_V3.3-3_design.md`，冻结 Valve Datafeed 离线同步、双语静态目录、规范化、Catalog Repository、查询工具、EvidenceGraph 和自然回答边界。
- 实施顺序固定为 A 数据源与快照、B Runtime Catalog 与解析器、C 查询工具与 Evidence、D Controller 与自然回答、E 真实同步与质量收口。
- 明确静态英雄/技能/天赋/物品定义来自 Valve committed snapshot；STRATZ/OpenDota 只承担使用率、胜率、出装和天赋选择等比赛统计。
- 明确 V3.3-3 不实现 VPK 导入、图片/前端卡片、热门出装或天赋胜率，不新增固定 intent pipeline 或运行时网络 fallback。

### 已验证

- 计划对照当前 `sync_game_data.py`、英雄 resolver、ToolRegistry、EvidenceGraph、Controller Prompt 和 V2.5/V3.2 架构边界编写。
- 当前阶段只新增设计与进度文档，未修改同步脚本、runtime catalog、工具、Prompt、API 或前端。

### 边界

- 仅 A1 设计合同完成；A2-A5、B、C、D、E 尚未实现。
- 后续每个工作项必须按设计顺序完成验证并追加到当天中英文进度快照，不得提前声明后续阶段完成。

## 21:05 — V3.3-3 A2-A5 数据源与快照实现

### 已完成

- 新增 `app/integrations/valve/datafeed.py`，将 Valve Datafeed 收敛为固定官方 host、双语 locale、有限 retry/timeout 的可测试 transport；只允许 hero/ability/item/patch manifest endpoint，不接受任意 URL。
- 新增 `app/integrations/valve/catalog.py`，实现 manifest、hero、ability、talent tier、item、recipe 和 bundle 模型，以及 ID/内部名双语 join、HTML/entity 清理、special value 与 talent bonus 占位符渲染、天赋树/配方图/悬空引用 fail-fast 校验。
- 扩展 `scripts/sync_game_data.py`：全量同步先在内存中构建规范化 bundle，写入同目录临时文件并校验后再替换 `app/data/catalog/manifest.json`、三个 catalog 文件；保留既有 hero YAML 和 patch JSON 离线生成。
- 新增 `tests/test_dota_catalog_sync.py`，覆盖 transport retry/endpoint 边界、双语合并、HTML、普通 special value、talent bonus、Scepter、天赋层、未解析 token、ID 不一致和快照 schema round-trip。

### 已验证

- focused pytest：`4 passed`。
- Ruff：`app/integrations/valve`、同步脚本和目录测试通过。
- `python -m compileall`、`git diff --check` 通过。
- 真实 Datafeed 探测确认当前返回 127 个英雄、544 个物品，双语列表/详情 ID 与内部名可 join；同步器按合同在写入前检查失败。

### 边界与阻塞

- 本次未提交不完整的生产快照：真实同步在 Valve 当前数据的 `sandking_scorpion_strike.shard_loc` `%caustic_damage_pct%`（以及同类缺失的 Scepter/Shard 占位符）处按设计 fail-fast。该值不在当前 ability/talent special values 中，不能猜测或用运行时 fallback 补齐。
- A2-A5 的代码与测试合同已实现；完整 committed catalog 快照需 Valve Datafeed 补齐这些官方占位符后重新运行同步，再进入 B 阶段 Runtime Catalog。

## 21:09 — A 阶段回归门禁

### 已验证

- API 全量 pytest：`473 passed, 20 skipped`（保留 1 个既有 Starlette/httpx deprecation warning）。
- A 阶段新增 focused pytest 仍为 `4 passed`，Ruff、compileall 和 `git diff --check` 均通过。

### 边界

- 本次没有把失败的真实同步结果写入 `app/data/catalog/`，因此 B 阶段仍未开始，运行时没有新增网络回源路径。

## 21:11 — A 阶段最终验证

- 修正 talent bonus 按 talent internal name 隔离，避免同名字段（例如 `AbilityCooldown`）跨天赋串值；同时扩大默认展示 token 检查到名称、lore、notes。
- focused pytest：`4 passed`；全量 API pytest：`473 passed, 20 skipped`；Ruff、compileall 和 `git diff --check` 继续通过。
