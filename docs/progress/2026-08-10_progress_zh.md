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

## 13:00 — C1-C5 Catalog 查询工具与 EvidenceGraph 收口

### 已完成

- 在唯一的 `dota_catalog_tools` 注册路径中新增 `dota.hero_attributes`、`dota.hero_abilities`、`dota.hero_talent_tree`、`resolve_item` 和 `dota.item_info`；连同 `resolve_hero` 共六个 Catalog 工具。
- 三个英雄数据工具的 `hero_id` 强制引用当前计划前序 `resolve_hero.data.hero.hero_id`；`dota.item_info.item_id` 强制引用前序 `resolve_item.data.item.item_id`。literal、错误工具/路径和前向引用均被拒绝。
- 英雄属性工具输出身份、基础/成长属性、战斗和移动字段；技能工具按 hero ability IDs 原顺序输出非天赋技能及双语描述、等级数值、先天/Scepter/Shard 信息；天赋工具严格输出 10/15/20/25 四层左右分支。
- 物品 resolver 保留 exact/fuzzy/ambiguous/not_found 和明确图纸 scope；物品详情输出完整双语定义，并仅在真实存在组件或升级目标时输出 recipe graph。
- 六工具统一使用 `official_snapshot` source 和 snapshot metadata。Evidence kinds/mandatory 固定为 `hero_identity`、`hero_attributes`、`hero_ability`、`hero_talent_tree`、`item_identity`、`item_definition`；`item_recipe` 仅按实际关系可选产出。
- 补齐 ToolRegistry、Controller catalog renderer、plan validation、plan-local reference execution、EvidenceGraph per-call mandatory 和 producibility 回归；没有新增 intent 固定路由、运行时 Datafeed HTTP 或第三方 fallback。

### 验证

- 主代理 Catalog/C5 focused：`119 passed`；全量 API pytest：`533 passed, 20 skipped`。
- Ruff、compileall 和 `git diff --check` 通过。
- 实际 evidence 链验证：英雄链产出 identity、attributes、有序 ability 和 8 条 talent 分支证据；BKB 产出 identity/definition/recipe；知识之书只产出 identity/definition，显式要求 recipe 时正确报告缺失。

### 当前边界

- C1-C5 已完成；尚未修改 D 阶段的 Controller Supported/Unsupported 描述、自然回答静态目录规则或完整 graph 自然回答回归。
- 本节改动尚未提交。

## 13:50 — D1-D3 Controller/Answer/Graph 与 E1 真实抽查

### 已完成

- Controller Supported/Unsupported 增加英雄属性、技能/先天/Scepter/Shard、四层天赋、物品定义/价格/效果/配方/中立等级，并明确热门、胜率、推荐和强弱判断必须由统计 evidence 支撑。
- 增加莉娜技能、莉娜属性+天赋复用一次 resolver、BKB 价格+配方三个 plan-local reference 示例；没有增加 intent 专用路由。
- 唯一 `natural_language_answer` 路径新增 Catalog evidence 规则：区分 base/gain、技能等级数组、天赋层与左右、普通/先天/Scepter/Shard、物品本体/图纸/组件/升级目标，并披露 patch/generated_at；禁止从静态定义推断推荐、热门度、加点或天赋胜率。
- Graph 端到端覆盖英雄属性、技能、天赋、组合查询、BKB 定义+配方和无配方物品；成功路径均经过 Tool→Evidence→Answer→Critic，并覆盖 resolver ambiguity/not_found、坏引用、缺 recipe evidence 和 Answer LLM error。
- E1 对正式 7.41e 快照完成人工抽查：Lina/25 的属性、普通技能、先天 Slow Burn、Scepter 授予 Flame Cloak、Shard 升级 Laguna Blade 和四层天赋完整；Blink Dagger 主动效果及 BKB 的 Mithril Hammer/Ogre Axe 组件关系完整。

### 验证

- 主代理 D focused：`73 passed`；D 阶段完成时全量 API pytest：`548 passed, 20 skipped`。
- Ruff 和 `git diff --check` 通过。
- 真实抽查只读取 committed Catalog snapshot，没有请求期 Valve/STRATZ/OpenDota 网络访问，也没有 mock Catalog 业务数据。

### 当前边界

- D1-D3 与 E1 已完成；保持单一自然回答路径、现有流式行为和 output contract，不新增卡片或第二 reviewer。
- 尚待 E2 最终全量门禁、文档一致性检查和 Git 提交。

## 13:51 — E2 质量门禁与 V3.3-3 阶段收口

### 已完成

- 对 C/D 新增的六个 Catalog 工具、Controller 能力边界、Answer 规则和 Graph 成功/失败路径执行最终全量回归。
- 更新当前架构文档，记录唯一 Catalog 注册路径、plan-local resolver 引用、EvidenceGraph 义务、静态/统计边界和单一自然回答路径。
- 中英文当日进度结构和事实保持一致；未修改前端，也未声明无关前端测试。

### 验证

- 全量 API pytest：`548 passed, 20 skipped`。
- Ruff（app/tests/scripts）、compileall 和 `git diff --check` 通过。
- 唯一非阻塞告警是既存 Starlette/httpx deprecation warning。

### 阶段结论

- V3.3-3 的 A-E 实施顺序已经闭合：正式 Valve 快照、Runtime Catalog/resolvers、六个查询工具、EvidenceGraph、Controller/Answer/Graph 回归及真实抽查均完成。
- 当前改动已满足提交条件；不包含推送远端操作。

## 14:15 — 英雄技能回答格式与查询粒度收口

### 已完成

- Controller 明确区分完整英雄技能查询与单技能查询：完整查询固定执行一次 `resolve_hero`，再执行 `dota.hero_abilities` 和 `dota.hero_talent_tree`；单技能查询只执行 resolver + abilities，除非用户同时询问天赋。
- Answer 禁止向用户展示 `has_shard`、`has_scepter`、`is_innate`、`special_bonus_*`、`talent_internal_name`、`internal_name` 等内部 schema/token 名，改用“魔晶升级”“神杖升级”“先天技能”等自然标题。
- 完整技能回答固定为英雄双语身份与快照、按 Catalog 顺序逐技能详情、末尾简洁天赋表；天赋表列为“等级｜左侧天赋（中文 / English）｜右侧天赋（中文 / English）”。
- 完整技能回答不再生成重复的“技能分类汇总”和“相关天赋”章节，也不在数值后暴露 talent internal token。
- 单技能回答只输出用户指定技能，不附其他技能、分类汇总、相关天赋或完整天赋树。
- 保持唯一 `natural_language_answer` 路径和原 Catalog tool/evidence payload，不增加 deterministic formatter、卡片或第二回答实现。

### 验证

- Controller/Answer/Graph focused：`70 passed`；全量 API pytest：`550 passed, 20 skipped`。
- Ruff、compileall 和 `git diff --check` 通过。
- 使用正式 Monkey King Catalog evidence 的 Graph 回归确认完整查询包含 ability + talent evidence，单技能查询不包含 talent evidence；用户可见示例含天赋表且不含内部 token。

### 当前边界

- 格式由唯一 Answer LLM 的明确系统规则约束，不引入第二套确定性渲染器；Catalog 原始结构字段继续保留在内部工具证据中供审计。
- 本节改动尚未提交。

## 21:30 — 物品配方数据与回答格式修复

### 已完成

- 审查并清理中断 diff：本次仅保留 Repository、`dota.item_info`、Answer 格式、对应测试及配方文档；多轮对话记忆相关改动全部移出本次修复。
- `DotaCatalogRepository` 新增通过成品 ID 或图纸 ID 查询同一官方配方边的深拷贝接口；基础物品不会因为作为组件而被误判为合成装备。
- `dota.item_info` 现在输出图纸、组件和真正的进一步升级目标定义，包含中英文名、价格、`special_values` 与可审计成本明细；成品自身只保留在原始 edge 的官方 target 中。
- 以正式 7.41e 快照的希瓦的守护验收：图纸 118 为 1250 金币，组件 9/1847/1872 为 1400/950/900，计算总价 4500，与成品价格一致；未修改快照，也未增加英雄/物品硬编码特例。
- Answer 规则固定合成物品的“组件（中文名（English））｜价格｜属性”表格并单列图纸；基础物品只显示双语名、价格和属性；存在图纸证据时不得声称无图纸，只有成本不一致时才提示异常。
- 同步 V3.3-3 设计和当前架构中的配方 edge、图纸和成本证据说明。

### 验证

- Repository/Tool/Answer focused：`38 passed`。
- 全量 API pytest：`552 passed, 20 skipped, 1 existing Starlette/httpx deprecation warning`。
- Ruff、compileall 和 `git diff --check` 通过。

### 当前边界

- 本次不处理 compact Turn、多轮组件引用或历史实体记忆；“上面三个配方物品售价是多少”仍作为后续独立问题。
- 不重新生成 Catalog 快照，不增加第三方或网络 fallback；全部改动尚未提交。

## 22:38 — 通用 discourse graph 会话记忆

### 已完成

- 用通用 `DiscourseState` 替换 Turn 中领域专用的 `resolved_entities`：支持开放字符串 kind/label、referent、ordered group、link、focus 和 grounding；拓扑、ref、状态和数量边界由模型与 `ConversationPolicy` 校验。
- 新增异步 `DiscourseExtractor`，只接收上一份 available discourse、当前完整 query、当前完整 answer 和结构边界；不读取或反解析 300 字符的 `response_summary`，不保存 ID、价格、属性、胜率或其他事实值。
- 抽取失败允许一次确定性校验反馈重试；第二次失败写入 `unavailable` 空图并记录低基数 discourse 指标。业务回答成功时不会因记忆抽取失败而改写状态，后续依赖该记忆时由 Controller 暴露 `context_missing`。
- `PlanService._build_turn()` 改为异步，safe failure 不运行抽取；clarification 可继承上一份 discourse 并将当前 query/澄清问题交给抽取器；`ChatRunExecutor` 在 PostgreSQL Turn 提交前 await compact Turn 构建。
- Controller history 渲染为转义后的对象/集合/关系/焦点数据；直接回忆改为 `recall_referent` + `discourse ref`，服务端确定性返回 referent 名称或 group 成员名称。kind/label 不参与固定路由，当前事实仍须当前轮工具调用与证据确认。
- Redis Turn 严格升级到 `schema_version=2` discourse DTO；只写 v2，不从旧 `response_summary` 重建，旧 session key 可失效。PostgreSQL 旧 JSONB Turn 缺少 discourse 时按默认 empty 加载。
- 新增 Conversation Memory 设计说明并同步当前架构、Controller 设计、V3.2 设计引用和 Controller golden prompt。

### 验证

- discourse/summary/render/decision/Redis focused：`110 passed`。
- 全量 API pytest：`561 passed, 20 skipped, 1 existing Starlette/httpx deprecation warning`。
- 启用本机真实 Redis（`DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`）时，Redis 集成 `14 passed`，完整 API pytest `576 passed, 5 skipped`；warning 不变。
- Ruff focused、完整 API Ruff、compileall 和 `git diff --check` 在最终门禁中执行。
- 覆盖 Lina 集合与顺序指代、希瓦式多个组件关系、开放 `guide` kind、多个 group、非法 ref/拓扑、超限、grounding 失败、抽取器不可用、失败轮不可复用、历史非证据和 Redis v2 round-trip。

### 当前边界

- discourse 是指代和集合选择记忆，不是 EvidenceGraph、事实缓存或当前轮证据；历史名称和 ID 不能直接写入下游工具参数。
- `response_summary` 仍保持现有 300 字符回答摘录合同；本轮没有通过增加其长度解决多轮引用。
- 当前改动尚未提交；本轮真实 Redis 验证使用随机测试前缀并清理精确测试 key。
