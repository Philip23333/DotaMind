# DotaMind 进度快照（2026-08-10）

## 02:43 — Ascetic's Cap 运行时排除与同步审计

### 已完成

- 将 Valve Datafeed 中的物品 825 `item_ascetic_cap` 从默认“当前版本可用物品”运行时目录排除；`DotaCatalogRepository` 不加载同步审计，因此 ID 和名称查询均返回 not found，不会向用户展示残缺效果。
- 新增 `CatalogSyncAudit` / `CatalogExcludedEntity`，同步时将该物品记录为 `legacy_or_unclassified`，保留官方英文/简体中文原始描述、未解析 token、状态字段、special value 字段、配方关系和来源 endpoint。
- 排除规则只适用于精确 ID 825 + 内部名 `item_ascetic_cap`。双语身份、三个 token、状态字段、唯一 `AbilityCooldown` special value 或配方关系发生漂移时，直接 fail-fast 并要求重新审核；不会将该规则推广到其他物品。
- 快照写入扩展为五个原子替换文件：manifest、heroes、abilities、items 和仅供开发者查看的 `sync_audit.json`。manifest 数量只统计运行时目录实体，审计条目不得同时出现在运行时目录。
- `DotaMind_V3.3-3_design.md` 已同步运行时排除、审计产物和无残缺用户展示的边界。

### 验证

- Catalog A+B focused：`50 passed`。
- 全量 API pytest：`519 passed, 20 skipped`。
- Ruff、compileall 和 `git diff --check` 通过。
- 针对当前 Valve 7.41e 官方数据的实时审计验证通过：物品 825 被分类为 `legacy_or_unclassified`；原始双语描述和 `duration`、`slow_resistance`、`status_resistance` 三个 token 均保留；状态与配方证据符合已审核形状。
- 完整真实 no-write 构建已越过物品 825，随后在物品 81 的未解析 token 处 fail-fast。该后续数据缺口未纳入本次特例，也没有写入正式快照。

### 当前边界

- `sync_audit.json` 是开发者审计文件，不是 runtime fallback，也不参与 resolver、tool evidence 或 Answer。
- 本次没有猜测 Ascetic's Cap 的缺失数值，也没有把 `%status_resistance%` 等原始 token 暴露给用户。
- 正式 A4 快照仍需解决物品 81 的独立未解析 token 后才能完整生成和审查。

## 02:52 — 物品备注 token 通用渲染修复

### 已完成

- 修复 `normalize_item` 对 `notes_loc` 只清理 HTML、没有执行数值替换的问题。所有物品的英文和简体中文 notes 现在统一使用当前物品的 `special_values` replacement map 进入 `_render`。
- 没有为物品 81 `item_vladmir` 增加特例。当前 Valve 数据已经提供 `lifesteal_creeps_tooltip=12`；修复后官方备注从 `%lifesteal_creeps_tooltip%%%` 正确渲染为 `12%`。
- 未知或缺值的物品备注 token 继续 fail-fast；没有增加原样展示、猜测数值或其他 fallback。
- 新增双语物品备注渲染测试和缺值 token 拒绝测试。

### 验证

- Catalog sync focused：`48 passed`；Catalog A+B focused：`52 passed`。
- 全量 API pytest：`521 passed, 20 skipped`。
- Ruff、compileall 和 `git diff --check` 通过。
- 针对当前 Valve item 81 的独立实时解析通过：英文和中文备注均渲染为 `12%`，残留 token 列表为空。
- 完整 Valve 7.41e no-write 构建成功：`127` 个英雄、`1707` 个技能、`543` 个运行时物品、`1` 条审计排除；当前没有下一同步 blocker，且没有写入正式快照。

### 当前边界

- 本次只修复运行时目录生成前的离线规范化，不改变 resolver、tool、EvidenceGraph 或 Answer 合同。
- 正式 A4 产物已经具备生成条件，仍需执行正式写盘、审查五个快照文件的结构和 diff 后才能收口。

## 03:22 — A4 正式快照与 B2 Catalog resolver 切换

### 已完成

- 正式执行 Valve 7.41e 同步并生成 `app/data/catalog/` 五文件快照：manifest、heroes、abilities、items 和 developer-only sync audit。
- 正式快照包含 `127` 个英雄、`1707` 个技能、`543` 个运行时物品和 `133` 条配方边；审计仅包含物品 825 `item_ascetic_cap` 一条 `legacy_or_unclassified` 排除，且该 ID 不在运行时 items 中。
- 默认 ToolRegistry 已改为先注册 `dota_catalog_tools.register_dota_catalog_tools`；`resolve_hero` 现在只有一个注册，source 为 `official_snapshot`，公开工具名、`data.hero.hero_id` 输出路径和下游引用合同保持不变。
- 从 STRATZ 模块删除旧 `resolve_hero` registration、input model、handler 和 evidence extractor。STRATZ evidence 的英文英雄名索引也改为读取同一个 Catalog repository，避免残留第二套英雄主数据。
- 删除旧 `hero_tools.py`、旧 `app/data/heroes/dota2_heroes.yaml` 和专属 resolver 测试；同步脚本不再生成旧 YAML。`hero_aliases_zh.yaml` 继续作为人工 alias overlay 注入 Catalog。
- Datafeed patchnotes 参数校验允许合法字母后缀（如 `7.41e`），仍只接受 dotted numeric patch + 单个可选小写字母；没有放开任意参数。
- 更新 Controller golden prompt 和当前架构文档，公开新的 Catalog resolver 来源与单路径边界。

### 验证

- 主代理切换相关 focused：`102 passed`；全量 API pytest：`518 passed, 20 skipped`。
- Ruff、compileall 和 `git diff --check` 通过。
- 正式五文件通过 Pydantic、catalog、manifest 和 sync-audit 一致性校验；实际数量与 manifest 完全一致。
- 默认 registry 实际验证：仅一个 `resolve_hero`；“火女”以 exact 命中 Lina / hero ID 25；source 为 `official_snapshot`；snapshot patch 为 `7.41e`。
- STRATZ 既有 `resolve_hero` plan-local reference 合同保持有效；OpenDota registry 未受影响；STRATZ 英文 hero display name 语义未改变。

### 当前边界

- A4 正式快照生成和 B2 `resolve_hero` 归位已经收口；运行时英雄解析不再依赖旧 YAML，也没有网络 fallback。
- 当前 `dota_catalog_tools.py` 只注册已经完成迁移的 `resolve_hero`。英雄属性、技能、天赋树、物品 resolver/info 等后续 Catalog tools 仍按 V3.3-3 的 C 阶段顺序实现。
- 本轮未提交、未暂存。
