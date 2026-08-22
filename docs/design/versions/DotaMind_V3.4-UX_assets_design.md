# DotaMind V3.4 UX — 技能与 PandaScore 战队本地图标

## 范围

本设计只覆盖两类展示资产：Valve Catalog 普通技能图标和 PandaScore Dota 2
战队 Logo。不改变 Controller 路由、Evidence 可见性、Answer 事实选择或模型
生成 URL 的边界。Answer 继续输出有证据支持的名称，Chat 依据本地路径确定性
插入 Markdown 图标。

## Valve 技能资产

`scripts/sync_game_data.py --images-only` 在原有英雄和非配方物品同步之外，
同步 `not is_item and not is_talent and not is_innate` 的普通技能：

```text
app/data/catalog/images/abilities/{ability_id}.png
/api/v1/assets/dota/abilities/{ability_id}.png
```

技能下载复用现有并发、staging 与整目录原子替换；普通技能缺图和英雄/物品
一样使 Catalog 同步失败。技能 evidence 和 `dota.hero_abilities` 的序列化结果
增加 `ability_image_path`；天赋、全属性加点和未解析技能为 `null`。路径由稳定
ID 运行时派生，不写入 Catalog JSON。

## PandaScore 战队资产

战队资产与 Valve Catalog 分开维护：

```text
app/data/esports/teams/manifest.json
app/data/esports/teams/{pandascore_team_id}.{png|jpg|webp}
/api/v1/assets/esports/teams/{pandascore_team_id}.{png|jpg|webp}
```

同步脚本默认先按 `begin_at` 取得最新 10 个 Dota 2 Series，再读取每个 Series 的
upcoming/running/past Fixture，并从 `opponents[].opponent` 去重出战队。`--series-limit`
可调整 Series 数量；在 Series/Fixture 读取成功后才构造 staging manifest 并原子替换整个
`teams` 目录。无 Logo、非法 Logo URL 和单张下载失败只记录并跳过；Series/Fixture 分页、
认证或整体请求失败退出非零并保留旧快照。`--force` 禁止复用 source URL 未变化的旧图片。

`PandaScoreTeamAssetRepository` 只读本地 manifest 和文件，不联网；缺 manifest、
条目或图片时返回 `None`。PandaScore Fixture 展示投影仅在本地命中时在
`opponents[].opponent.team_image_path` 附加路径，原始队伍 ID、名称和解析输入不变。

## Chat 展示

`catalog_visual_entities` 支持 `ability` 和 `team` 两种本地实体：

- 技能加点箭头序列使用 `md` 技能图标；天赋和全属性加点保持纯文本。
- 赛果、对阵和 BP 标题中的战队 Logo 使用本地路径，普通段落为 `md`，表格为 `sm`。
- 只接受 `/api/v1/assets/dota/...` 与 `/api/v1/assets/esports/teams/...`；PandaScore
  CDN URL 不进入 Chat Response、数据库紧凑响应或浏览器。
- 无本地命中时保留纯文字；已保存的历史回答不重新补图。

## 验收边界

- 同步脚本与 transform 不在请求路径下载图片。
- 本地静态路由和 repository 缺失资源不阻断比赛查询或文字回答。
- API/Chat 定向测试覆盖技能路径空值边界、战队分页/原子替换/Logo 跳过、fixture
  投影、紧凑响应、技能箭头和战队图标；既有英雄、物品、BP 与出装图标回归不变。
