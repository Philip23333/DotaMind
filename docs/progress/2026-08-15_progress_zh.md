# 2026-08-15 进度快照

## 11:10 — P-15 Controller 会话回忆示例去偏

### 已完成

- 将 Controller prompt 中固定的 `conversation_recall -> context_missing` JSON 示例改为中性 `context_missing` 字段结构；删除可直接照抄的“当前会话中没有足够的历史信息”失败文案。
- 保留 `ContextMissingDecision` 的 `kind`、`intent`、`reason` 输出形态，没有新增关键词路由、固定意图分支、确定性回忆模板或 validator。
- 更新 Controller golden prompt fixture，并增加断言，防止固定 `conversation_recall` 映射和中文失败文案重新进入 system prompt。
- 当前默认 Controller system prompt 为 33,718 字符、512 行，SHA-256 为 `b8b6f18f1bd2a51076af73d6c789e004fe3796523630d8fa049254ac7606d427`。

### 验证

- `tests/test_agentic_prompts.py`：12 passed；相关 Ruff：通过。
- 使用独立持久化 Chat Run 会话完成 6 类 × 3 次、共 18 个真实样本，并在加载当前源码的临时 8002 API 实例上复测；每个会话均以 HTTP 204 删除，临时 API 已停止且端口已关闭。
- 修改前：4/18 `direct_answer`、14/18 `context_missing`；修改后：14/18 `direct_answer`、4/18 `context_missing`。
- 修改后，“我上一个问题是什么”“你刚才回答了什么”“我刚才问过哪两个英雄”均为 3/3 成功；“我刚才问了什么”为 1/3，“我刚才问过哪两个问题”和“把我刚才的两个问题列出来”均为 2/3。

### 已知边界

- 删除误导示例显著改善了元会话回忆，但没有完全关闭问题；泛化的用户问题回忆仍可能错误返回 `context_missing`。
- P-15 当前标记为部分改善，后续应基于同一真实矩阵评估最小的正向判定提示，不引入基于中文关键词的确定性分支。

## 11:36 — P-15 显式 recent-conversation 规则实验与撤回

### 实验

- 在会话规则中临时增加一条显式约束：system 与当前用户消息之间已经出现的消息属于可用会话；所需内容出现时 `context_missing` 无效且无需 `conversation.history_lookup`。
- 使用加载实验源码的临时 8002 API，运行 7 类 × 3 次、共 21 个独立持久化 Chat Run；新增覆盖真实失败原话“我刚才问的什么”。

### 结果

- 两种泛化表达“我刚才问了什么”和“我刚才问的什么”均为 0/3；“我上一个问题是什么”为 2/3；“我刚才问过哪两个问题”为 0/3。
- “把我刚才的两个问题列出来”“你刚才回答了什么”“我刚才问过哪两个英雄”均为 3/3。
- 与上一轮相同的 18 个场景仅 11/18 返回 `direct_answer`，低于删除负向示例后的 14/18；新增真实原话场景另为 0/3。

### 决策与验证

- 该规则没有产生可验证收益，且增加了与现有历史规则重复的 Prompt 文本，因此已从源码、测试断言和 golden fixture 撤回；最终代码仍只保留 11:10 的中性 `context_missing` 结构修改。
- 撤回后 `tests/test_agentic_prompts.py`：12 passed；临时会话均 HTTP 204 删除，临时 API 已停止，8002 端口已关闭。
- 后续不应继续叠加同义的历史可用性提醒；需重新评估 `context_missing` / `conversation.history_lookup` 的职责表达或模型决策边界。

## 12:10 — P-15 会话上下文结果去向与空 lookup 摘要

### 已完成

- 将 Controller 中近期消息、`conversation.history_lookup` 与 `context_missing` 的职责收敛为三条定义：请求内已供应消息是可用会话上下文；lookup 只补充更早消息且不是 Dota evidence；只有综合已供应消息和已完成 lookup 后仍不可用，才返回 `context_missing`。
- `ToolDefinition` 新增 `result_destination`，取值为 `evidence` 或 `controller_context`。Graph 路由、ControllerDecision 校验和 Registry 一致性检查按该字段工作，已删除按 `conversation.history_lookup` 工具名判断的分支。
- `controller_context` 工具成功后，将消息合并到请求级 `retrieved_messages`，并保留最小 `controller_context_summaries`。空 lookup 在下一次 Controller system input 中明确显示为 `{"tool":"conversation.history_lookup","status":"completed","matched_turns":0}`。
- lookup 的 ToolDefinition description 收窄为检索能力说明；`result_destination` 仅作为运行时契约，不为每个工具增加 Prompt 文本。
- 更新 Controller golden fixture、当前架构/Controller/Conversation Memory/Tool/节点清单及 Prompt 重构复盘文档。当前默认 Controller system prompt 为 33,734 字符、514 行，SHA-256 为 `0b24cc98e928e6db22006aacfef36b95b1432f6677f87d1ec8bbfac5c8fbf6e2`。

### 验证

- `tests/test_history_lookup.py tests/test_controller_decisions.py tests/test_agentic_prompts.py -q`：29 passed。
- `tests/test_agentic_contracts.py tests/test_agentic_registry.py -q`：52 passed。
- 相关 Ruff 检查：通过；`git diff --check`：通过（仅现有 CRLF 转换提示）。

### 已知边界

- 本次只完成 Prompt 与上下文结果流的结构修复，没有运行真实 LLM 持久化 Chat Run 矩阵；P-15 的模型层稳定性仍需按同一场景集复测。
- 当前仅 `conversation.history_lookup` 声明 `controller_context` destination；预算配置名仍是 `history_lookup_max_per_run`。

## 12:22 — P-15 结构修复后的真实复测

### 结果

- 使用加载当前工作树的临时 8002 API，通过独立持久化 Chat Run 会话复测此前失败场景。
- “你有什么工具可用”之后：`我刚才问的什么` 0/3、`我刚才问了什么` 0/3、`我上一个问题是什么` 0/3。
- “你有什么工具可用”与“你有什么功能”之后：`我刚才问过哪两个问题` 0/3。
- 合计 0/12 `direct_answer`、12/12 `context_missing`；每次回忆请求都只调用一次 Controller，未执行 history lookup。
- 第一条样本的公开 transcript 明确包含前一轮完整 user/assistant 消息。双问题样本中有一次 failure reason 已准确提到“询问可用工具与功能”两条历史，却仍返回 `context_missing`。

### 空 lookup 链路

- 另两次显式要求 `conversation.history_lookup` 查询不存在的更早内容：工具均成功执行，随后进入第二次 Controller。
- 第二次 Controller 均再次生成 lookup `tool_plan`，触发 `history_lookup_max_per_run=1`，最终公开结果为 `execution_error`，而不是预期的 `context_missing`。
- 因此，空结果摘要解决了运行时状态丢失，但没有让当前模型稳定采用正确终态；重复 lookup 的预算终态映射也是新暴露的次级问题。

### 清理与结论

- 所有测试会话均已删除。临时 8002 API 已停止，端口关闭，临时日志目录已删除；现有 8001 服务未修改。
- P-15 仍是未关闭的 P0。下一步需要重新讨论 decision 合同与模型判断，而不是继续假设本次 Prompt 简化已经解决问题。

## 14:10 — 第一阶段比赛数据工具与 PandaScore 免费能力核验

### 已完成

- 使用临时 PandaScore token 做进程级实测：`/dota2/series`、`/dota2/tournaments`、upcoming/running/past Fixture 列表均返回 200；TI 2026 Series 为 10828，Group Stage 为 Tournament 21545。
- 新增 PandaScore transport、赛事/Fixture/Game 归一化模型和 OpenDota 单场 integration；注册 `pandascore.resolve_competition`、`pandascore.list_matches`、`pandascore.resolve_match_game`、`opendota.match_summary`、`opendota.match_draft` 五个工具。
- 新增 Bearer 认证、分页上限、短缓存、限流头读取、401/403/429/非 JSON/超时错误映射，以及 `DOTAMIND_PANDASCORE_TOKEN` 配置；token 未写入仓库。
- 新增比赛证据提取和 Answer source boundary：PandaScore Fixture 与 OpenDota Valve/Replay 事实分开归因，`detailed_stats` 不解释为 `has_parsed`，空 BP 不产生证据。
- 更新 Controller golden fixture、工具注册目录、Tool 层/架构/节点清单、README、配置文档和 PandaScore API inventory。
- 加入五个工具后的当前 Controller system prompt 为 37,163 字符、571 行，SHA-256 为 `dbba108230c07fc322e2be582c324b9ac2729c0e0e1e92b2df0c3e8e986b4675`。

### 已验证边界

- 已知样本 `pandascore_match_id=1631694`、第一局 `pandascore_game_id=738652` 可由免费 Fixture 定位；双方战队顺序不影响匹配，未指定多局序号时返回 ambiguous。
- Game 行的 `match_id` 是 PandaScore 父 Match ID，不是 Valve `match_id`；`GET /dota2/games/738652` 返回 403。`resolve_match_game` 因此返回 `pending_valve_match_id`，不伪造映射、不抓网页、不绕过套餐。
- OpenDota `8943244303` 实测返回 10 名选手、parse version 22 和 24 条 BP；归一化输出包含赛果、面板、parse coverage 和 draft。

### 验证

- `tests/test_pandascore_transport.py tests/test_pandascore_domains.py tests/test_agentic_pandascore_tools.py tests/test_agentic_opendota_match_tools.py`：17 passed。
- `tests/test_agentic_registry.py tests/test_agentic_contracts.py tests/test_agentic_evidence.py tests/test_agentic_prompts.py`：75 passed。
- `uv run ruff check app tests`：通过。

### 已知限制

- 当前免费 PandaScore Fixture 无法把 PandaScore Game 映射到 Valve match ID；需要用户提供 Valve ID 或可用的受权限 API 数据，第一阶段不会把该缺口隐藏成成功。
- 本阶段没有新增 endpoint、结构化比赛 output contract、时间线/事件/日志、STRATZ fallback、数据库同步或前端。

## 18:21 — 第二阶段跨源 Valve 单局映射

### 已完成

- 新增 `dota.resolve_valve_match`，建立
  `pandascore.resolve_competition → pandascore.resolve_match_game →
  dota.resolve_valve_match → opendota.match_summary/match_draft` 的声明引用链。
- 新增 OpenDota `/leagues` 与 `/leagues/{league_id}/matches` integration、
  `CrossSourceMatchResolutionPolicy`（默认开始时间容差 1800 秒、时长容差 5 秒）
  和 `inferred_cross_source` 归一化映射模型。
- 解析器按赛事名称+年份唯一匹配联赛、复用现有战队解析器，并使用无序战队 ID、
  开始时间、时长、系列局序和胜者一致性硬过滤；零/多候选、联赛/战队歧义和信号缺失
  保持显式状态，不使用加权或 closest fallback。
- `resolve_match_game` 的 mandatory evidence 收敛为
  `match_identity` + `pandascore_game_identity`；新增 `data.resolution_input`，
  不把推断 Valve ID 写入 PandaScore 原生上下文。OpenDota summary/draft 接受
  resolver 引用，并提供 `data.match.match_id` 兼容别名。
- 新增跨源 mapping/league/tool 测试和技术文档，更新 Controller catalog、Answer
  归因规则、Tool/节点清单、README 与配置说明。

### 实测边界

- 当前 `.env` token 进程实测：TI 2026 Series 10828、Tournament 21545；
  Match 1631694 / Game 738652 的 PandaScore 原生 `valve_match_id` 为 `null`。
- OpenDota 实测存在 league 19719、series 1130066、Valve match 8943244303，
  但 `/teams` 对 “Nigma Galaxy” 返回两个同分候选（10136357、7554697）；
  按严格 `ambiguous_team` 规则，真实链路当前不会静默选择 10136357。
- 因此已知样本的“唯一 resolved”live smoke 未通过，原因是上游战队目录歧义；
  测试使用脱敏且唯一的战队 fixture 验证 resolved 路径。没有写入手工 Valve 映射表，
  也没有绕过套餐或抓网页。

### 验证

- `test_cross_source_match_resolution.py`、`test_agentic_match_resolution_tools.py`、
  OpenDota/PandaScore/registry/contract/evidence/prompt 定向集合：92 passed。
- `uv run --project apps/api pytest apps/api/tests -q`：595 passed，21 skipped，1 warning。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests`：通过。
- 已扫描 Git 跟踪文件，PandaScore token 未出现在源码、fixture、文档或测试输出中。

### 明确不做

- 本阶段没有新增 API endpoint、时间线/事件/日志、STRATZ fallback、Replay 自动解析、
  数据库 mapping 表、网页抓取、付费 PandaScore 详情调用或 intent 路由。

## 19:12 — P2.1 按 League 参赛记录消解同名战队

### 已完成

- 不修改公共 `resolve_team()` 语义；仅在 `ValveMatchResolver` 的跨源上下文中，
  对全局同名候选调用既有 `OpenDotaTeams.get_matches(team_id)`。
- 只使用 Team Matches 的精确 `leagueid == target OpenDota league ID` 判断参赛，
  `league_name` 仅保留在诊断数据中，不参与唯一判断。
- 恰好一个候选参加目标 League 时返回 `league_participation`；零个返回
  `no_candidate_in_target_league`，多个返回 `multiple_candidates_in_target_league`，
  均继续保持 `ambiguous_team`，不按评分、活跃度、数量或候选顺序猜测。
- 统一战队审计字段：直接解析记录 `global_team_identity`；League 消歧记录
  `target_league_id`、`league_match_count`、最多五个 `sample_match_ids`。成功 mapping
  增加 `team_league_participation`，未新增工具、output path 或 evidence kind。

### 真实样本 Smoke Test

- 使用当前 PandaScore 标准化 Series 10828 / Match 1631694 / Game 738652 与实时
  OpenDota API：Nigma 候选 10136357 有 8 场 `leagueid=19719` 记录，7554697 无目标
  League 记录；OG 唯一解析为 2586976。
- 真实结果：`resolved`，Valve `8943244303`，OpenDota league `19719`、series
  `1130066`；开始时间差 115 秒、时长差 0 秒、candidate_count 1。

### 验证

- `test_cross_source_match_resolution.py`：14 passed，覆盖真实重复目录拓扑、零/多候选、
  相似 league_name 错 leagueid、唯一战队不请求 Team Matches、上游异常透传和最终比赛唯一性。
- 清理一个与已提交 P-13 动态能力目录不一致的旧 Controller 测试断言；未修改
  Controller Prompt 或其 golden fixture。P2.1 改动后的全量：602 passed、21 skipped、1 warning；Ruff 通过。

### 边界

- Team Matches 只用于消解战队身份，不能直接作为最终 Valve match；最终 ID 仍由
  league matches 的无序战队、时间、时长、局序和胜者硬过滤唯一确定。
- 未引入网页抓取、评分选择、手工 Valve 映射、fallback 或新工具。

## 19:05 — P-13 Controller 能力事实源收敛

### 已完成

- 删除 Controller system prompt 中与动态 ToolRegistry 目录重复的
  `Supported in this development version` 固定能力清单。该清单未跟随新增
  PandaScore/OpenDota 赛事与比赛工具更新。
- `Direct-answer rules` 现要求能力类问题从当前渲染的工具目录得出能力，
  按用户任务领域概括；用户未明确询问工具名时不列内部名称，不宣称未注册能力。
- 增加一个仅限表达风格的中文能力概括案例；案例不是固定能力清单或
  intent 路由，具体内容仍以 ToolRegistry 为准。
- 默认 Controller system prompt 现为 38,169 字符、578 行，SHA-256 为
  `6aeddc428335bc04b516eb8c91ea28b4173a44a437e74652eb09ae0c98518f50`。
- P-05 按当前决策记录为“未稳定复现，暂不处理”；P-15 保持未关闭但暂停继续修改。

### 验证

- `tests/test_agentic_prompts.py -q`：14 passed。
- `ruff check app/agentic/prompts/controller_rules.py tests/test_agentic_prompts.py`：通过。

### 未改变的边界

- 未修改 ToolDefinition、工具调用顺序、ControllerDecision schema、Answer Prompt、
  EvidenceGraph、API 或 intent 路由。

## 20:15 — P-16 Controller 新 Dota 事实来源边界

### 问题与修复

- LunaMax 实测确认：简单英雄介绍、完整技能和具名技能可返回
  `direct_answer` 且 `tool_results=[]`。工具目录已包含 Catalog 能力，故障发生在
  Controller 是否选择 `tool_plan`，而非 Catalog 工具链或 Answer。
- Controller 现明确：模型自身知识不是 `direct_answer` 的 Dota 事实证据；
  所需事实不在当前消息/可复用历史中且注册工具可提供时，必须选择
  `tool_plan`。
- “不要仅因为话题是事实就重查”收窄为仅适用于已明确存在且可复用的
  当前/历史事实。`Direct-answer rules` 同步声明分支合法性。
- 增加基于真实失败的 fresh-fact 反例，仅强调新英雄/技能事实需要
  `tool_plan`，不指定 Catalog 工具名、参数、调用顺序或 intent 路由。
- 默认 Controller system prompt 现为 39,037 字符、592 行，SHA-256 为
  `fc2b55d016225b9da2d53c47bef23822c3e7225169afb3b3acff6c18f75e22a3`。

### 验证

- `tests/test_agentic_prompts.py -q`：14 passed。
- `ruff check app/agentic/prompts/controller_rules.py tests/test_agentic_prompts.py`：通过。
- 使用加载当前工作树的临时 8002 API 隔离复测：“兽王是什么英雄”3/3
  选择 `tool_plan`，工具为 `resolve_hero` + `dota.hero_attributes` +
  `dota.hero_abilities`；“齐天大圣有什么技能”和具名“棒击大地”各复测1次，
  均使用 `resolve_hero` + `dota.hero_abilities`。
- 临时 8002 已停止。现有 8001 进程未稳定热加载当前 Prompt，其旧 Prompt
  结果未计入最终验收。

### 未改变的边界

- 未修改 ToolDefinition、ArgContract、Validator、ControllerDecision schema、
  Catalog handler、EvidenceGraph、Answer Prompt、API 或数据。
