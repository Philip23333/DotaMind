# OpenDota 单位标识与双语名称采样

本文保存 game.detail 数据契约依赖的实际来源证据。目标结构与转换规则由 [game_detail_data.md](../agent/game_detail_data.md) 唯一拥有；本文不是运行时映射文件，也不代表相关转换已经实现。

## 采样口径

- 采样日期：2026-10-15。使用既有保存的 OpenDota 响应，没有重新请求比赛详情，也未使用 DotaLens 的推导分析作为 OpenDota 字段证据。
- 比赛：9040460429、9040578015、9042720328。前两场原始响应保存在本地实验结果中；项目内可复核 [9040460429 fixture](../../apps/api/tests/vnext/fixtures/game_detail/opendota_9040460429.json) 和 [9042720328 fixture](../../apps/api/tests/vnext/fixtures/game_resolution/opendota_game_9042720328.json)。
- 递归收集原始响应字典键及字符串值中的 npc_* / dota_* 单位标识，记录字段位置，并按标识去重。统计数量不是击杀次数或去重后的游戏事件数。
- “当前 DTO 使用”表示此前离线投影保留了该来源标识，不代表已接入正式工具或已实现双语转换。

## 固定来源与版本

非英雄单位定义及名称来自 Valve 游戏文件的公开镜像，按完整单位内部名精确对照，不按英文词义生成译名。英语/单位定义和中文来自不同镜像提交；这些是静态名称证据，不证明比赛当时的数值、机制或补丁版本。

- [dota_english.txt](https://github.com/SteamDatabase/GameTracking-Dota2/blob/fc24352806127812d3746b47d7c53ed5f802ffaa/game/dota/pak01_dir/resource/localization/dota_english.txt)；SHA-256：`3c7138f17b4ed569960218c70af01768a3139ec05269d98136d7ad4da3163d33`。
- [npc_units.txt](https://github.com/SteamDatabase/GameTracking-Dota2/blob/fc24352806127812d3746b47d7c53ed5f802ffaa/game/dota/pak01_dir/scripts/npc/npc_units.txt)；SHA-256：`f9a4b9d946913324f4263af2d41a3be5436645fb17e411ac006350caa83e9d37`。
- [abilities_english.txt](https://github.com/SteamDatabase/GameTracking-Dota2/blob/fc24352806127812d3746b47d7c53ed5f802ffaa/game/dota/pak01_dir/resource/localization/abilities_english.txt)；SHA-256：`1d35f2b3d7c7d564e28f7e99364919f8596b9c0bec549104d2510951b3f03406`。
- [abilities_schinese.txt](https://github.com/dotabuff/d2vpkr/blob/68348f45cb38e5c29388e13bd2ca4f825393357d/dota/resource/localization/abilities_schinese.txt)；SHA-256：`61ea25747179d44146db70f8cb9aac1a58c304d624025e372f77f212b6698708`。

实体名称覆盖检查使用本地 committed Catalog：patch `7.41f`，generated_at `2026-09-28T16:35:43.688620+00:00`，schema_version `1`。没有核查生产活跃快照。

## 覆盖结果

- 原始响应共 139 种单位标识：英雄 21 种，非英雄 118 种。117 种非英雄标识存在精确单位定义和双语名称，另一个是 dota_unknown。
- 此前 DTO 涉及 41 种非英雄标识，40 种有双语名称；剩余为 dota_unknown。单位映射不要求把原始响应中全部野怪/建筑伤害数据加入详情。

| 其他实体输入口径 | 不同输入值数 | 有双语名称 | 未精确匹配 |
|---|---:|---:|---|
| 英雄 ID，包含选禁 | 40 | 40 | 无 |
| 最终装备 ID，排除空槽 0 | 96 | 96 | 无 |
| 购买记录 key | 148 | 148 | 无 |
| 中立装备历史 key | 31 | 30 | guardian_shell |
| 中立强化 key | 12 | 12 | 无 |
| 技能升级 ID | 179 | 179 | 无 |

英雄 ID 的 40 个值包含选禁；21 个 hero unit key 统计实际出现的单位内部名，两者口径不同。各类物品输入可能重合，不能相加作为物品总数。

## 非英雄击杀者的真实死亡日志

| 比赛 | 秒数 | 受害英雄 | 受害 player_slot | 来源击杀者 |
|---|---:|---|---:|---|
| 9040578015 | 1063 | 巫医 | 3 | `npc_dota_creep_badguys_flagbearer` |
| 9042720328 | 1470 | 灰烬之灵 | 129 | `npc_dota_goodguys_tower2_bot` |
| 9042720328 | 563 | 龙骑士 | 130 | `npc_dota_goodguys_tower1_bot` |
| 9042720328 | 367 | 森海飞霞 | 131 | `npc_dota_creep_goodguys_melee` |

这些记录直接来自受害玩家的 deaths_log；没有按附近事件、伤害量或名字相似度推算击杀者。

## 已知缺口与解释边界

- dota_unknown：在 9040578015 和 9042720328 的建筑事件 unit 中各出现一次。建筑 key 和时间仍已知，仅击毁者单位未知。
- guardian_shell：在 9040578015 的 player_slot 129/132、9042720328 的 player_slot 0/128 中立装备历史各出现一次，共 4 次；精确内部 key 不存在于所检查的 Catalog。分别为 995、1033、991、960 秒。保留未知与来源证据，不能猜成卫士胫甲等名称相似物品。
- npc_dota_miniboss 的中英客户端名称分别是痛苦魔方、Tormentor。名称证据已补齐；game.detail 接受的目标事件类型规则见契约，不能继续把这项当作首版待决定字段。
- generic courier、ward、召唤物等单位定义中的默认 TeamName 不表示本场实际归属；不要用它填写 side 或控制玩家。
- 四级塔的共享单位 key 不区分左右实体。英雄和装备 ID 也不能用作其他单位的虚构实例 ID。
- 单位分类仅适用于下表的精确已核实记录；新名字不能单凭相似前缀自动继承映射。

## 非英雄映射核对表

kind 使用契约固定枚举。名称保留客户端原文，不拼造带阵营、道路、等级的名称；可确认的 side、lane、tier 另用结构化字段。缺少任一映射只影响相应字段。下表中空白名称表示来源未知。

| 来源标识 | kind | 中文名称 | 英文名称 | 当前 DTO 使用 |
|---|---|---|---|---|
| `dota_fountain` | `fountain` | 泉水 | Fountain | 否 |
| `dota_unknown` | `unknown` | — | — | 是 |
| `npc_dota_badguys_fillers` | `building` | 建筑 | Building | 否 |
| `npc_dota_badguys_fort` | `ancient` | 夜魇遗迹 | Dire's Ancient | 是 |
| `npc_dota_badguys_melee_rax_bot` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_badguys_melee_rax_mid` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_badguys_melee_rax_top` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_badguys_range_rax_bot` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_badguys_range_rax_mid` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_badguys_range_rax_top` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_badguys_siege` | `siege_creep` | 攻城单位 | Siege Creep | 是 |
| `npc_dota_badguys_siege_upgraded` | `siege_creep` | 高级攻城单位 | Super Siege Creep | 否 |
| `npc_dota_badguys_tower1_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower1_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower1_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower2_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower2_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower2_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower3_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower3_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower3_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_badguys_tower4` | `tower` | 防御塔 | Tower | 否 |
| `npc_dota_brewmaster_earth_1` | `summoned_unit` | 大地战士 | Earth Brewling | 否 |
| `npc_dota_brewmaster_earth_3` | `summoned_unit` | 大地战士 | Earth Brewling | 否 |
| `npc_dota_brewmaster_earth_4` | `summoned_unit` | 大地战士 | Earth Brewling | 否 |
| `npc_dota_brewmaster_fire_1` | `summoned_unit` | 烈火战士 | Fire Brewling | 否 |
| `npc_dota_brewmaster_fire_3` | `summoned_unit` | 烈火战士 | Fire Brewling | 否 |
| `npc_dota_brewmaster_fire_4` | `summoned_unit` | 烈火战士 | Fire Brewling | 否 |
| `npc_dota_brewmaster_storm_1` | `summoned_unit` | 狂风战士 | Storm Brewling | 否 |
| `npc_dota_brewmaster_storm_3` | `summoned_unit` | 狂风战士 | Storm Brewling | 否 |
| `npc_dota_brewmaster_storm_4` | `summoned_unit` | 狂风战士 | Storm Brewling | 否 |
| `npc_dota_courier` | `courier` | 信使 | Courier | 否 |
| `npc_dota_creep_badguys_flagbearer` | `lane_creep` | 士兵旗手 | Flagbearer Creep | 是 |
| `npc_dota_creep_badguys_flagbearer_upgraded` | `lane_creep` | 高级士兵旗手 | Super Flagbearer Creep | 否 |
| `npc_dota_creep_badguys_melee` | `lane_creep` | 近战兵 | Melee Creep | 是 |
| `npc_dota_creep_badguys_melee_upgraded` | `lane_creep` | 高级近战兵 | Super Melee Creep | 否 |
| `npc_dota_creep_badguys_ranged` | `lane_creep` | 远程兵 | Ranged Creep | 是 |
| `npc_dota_creep_badguys_ranged_upgraded` | `lane_creep` | 高级远程兵 | Super Ranged Creep | 否 |
| `npc_dota_creep_goodguys_flagbearer` | `lane_creep` | 士兵旗手 | Flagbearer Creep | 是 |
| `npc_dota_creep_goodguys_flagbearer_upgraded` | `lane_creep` | 高级士兵旗手 | Super Flagbearer Creep | 否 |
| `npc_dota_creep_goodguys_melee` | `lane_creep` | 近战兵 | Melee Creep | 是 |
| `npc_dota_creep_goodguys_melee_upgraded` | `lane_creep` | 高级近战兵 | Super Melee Creep | 否 |
| `npc_dota_creep_goodguys_ranged` | `lane_creep` | 远程兵 | Ranged Creep | 是 |
| `npc_dota_creep_goodguys_ranged_upgraded` | `lane_creep` | 高级远程兵 | Super Ranged Creep | 否 |
| `npc_dota_dark_troll_warlord_skeleton_warrior` | `summoned_unit` | 骷髅战士 | Skeleton Warrior | 否 |
| `npc_dota_enraged_wildkin_tornado` | `spell_unit` | 飓风 | Tornado | 否 |
| `npc_dota_furion_treant` | `summoned_unit` | 树人 | Treant | 否 |
| `npc_dota_goodguys_fillers` | `building` | 建筑 | Building | 否 |
| `npc_dota_goodguys_fort` | `ancient` | 天辉遗迹 | Radiant's Ancient | 是 |
| `npc_dota_goodguys_melee_rax_bot` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_goodguys_melee_rax_mid` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_goodguys_melee_rax_top` | `barracks` | 近战兵营 | Melee Barracks | 是 |
| `npc_dota_goodguys_range_rax_bot` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_goodguys_range_rax_mid` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_goodguys_range_rax_top` | `barracks` | 远程兵营 | Ranged Barracks | 是 |
| `npc_dota_goodguys_siege` | `siege_creep` | 攻城单位 | Siege Creep | 否 |
| `npc_dota_goodguys_siege_upgraded` | `siege_creep` | 高级攻城单位 | Super Siege Creep | 否 |
| `npc_dota_goodguys_tower1_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower1_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower1_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower2_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower2_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower2_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower3_bot` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower3_mid` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower3_top` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_goodguys_tower4` | `tower` | 防御塔 | Tower | 是 |
| `npc_dota_miniboss` | `tormentor` | 痛苦魔方 | Tormentor | 否 |
| `npc_dota_neutral_alpha_wolf` | `neutral_creep` | 头狼 | Alpha Wolf | 否 |
| `npc_dota_neutral_ancient_frog` | `neutral_creep` | 远古长须蛙 | Ancient Croaker | 否 |
| `npc_dota_neutral_ancient_frog_mage` | `neutral_creep` | 远古沼蛙法师 | Ancient Marshmage | 否 |
| `npc_dota_neutral_big_thunder_lizard` | `neutral_creep` | 远古雷肤兽 | Ancient Thunderhide | 否 |
| `npc_dota_neutral_black_dragon` | `neutral_creep` | 远古黑龙 | Ancient Black Dragon | 否 |
| `npc_dota_neutral_black_drake` | `neutral_creep` | 远古黑蜉蝣 | Ancient Black Drake | 否 |
| `npc_dota_neutral_centaur_khan` | `neutral_creep` | 半人马征服者 | Centaur Conqueror | 否 |
| `npc_dota_neutral_centaur_outrunner` | `neutral_creep` | 半人马猎手 | Centaur Courser | 否 |
| `npc_dota_neutral_dark_troll` | `neutral_creep` | 丘陵巨魔 | Hill Troll | 否 |
| `npc_dota_neutral_dark_troll_warlord` | `neutral_creep` | 黑暗巨魔召唤法师 | Dark Troll Summoner | 否 |
| `npc_dota_neutral_enraged_wildkin` | `neutral_creep` | 枭兽撕裂者 | Wildwing Ripper | 否 |
| `npc_dota_neutral_fel_beast` | `neutral_creep` | 魔能之魂 | Fell Spirit | 否 |
| `npc_dota_neutral_forest_troll_berserker` | `neutral_creep` | 丘陵巨魔狂战士 | Hill Troll Berserker | 否 |
| `npc_dota_neutral_forest_troll_high_priest` | `neutral_creep` | 丘陵巨魔牧师 | Hill Troll Priest | 否 |
| `npc_dota_neutral_froglet` | `neutral_creep` | 沼蛙 | Boglet | 否 |
| `npc_dota_neutral_froglet_mage` | `neutral_creep` | 沼蛙法师学徒 | Marshmage Apprentice | 否 |
| `npc_dota_neutral_frostbitten_golem` | `neutral_creep` | 远古霜害傀儡 | Ancient Frostbitten Golem | 否 |
| `npc_dota_neutral_ghost` | `neutral_creep` | 鬼魂 | Ghost | 否 |
| `npc_dota_neutral_giant_wolf` | `neutral_creep` | 巨狼 | Giant Wolf | 否 |
| `npc_dota_neutral_gnoll_assassin` | `neutral_creep` | 豺狼人刺客 | Vhoul Assassin | 否 |
| `npc_dota_neutral_granite_golem` | `neutral_creep` | 远古花岗石傀儡 | Ancient Granite Golem | 否 |
| `npc_dota_neutral_grown_frog` | `neutral_creep` | 长须蛙 | Croaker | 否 |
| `npc_dota_neutral_grown_frog_mage` | `neutral_creep` | 沼蛙法师 | Marshmage | 否 |
| `npc_dota_neutral_harpy_scout` | `neutral_creep` | 鹰身女妖侦察者 | Harpy Scout | 否 |
| `npc_dota_neutral_harpy_storm` | `neutral_creep` | 鹰身女妖风暴巫师 | Harpy Stormcrafter | 否 |
| `npc_dota_neutral_ice_shaman` | `neutral_creep` | 远古寒冰萨满 | Ancient Ice Shaman | 否 |
| `npc_dota_neutral_kobold` | `neutral_creep` | 狗头人 | Kobold | 否 |
| `npc_dota_neutral_kobold_taskmaster` | `neutral_creep` | 狗头人长官 | Kobold Foreman | 否 |
| `npc_dota_neutral_kobold_tunneler` | `neutral_creep` | 狗头人士兵 | Kobold Soldier | 否 |
| `npc_dota_neutral_mud_golem` | `neutral_creep` | 泥土傀儡 | Mud Golem | 否 |
| `npc_dota_neutral_mud_golem_split` | `neutral_creep` | 碎土傀儡 | Shard Golem | 否 |
| `npc_dota_neutral_ogre_magi` | `neutral_creep` | 食人魔冰霜法师 | Ogre Frostmage | 否 |
| `npc_dota_neutral_ogre_mauler` | `neutral_creep` | 食人魔拳手 | Ogre Bruiser | 否 |
| `npc_dota_neutral_polar_furbolg_champion` | `neutral_creep` | 地狱熊怪 | Hellbear | 否 |
| `npc_dota_neutral_polar_furbolg_ursa_warrior` | `neutral_creep` | 地狱熊怪粉碎者 | Hellbear Smasher | 否 |
| `npc_dota_neutral_prowler_acolyte` | `neutral_creep` | 远古侍僧潜行者 | Ancient Prowler Acolyte | 否 |
| `npc_dota_neutral_prowler_shaman` | `neutral_creep` | 远古萨满潜行者 | Ancient Prowler Shaman | 否 |
| `npc_dota_neutral_rock_golem` | `neutral_creep` | 远古岩石傀儡 | Ancient Rock Golem | 否 |
| `npc_dota_neutral_satyr_hellcaller` | `neutral_creep` | 萨特苦难使者 | Satyr Tormenter | 否 |
| `npc_dota_neutral_satyr_soulstealer` | `neutral_creep` | 萨特窃神者 | Satyr Mindstealer | 否 |
| `npc_dota_neutral_satyr_trickster` | `neutral_creep` | 萨特放逐者 | Satyr Banisher | 否 |
| `npc_dota_neutral_small_thunder_lizard` | `neutral_creep` | 远古岚肤兽 | Ancient Rumblehide | 否 |
| `npc_dota_neutral_tadpole` | `neutral_creep` | 蝌蚪 | Pollywog | 否 |
| `npc_dota_neutral_warpine_raider` | `neutral_creep` | 斗松掠夺者 | Warpine Raider | 否 |
| `npc_dota_neutral_wildkin` | `neutral_creep` | 枭兽 | Wildwing | 否 |
| `npc_dota_observer_wards` | `ward` | 侦察守卫 | Observer Ward | 否 |
| `npc_dota_roshan` | `roshan` | 肉山 | Roshan | 否 |
| `npc_dota_sentry_wards` | `ward` | 岗哨守卫 | Sentry Ward | 否 |
| `npc_dota_unit_roshans_banner` | `roshans_banner` | 肉山的战旗 | Roshan's Banner | 否 |
| `npc_dota_witch_doctor_death_ward` | `summoned_unit` | 死亡守卫 | Death Ward | 否 |

`dota_unknown` 在表中归为 unknown 仅供采样统计；unknown 不是已接受的 Unit.kind 枚举。目标输出该单位字段为 null，并将原始标识放入 coverage.missing。

## 验证范围

采样已核对三份输入文件、四份静态来源文件的内容哈希、139 个标识去重及 CSV/JSON 统计一致性。没有执行新行为的代码测试、真实模型调用或部署验证。样本不保证其他比赛或未来版本的完整覆盖。
