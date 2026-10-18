# STRATZ 单局详情：来源事实与治理限制

本文件保存重新发现成本较高的 Provider 事实，不是实施进度或完整 API
字段表。目标 DTO 由 [Game Detail Data Contract](../agent/game_detail_data.md)
拥有；本文件中的实测结论不能直接提升为通用转换规则。

## 核验范围

- Valve 对局 ID：`8960991322`，正式时长 `3862` 秒（`64:22`），十名玩家。
- 2026-10-18 使用现有授权访问 [STRATZ GraphQL API](https://api.stratz.com/graphql)，
  查询 `match(id: 8960991322)`、相关类型定义及 `gameVersionId=189` 的 NPC 常量。
  比较对象为此前读取的 [OpenDota 对局源记录](https://api.opendota.com/api/matches/8960991322)。
- STRATZ 主详情读取时间为 `2026-10-18T03:33:00.053486Z`；OpenDota 记录读取时间为
  `2026-10-17T17:20:39.888836Z`。二者不是同时采样，不据此认定细小终局差值是错误。
- 查询覆盖选定字段，不代表完整 STRATZ 数据集。未下载录像、提交解析任务或测试新的
  `GameDetailService` 实现。API 内容和可用性可能变化。

## 身份、终局与分钟数据

| 项目 | 本场核验事实 | 使用边界 |
|---|---|---|
| 身份 | 两源对局 ID、时长、十人账号/英雄/槽位一致；STRATZ `playerSlot` 为 0–4、128–132 | 不用玩家数组位置关联；不能据一场认定所有版本编码相同 |
| 终局统计 | K/D/A、正反补、净值、英雄伤害、建筑伤害、治疗共九项 × 十人，90 个值一致 | 不等于所有新增字段语义已验证；公开 DTO 仍遵守删除净值、替换终局差值的契约 |
| OpenDota 分钟数据 | 十人 `times/gold_t/xp_t` 等有 65 项，十人均没有 `networth_t` | 缺少净值不能推导为没有累计收入或经验 |
| STRATZ 分钟数组 | 每人 `stats.networthPerMinute` 65 项，`goldPerMinute/experiencePerMinute` 64 项；团队优势数组 66 项 | 点值、区间量和起始桶分别核实，不能统一按数组下标赋时刻 |
| 经验 | 十人 `stats.experiencePerMinute` 前缀和与 OpenDota `xp_t[1:]` 共 640 个值相符 | 支持本场候选转换，不验证其他数组或所有历史版本 |
| 累计金币 | Satanic 的有效 `goldEvents` 求和 43,182，与 OpenDota 最后分钟 `gold_t=49,310` 不一致 | 不能把金币事件求和或 GPM × 时间当成完整累计收入 |
| 团队优势 | STRATZ 字段为 `radiantNetworthLeads/radiantExperienceLeads`；schema 描述起始桶为 −60 至 0 秒 | 净值优势不能填入 OpenDota `radiant_gold_adv`；相同长度也不能证明轴一致 |
| 末端边界 | Satanic 一条末端更新的净值为 40,421，终局值为 40,422 | 最后分钟或最近更新不自动等于同一终局时刻 |

`gold_t` 是累计获得金币，既不是钱包余额，也不是剩余资产净值。公开字段名使用
`cumulative_gold_earned`。终局累计金币与净值差需要可靠的同一时刻输入；当前证据
不能保证这一输入，不能以最后整分钟值凑出“损失金钱”。

## 死亡事实

- 本场原始 STRATZ `deathEvents` 共 422 条，终局死亡合计 65；原始 `killEvents`
  共 221 条，不能直接按条数计算英雄击杀。额外记录的完整含义尚未验证。
- `playbackData.goldEvents.reason="DEATH"` 共 65 条，逐人数量与终局死亡一致。
  零扣款出现在关联死亡记录的 `goldLost`，本场 DEATH 金币 `amount` 没有零值；
  两个字段不能混同，也不能要求死亡扣款大于零。
- 本场 `goldFed>0` 的死亡记录恰与这些时间对应，不构成通用过滤器；
  `timeDead>0` 会得到 100 条，也不是有效规则。
- Collapse 终局死亡五次。OpenDota 英雄 `kills_log` 只能定位其中四次，
  `killed_by` 另有一次泉水归因；STRATZ 在 `3844` 秒有 DEATH 金币记录及
  对应 `goldLost=1117` 的死亡记录，但 `attacker=null`。这支持定位死亡，不能仅凭
  STRATZ 空攻击者断言泉水击杀。OpenDota 聚合归因也不能凭空生成时间。

正式采用候选规则前仍需其他真实样本：零扣款、野怪/泉水/小兵击杀、重生、
召唤物/幻象、同秒多记录，以及缺失日志。终局死亡、已定位死亡、未知时间事实和
未关联数量分别保留，不将差额伪造为事件。

后续实现核验另取 `9040460429` 和 `9040578015` 的真实 STRATZ 记录。三场合计
203 条 DEATH 金币事实，30 名玩家逐人数量与终局死亡相符；三个样本中该原因的
`isValidForStats` 均为 false，因此不能用此标志过滤死亡事实。三个样本中亦出现
`-goldEvents.amount != deathEvents.goldLost`，例如本场 2297 秒为 694 与 282。
两者不是已验证的同一指标，不以金额相等连接或替代。

初版以明确 DEATH 事实保留所属玩家和时间；只在所属玩家英雄、时间和一对一关系
明确时附加 `deathEvents` 属性。多条候选保持属性未知；不为对齐终局统计删改事实。
`attacker` 对应唯一同场英雄时仅提供击杀归属，实际攻击单位仍未知，不自动说成英雄
本体、召唤物或泉水。上述样本包含幻象噪声、零 `goldLost` 和冥魂大帝，但并未验证
所有重生/非英雄击杀的编码，新增编码仍按覆盖缺口处理。

## 肉山、魔方、建筑与消息编码

| 类别或路径 | STRATZ 本场返回 | OpenDota 对照与治理结论 |
|---|---|---|
| `chatEvents.type=117` | 1982 秒（33:02）、2839 秒（47:19） | 与明确魔方事件同秒，可保留事件类型和时间 |
| `chatEvents.type=9` | 0 条 | OpenDota 明确肉山击杀在 1795、2452、3038 秒；STRATZ 空列表不证明比赛没有肉山 |
| `goldEvents.reason="ROSHAN"` | 五个奖励时点：1795、1982、2452、2839、3038 | 同时包含三次肉山与两次魔方，不可计为五次肉山击杀 |
| `chatEvents.type=8` | 0 条 | OpenDota 三次不朽盾事件在 1795、2452、3039 秒；库存出现盾不自动等同精确拾取事件 |
| `chatEvents.type=3/2` | 塔 13 条、兵营 0 条 | OpenDota 有 18 条建筑记录；初版具体建筑整类采用 OpenDota，不把两边逐条拼为完整列表 |
| `towerDeaths`、`playbackData.buildingEvents/towerDeathEvents/roshanEvents` | 均为空 | 不能补出本场缺失类别；`roshanEvents` 所查结构为血量/状态，并非专用击杀列表 |
| `towerStatus`、十人 `csEvents` | 14 个状态容器中的塔/前哨列表为空，十人补刀事件均为空 | 本场不能作为精确目标死亡的替代路径 |
| 首血 | `firstBloodTime=56`；明确首血消息为 79 秒 | OpenDota 报告/事件均为 79；保留 STRATZ 内部冲突，不静默覆盖 |

魔方消息中的 `fromHeroId` 分别指向 Bane 和 Lifestealer，`value=3`、
`isRadiant=false`；这些载荷的逐事件含义未核实，不能直接称为击杀者或奖励金额。

消息类型来自 Clarity 保存的 Valve protobuf：
[dota_usermessages.proto](https://github.com/skadistats/clarity-protobuf/blob/master/src/main/proto/dota/common/dota_usermessages.proto)。
核验文件 SHA-256 为
`1152180a30ba9360088aae0cd5687d1ec0279ddc08c4fc7ab65818a72e429675`。
已核对编码为 2 兵营、3 塔、4 反补塔、5 首血、8 不朽盾、9 肉山、10 信使、
117 魔方、119 肉山战旗。类型映射不自动验证消息参与者、队伍或奖励字段。

STRATZ 该历史版本 NPC 常量中，133 对应 `npc_dota_roshan`，861 对应
`npc_dota_miniboss`。它们属于 STRATZ NPC 命名空间，不能作为 Valve `hero_id`。
先按版本转换为确切内部名，再走本地单位映射。

## 装备、升级与其他限制

- `stats.inventoryReport` 每人 67 条，所查类型无显式时间；
  `playbackData.inventoryEvents` 共 1912 条，有显式时间和槽位。只以后者生成带时间
  装备观察，不推测前者每项对应哪一分钟。
- `playbackData.abilityLearnEvents` 共 207 条，包含时间、技能及等级字段；
  等级编码需核实，不把升级序号直接当作英雄等级。
- OpenDota 购买记录 705 条，STRATZ `stats.itemPurchases` 456 条、
  `playbackData.purchaseEvents` 349 条。数量不同不证明优劣或语义一致；
  不合并两种列表，不从购买记录推导合成、出售、交付或完整库存。
- 两源买活均为 13 条，但查询到的 STRATZ `cost` 全为 0；不据此宣称免费买活。
- STRATZ `isStats=false` 时上述大量字段仍存在；该标志含义未确认，不能否定整份数据。
- 本次选定主详情的紧凑 JSON 为 1,286,285 字节（含部分重叠 stats/playback 字段），
  gzip 测试为 71,038 字节。这不是目标 DTO 大小，也不是完整来源对象大小上限。

目标采用固定字段组/事件类别来源表，分别记录实际来源、读取时间和覆盖范围。
Provider 错误不是空列表，部分缺失也不使其他可用统计失效。
