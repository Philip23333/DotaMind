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
| 分钟累计金币 | Satanic 的有效 `goldEvents` 求和 43,182，与 OpenDota 最后分钟 `gold_t=49,310` 不一致 | 不把金币事件求和或 GPM × 分钟边界当成精确分钟累计收入；后文的终局 GPM 推导口径是独立指标 |
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

## 三场补充核验：报表字段

2026-10-19 再次查询 STRATZ schema/选定字段及 OpenDota 记录，比较
`8960991322`、`9040460429`、`9040578015`。以下是样本事实及候选映射的边界，
不表示生产投影或报表已经实现。宽查询包含重叠与诊断字段，不是生产查询模板。

| 数据 | 核验结果 | 采用边界 |
|---|---|---|
| 终局 11 项 | 30 人 K/D/A、等级、正反补、GPM/XPM、英雄/建筑伤害、治疗，共 330 个值与新取 OpenDota 相符 | 支持 STRATZ 供应这些明确终局字段；不能证明所有未来场次一致 |
| 终局累计金币 | STRATZ 玩家类型未发现独立 `totalGold/goldEarned`；`floor(goldPerMinute × durationSeconds / 60)` 与 OpenDota `total_gold` 共 30 人一致 | OpenDota 本身就是相同公式，不是独立精确末帧计数的交叉验证。可提供带推导来源的终局累计金币；不补分钟曲线或精确净值差 |
| 双方比分 | `radiantKills/direKills` 为分桶击杀，逐桶求和与两源终局比分共六个值相符 | 不取数组末项、长度或十人英雄击杀之和。首场玩家击杀和 30:34，双方比分 31:34 |
| 等级 | `playerUpdateLevelEvents` 共 770 条，30 人单调且末端与终局等级一致 | 可用明确时间更新生成最近已知等级；不能给无起始依据的时段补默认等级 |
| 技能 | 升级事件 600 条，其中 594 个非零技能 ID；已知技能的 `level` 为零起始，与该技能逐次升级和终端技能等级相符，天赋 138 条 | 已知技能显示等级候选为 `level+1`；六条 `abilityId=0` 仍未知。`levelObtained` 有与当时英雄等级不一致的样本，不作为英雄等级 |
| 死亡扣钱 | 203 条归一化死亡均有唯一关联的明确 `goldLost`，包括零值 | 支持逐人完整关联后求和；DEATH 金币 amount 不是替代值；另外两条击杀者未知仍保持未知 |
| 装备 | 30 人最后库存观察的十个已查槽位与明确终局槽位共 300 项相符 | 支持源观察，不能证明中间逐秒/逐分钟覆盖完整；仍带实际观测时间 |
| 中立强化 | STRATZ 终局/库存类型未发现可靠 `neutral1` 对应字段 | OpenDota `item_neutral2` 和带时间的 neutral history 作为固定补充；不能把无时刻终局强化倒填分钟 |
| 永久升级 | `stats.matchPlayerBuffEvent` 共 23 条相关升级；以本地物品身份确认消耗神杖 108、魔晶 609、银月 247，90 个终局标志与 OpenDota 一致 | 区分持有神杖与消耗神杖；无完整事件覆盖时不把“没有事件”当作未激活 |
| 逐英雄伤害 | `heroDamageReport.dealtTargets/receivedTargets` 的 150 对敌方交互金额相互反向一致 | 通常每人五个敌方目标，未报告自身/友方不能补零；未证明覆盖全部非英雄承伤 |
| 伤害总量差异 | 首场 Satanic `heroDamage=46111`，`dealtTargets` 合计 53731；分类总量也不保证与二者一致 | 保留各自来源口径；不强制相等，不猜差异来自幻象或其他机制 |
| 物品使用 | 529 个 itemUsedEvents / stats.itemUsed 对应计数一致 | 证明事件与该统计的样本一致，不证明插眼、成功显影或团队收益 |
| 眼事件 | 后两场 STRATZ 有放置/摧毁字段；首场 wards、wardDestruction、match wardEvents 全为空而 OpenDota 有明确正数与事件 | 首场需要 OpenDota 对应组；同场两源部分计数也有差异，不合并成一份“完整”列表 |
| 助攻 | 直接原始列表、归一化死亡的助攻者及简单时间/目标/击杀者连接均未得到完整可靠映射；仅 12/30 人与终局助攻完全相符 | 不用容忍一两秒的启发式连接补完整分钟 A；终局 A 仍可直接使用 |
| Farming | 首场十人 csEvents 为空、分钟正反补数组全零，终局正反补有正数；其他两场有较完整事件但并非全部终局/边界吻合 | 初版继续 OpenDota `times/lh_t/dn_t`；不能把一个样本或全零数组当作普遍完整来源 |
| XP | 首场 640 个前缀和对应点吻合；其他场次并非所有玩家整条曲线一致 | 不推广统一数组移位/裁剪；默认表使用等级不要求删除现有可靠 XP 补充 |
| 魔方奖励 | 三条 type=117 消息分别与同英雄同秒 Shard buff 对应：首场 1982/2839 秒，第二场 1983 秒 | 支持唯一同场玩家/同秒明确 buff 的奖励接收者候选映射，不支持击杀者或奖励金额推断 |
| 肉山/盾 | 后两场 roshanEvents 血量零记录 2/1 条，而 OpenDota 明确击杀 2/3 条；首场该组为空 | 仍使用整类 OpenDota 明确事件；HP=0 或物品首次出现均不冒充完整精确事件 |

OpenDota `total_gold` 计算定义见
[odota/core 的 compute.ts](https://github.com/odota/core/blob/master/svc/util/compute.ts)，
本次核验源码 Git blob 为 `bd667e3490da4399336a37a59ee024ce991d8021`。
首场 Satanic：`floor(769 × 3862 / 60)=49497`，而 `64:00` 分钟样本为 49310，
两者边界不同，不相互覆盖或视为冲突。

首次血报告/消息的三场时间分别为 `56/79`、`-23/-24`、`88/88`；仍保留来源差异。
买活 cost 全零、宝石精确转移/持有时长、未知 NPC/技能、历史编码等限制仍在。

## 位置可用性与生成成本边界

首场 `playbackData.playerUpdatePositionEvents {time,x,y}` 共 29,097 个点，
覆盖十人，包含负比赛时间。位置流可用于临时生成图片；坐标、轨迹和网格不保存。
没有把首场的可用性推广为其余两场已验证。

2026-10-19 的独立成本探针只输出指标，没有保存位置源响应：

- 三场 OpenDota `/matches/{id}` 各一次：耗时 1.190 / 1.655 / 3.194 秒；gzip
  响应体 70,435 / 61,129 / 68,912 字节；解压体 335,091 / 296,718 / 343,117 字节。
  JSON 解码约 3.8–13.5 ms。不包括提交解析或下载录像，也不是延迟分位数。
- 首场 STRATZ 单独选取位置流：6.496 秒，紧凑 JSON 逻辑大小 848,774 字节，
  不是压缩线上大小。正常详情已请求的重字段不需要再次加入这个独立查询。
- 用该场位置、64×64 网格、平滑、占位底图和 PNG 内存编码，串行生成 5–60 分钟
  十人共 120 图。256×256 三轮为 1.591 / 1.375 / 1.310 秒，合计 1,554,140 B；
  512×512 为 6.002 / 5.240 / 5.270 秒，合计 3,542,501 B。

环境是本机 Windows、已启动的 Python + NumPy/Pillow，不是部署服务器基准。
未包括终局额外十图、正式地图、磁盘/对象存储、任务排队和传输。没有验收坐标标定、
死亡期间位置、共同色标或精确停留权重。样本只支持“渲染量级可控”的判断，不是
图片质量、存储上限或通用性能保证；正式图纹理可能改变体积。
