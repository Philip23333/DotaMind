# DotaMind 进度快照 — 2026-08-09

## 代码提交前验证 — V3.3-3 A 阶段

### 已验证

- 专项目录同步测试：`4 passed`。
- `app/integrations/valve`、同步脚本和专项测试的 Ruff 检查通过。
- Valve 集成与同步脚本的 `compileall` 检查通过；`git diff --check` 通过。
- 提交范围仅包含 V3.3-3 A 阶段的 Valve Datafeed transport、目录规范化与校验、离线快照生成、专项测试、设计文档和对齐的进度记录。

### 边界

- 本次验证不宣称真实目录快照已生成。当时真实同步在 Scepter/Shard 展示占位符处 fail-fast；18:37 的后续核查确认 Sand King 字段属于 inactive stale 数据并修正门控。同步始终未提交不完整快照，也未增加猜值或运行时网络 fallback。
- B-E 阶段尚未实现。

## 17:10 — V3.3-3 B1-B4 Runtime Catalog 与 Resolver

### 已完成

- 新增 `app/integrations/valve/catalog_repository.py`：启动期一次加载 manifest、英雄、技能、物品和配方快照，使用当前 Pydantic 模型及 `validate_catalog` 校验；ID 查询返回深拷贝，避免调用方修改全局目录。
- 实现英雄/物品 exact、fuzzy、ambiguous、not_found 解析；索引覆盖中英文名、去前缀内部名和 aliases，物品默认优先最终物品，明确“图纸/配方”时进入 recipe scope。
- 新增 `app/agentic/tools/dota_catalog_tools.py`，将 `resolve_hero` 注册和 handler 从 `stratz_tools.py` 迁出；工具名、`data.hero.hero_id` output path、`hero_identity` mandatory evidence 保持不变，source 改为 Valve committed snapshot，并在结果中披露 patch/generated_at/schema。
- STRATZ 工具只保留 evidence 兼容导出；英雄统计 evidence 的名称索引改为 Runtime Catalog。
- 新增 B 阶段 repository、快照一致性、深拷贝、英雄/物品 resolver、recipe scope 和工具 contract 测试。

### 已验证

- A+B focused tests：`8 passed`。
- B 相关 Ruff 检查通过。

### 边界与阻塞

- 当前工作树仍没有 `app/data/catalog/` committed snapshot；当时真实 Valve 同步在未解析的 Scepter/Shard 占位符处停止，18:37 的后续核查已将其纠正为 inactive 字段门控问题。按设计，`build_default_tool_registry()` 在快照缺失时直接抛出 `CatalogSnapshotError`，不回退到旧 YAML、不访问网络。
- 因此依赖默认 registry 的旧 graph/plan 测试在构造 registry 阶段会明确失败；完整 B 运行时回归必须在 E1 生成并审查正式快照后继续，不提前伪造数据或保留双注册路径。

## 17:12 — B 阶段阻塞边界修正

- 经全量回归验证，若在缺失快照时启用 B2 默认 registry 迁移，会使既有 graph/plan 测试和服务构造全部在启动期失败。因此本次保留现有默认 registry 与旧 hero resolver 运行路径，未宣称 B2 迁移完成。
- `dota_catalog_tools.register_dota_catalog_tools(registry, repository)` 已实现并由注入快照的 focused test 验证；待 `app/data/catalog/` 正式快照可用后，再执行一次性注册迁移并删除旧注册。
- 当前最终验证：A+B 数据层/仓储 focused tests `8 passed`；API 全量 pytest `477 passed, 20 skipped`。这是明确的迁移阻塞，不是运行时 fallback：新 Catalog repository 本身仍对缺失/损坏快照 fail-fast。

## 18:37 — A 阶段 Scepter/Shard 展示语义修正

### 已完成

- `normalize_ability` 仅在 `ability_has_shard=true` 时解析并输出 `shard_loc`，仅在 `ability_has_scepter=true` 时解析并输出 `scepter_loc`；inactive 残留字段输出空字符串且不触发 token 校验。
- active Shard 文本对每个 special value 优先使用非空 `values_shard`，active Scepter 文本优先使用非空 `values_scepter`，均在升级数组为空时回到基础 values；`[0]` 被视为有效升级数组。
- 普通名称、描述、lore 和 notes，以及结构化 `special_values.values/rendered_*` 继续使用基础 values。`granted_by_shard` / `granted_by_scepter` 仍是独立事实，不参与 `has_*` 展示门控。

### 已验证

- 目录同步专项测试：`8 passed`；A+B 数据层/仓储 focused tests：`12 passed`。
- API 全量 pytest：`481 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- 一次不写文件的真实 Datafeed 内存构建已越过 Sand King Stinger 的旧 `shard_loc` 阻塞；随后在另一普通/天赋名称字段遇到 `{s:bonus_AbilityChannelTime}`，正式快照仍未生成，该独立 token 关联问题不在本次升级字段修正范围内。

### 边界修正

- 前文将 Sand King Stinger 描述为“官方缺失有效 Scepter/Shard 占位符”并不准确。该技能当前 `ability_has_shard=false`，其 `shard_loc` 是 inactive stale 数据；正确门控后不再构成同步阻塞，也不能据此认定 Datafeed 缺失当前有效魔晶数据。

## 19:22 — A 阶段跨辅助技能天赋 bonus 解析

### 已完成

- 同步器从 Valve `abilitylist` 中排除物品、天赋和已由 `herodata` 覆盖的能力，仅抓取剩余 English `abilitydata` 作为同步期辅助关系；这些辅助技能只参与天赋 token 解析，不进入英雄能力目录，也不引入运行时网络请求。
- talent bonus 反向索引保留来源 ability ID、内部名、字段、值和 operation；解析顺序为英雄自身能力优先、官方辅助能力次之，并合并中英文天赋展示字段的 token 需求。
- 同一 talent/field 的同值、同 operation 多来源折叠为同一事实并保留来源；值、operation 或结构化列表冲突继续稳定 fail-fast。字段匹配优先 exact，再处理 Valve 的 `bonus_`、大小写和下划线别名。
- 该通用关系已解析 Tinker `tinker_keen_teleport`、Invoker `forged_spirit_melting_strike`、Naga Siren `naga_siren_reel_in`，以及 Tiny/Shadow Demon 的同值多来源和 alias 形态；未硬编码英雄、技能或数值。

### 已验证

- 目录同步专项测试：`16 passed`；A+B 数据层/仓储 focused tests：`20 passed`。
- API 全量 pytest：`489 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- patch `7.41e` 的真实 Datafeed no-write 内存构建已越过全部已知 talent name token，随后在 active `scepter_loc` 的 `%bonus_AbilityCooldown%` 处 fail-fast；未写入或提交不完整快照。

### 当前边界

- 正式 A4 快照仍未形成。新的阻塞不是跨辅助技能的 talent bonus 缺失，而是当前技能升级字段的别名映射：至少 Bane、Venomancer、Lifestealer、Ogre Magi 和 Mars 的激活神杖文本使用 `%bonus_AbilityCooldown%`，而其同一技能 `special_values` 已提供 `AbilityCooldown.values_scepter`。该独立问题留待下一次修改处理。

## 19:34 — A 阶段 Scepter/Shard 升级字段 alias

### 已完成

- Active Scepter/Shard replacement map 对每个官方升级字段同时支持字段原名及派生的 `bonus_<field>` token；`values_scepter` / `values_shard` 继续优先，空升级数组回退基础值，`[0]` 继续视为有效值。
- 映射采用两阶段优先级：先注册真实字段及其大小写/下划线 aliases，再补派生 `bonus_` aliases；真实 `bonus_` 字段不会被其他字段派生 alias 覆盖，同优先级 alias 不同值时稳定 fail-fast。
- Upgrade map 只在对应 `ability_has_scepter` / `ability_has_shard` 为真时构建；inactive 残留升级字段即使存在 alias 冲突也不阻塞。普通名称、描述、lore、notes 和结构化 special values 仍使用基础映射。

### 已验证

- 目录同步专项测试：`19 passed`；A+B 数据层/仓储 focused tests：`23 passed`。
- API 全量 pytest：`492 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- patch `7.41e` 的真实 Datafeed no-write 内存构建已越过 Bane、Venomancer、Lifestealer、Ogre Magi 和 Mars 的 `%bonus_AbilityCooldown%` 激活神杖文本。

### 当前边界

- 正式 A4 快照仍未形成。当前下一阻塞定位为 Lone Druid `Summon Spirit Bear`（ability ID `1342`）普通 `notes_loc` 中的 `%base_magic_resistance%`；同技能官方字段为 `bear_magic_resistance=[25]`。这属于非机械前缀的基础字段语义 alias，仍按 unresolved token fail-fast，未在本次升级 alias 修改中硬编码处理，也未写入不完整快照。

## 19:44 — A 阶段 Lone Druid Spirit Bear 定向 alias

### 已完成

- 按明确产品决策新增严格定向例外：仅当 `ability_id=1342` 且内部名为 `lone_druid_spirit_bear` 时，将普通文本 token `base_magic_resistance` 映射到同一官方记录的基础字段 `bear_magic_resistance`。
- 例外不硬编码数值，不增加全局 `base_` / `bear_` 推断；来源字段缺失、ID/内部名任一不匹配时仍由 unresolved token fail-fast。真实 `base_magic_resistance` 字段优先，若与 `bear_magic_resistance` 值冲突则明确失败。
- 其他英雄或能力即使包含同名 source/token 也不受影响；中英文文本继续共用经身份校验的同一基础 replacement map。

### 已验证

- 目录同步专项测试：`24 passed`；A+B 数据层/仓储 focused tests：`28 passed`。
- API 全量 pytest：`497 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- patch `7.41e` 的真实 Datafeed no-write 内存构建已越过 Lone Druid `%base_magic_resistance%`，没有写入不完整快照。

### 当前边界

- 正式 A4 快照仍未形成。下一稳定阻塞定位为 Bloodseeker `Blood Rite`（ability ID `5016`）中文 `notes_loc` 的 `%castpoint_tooltip%`；英文 note 使用可由 `AbilityCastPoint=[0.3]` 解析的 `%abilitycastpoint%`，中文 token 在当前基础字段中没有 exact match。该中文本地化字段差异不在本次 Lone Druid-only 例外范围。

## 21:10 — A 阶段 Blood Rite 英文权威中文 note

### 已完成

- 按产品决策将 Bloodseeker `Blood Rite`（ability ID `5016`、内部名 `bloodseeker_blood_bath`）的英文 note 作为语义权威；当前错误中文 note 由受审查的英文翻译模板替换为“总时间为 `%delay%` 秒的生效延迟，加上 `%abilitycastpoint%` 秒的施法时间。”
- 翻译模板不硬编码 `2.6/0.3`，仍从 Valve 官方 `delay` 和 `AbilityCastPoint` 动态渲染；英文输出保持不变，不引入在线翻译、运行时 LLM 或全局中文 fallback。
- 特例要求目标英文/中文原文均精确且唯一匹配；英文语义源漂移、中文目标缺失/新增/变化时稳定 fail-fast，避免继续输出过期翻译。其他英雄或能力的 `%castpoint_tooltip%` 不受影响。

### 已验证

- 目录同步专项测试：`30 passed`；A+B 数据层/仓储 focused tests：`34 passed`。
- API 全量 pytest：`503 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- patch `7.41e` 的真实 Datafeed no-write 内存构建已完成全部英雄、技能和天赋规范化，首次进入物品目录处理；没有写入不完整快照。

### 当前边界

- 正式 A4 快照仍未形成。下一阻塞为 `Tome of Knowledge`（item ID `257`，`item_tome_of_knowledge`）英文 `desc_loc` 中的 `%customval_team_tomes_used%`。该 token 表示比赛内“团队已使用知识之书数量”；官方 `special_values` 提供 `xp_bonus=750` 和 `xp_per_use=150`，但没有该动态计数字段。它属于动态比赛状态展示，不是可从静态物品定义还原的数值，仍由同步 fail-fast 暴露。

## 21:33 — A 阶段 Tome of Knowledge 静态描述边界

### 已完成

- 仅对 `item_id=257` 且内部名为 `item_tome_of_knowledge` 的知识之书，删除双语描述末尾包含 `%customval_team_tomes_used%` 的比赛运行时团队计数段；`Use: Enlighten` / “使用：启迪”的静态效果段完整保留。
- `xp_bonus` 和 `xp_per_use` 继续从 Valve 官方 `special_values` 动态渲染，未将团队计数设为 `0`，也未增加全局 `customval_` 忽略规则。
- 英文/中文完整静态描述、唯一动态后缀及后缀位置必须精确匹配；源漂移、目标缺失/重复或不位于末尾时稳定 fail-fast。其他物品出现相同 token 时仍按 unresolved token 失败。

### 已验证

- 目录同步专项测试：`36 passed`；A+B 数据层/仓储 focused tests：`40 passed`。
- API 全量 pytest：`509 passed, 20 skipped`，仅保留既有 Starlette/httpx deprecation warning。
- Ruff、`compileall` 和 `git diff --check` 通过。
- patch `7.41e` 的真实 Datafeed no-write 内存构建已越过知识之书动态计数；全部 127 个英雄的属性、技能、天赋和双语 token 规范化继续完整通过，没有写入不完整快照。

### 当前边界

- 正式 A4 快照仍未形成。下一阻塞为 `Ascetic's Cap`（item ID `825`，`item_ascetic_cap`）英文描述中的 `%status_resistance%`；同样使用该 token 的 Aeon Disk 和 Ceremonial Robe 均有可解析的 `status_resistance` 字段，只有 Ascetic's Cap 当前 `special_values` 为空。该问题位于物品目录，不影响已闭合的英雄/技能/天赋规范化。
