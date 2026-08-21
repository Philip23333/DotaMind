# 2026-08-22 进度快照

## 01:00 — Markdown 比赛详情信息密度增强

### 已完成

- 比赛详情 Answer 模板改为每队一张横向 BP 表：首列为顺序标签，后续七列展示本队的选择与禁用顺序。
- 选手表改为 `选手 / 英雄 | K/D/A | 经济 | 装备 | 技能加点与天赋`；普通比赛详情只显示加点及天赋数量摘要，装备按主栏、背包、中立和强化分组。
- 购买、加点或天赋 evidence 存在时，Answer 获得按需“出装、加点与天赋”章节规则；只有当前问题明确要求时，才展开目标选手的完整购买顺序、加点和实际天赋选择。
- Chat 继续只渲染 Markdown：横向 BP 英雄名确定性替换为中尺寸图标且不显示名称；合并英雄列与主装备使用中尺寸图标，背包、中立物品和强化使用小尺寸图标。
- Markdown 表格增加横向滚动容器；未新增图标尺寸、结构化比赛面板、HTML 折叠、Controller 路由或数据层契约。

### 验证

- Answer 定向测试：18 passed。
- Chat `dotamind-api` 定向测试：11 passed。

### 已知边界

- 纯 Markdown 不提供真实折叠交互；普通比赛详情不自动渲染十名选手的完整购买和加点日志。
- 当前没有离线技能或天赋图标资产，技能加点与天赋详情保持 evidence 支撑的文字和 Markdown 表格。

## 01:05 — Markdown 比赛详情全量验证

### 验证

- API 全量：655 passed、21 skipped、1 warning。
- Answer Prompt 与定向 Ruff 检查通过。
- Chat 全量：8 个测试文件、24 个测试通过。
- Chat ESLint 与 Next.js production build 通过。
- `git diff --check` 通过。
