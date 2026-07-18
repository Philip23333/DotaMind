# DotaMind MVP 设计文档 v2.1（多 Agent 终态架构）

> 本文是 v2 的修订版。v2 提出了 6→3 Agent 精简，但把 Retriever / Analyzer / Formatter 一律称作 "Agent" 是个用词错误——其中两层根本不需要 LLM 决策。v2.1 重新厘定 Agent 与工具的边界，并新增 **Critic Agent** 形成对抗式审核闭环。

修订基于以下三个判断：

1. **"Agent" 的判定标准是有无 LLM 决策**，不是有没有独立类
2. **Retriever / Formatter 是工具函数**，包装成 Agent 只增加 trace 噪声和延迟
3. **真正能体现"多 Agent"价值的是相互制衡的失败模式**——Orchestrator / Analyzer / Critic 三者刚好满足

---

## 1. 用词与边界（替换 v2 第 1.1-1.2 节）

### 1.1 Agent vs Tool 的判定

| 组件类型 | 判据 | 例子 |
|---|---|---|
| **Agent** | 内部需要 LLM 做决策（理解意图 / 推理 / 自检） | Orchestrator、Analyzer、Critic |
| **Tool / 函数** | 纯代码执行，无需 LLM | OpenDota client、patch JSON loader、Jinja 渲染 |

按此标准重审 v2：

| v2 称谓 | v2.1 修正 | 理由 |
|---|---|---|
| Retriever Agent | `retrieve_*()` 工具函数 | HTTP 调用 + schema 拼装，无 LLM |
| Analyzer Agent | Analyzer Agent（保留） | LLM 推理 + claim 抽取 + evidence 绑定 |
| Formatter Agent | `format_report()` 工具函数 | Jinja 模板 / JSON schema 转换，无 LLM |

### 1.2 v2.1 最终架构

```
                        ┌─────────────────────────┐
External Caller ───────►│   Orchestrator Agent    │  [LLM]
(User / A2A / CAP)      │   意图理解 + 工具编排   │
                        └────────────┬────────────┘
                                     │
                ┌────────────────────┼─────────────────────┐
                │                    │                     │
                ▼                    ▼                     ▼
        ┌───────────────┐   ┌────────────────┐   ┌────────────────┐
        │  Retriever    │   │  Analyzer      │   │  Critic        │
        │  Functions    │   │  Agent         │   │  Agent         │
        │  (no LLM)     │   │  [LLM]         │   │  [LLM + rules] │
        └───────┬───────┘   └────────┬───────┘   └────────┬───────┘
                │                    │                    │
                ▼                    ▼                    ▼
        OpenDota / Patch JSON   claims + evidence    pass / reject
                                                     ↓ reject
                                          ┌──────────┴──────────┐
                                          │ 回到 Orchestrator   │
                                          │ 决定补数据 / 重推   │
                                          └─────────────────────┘
```

**3 Agent + 2 Tool**：
- 3 个 Agent 都跑 LLM，都有独立失败模式
- 2 个 Tool 是确定性代码，独立可测

### 1.3 为什么不是单 Agent，也不是 6 Agent

| 方案 | 问题 |
|---|---|
| **单 Agent**（一个大 prompt 处理一切） | 推理和审核耦合在同一个 LLM，self-evaluation bias，幻觉无人把关 |
| **6 Agent**（v1 原方案） | Planner 在固定 4 服务下退化成 if-else；Retriever/Formatter 包 LLM 壳是浪费 |
| **3 Agent + 2 Tool**（v2.1） | 每个 Agent 有独立决策循环和独立失败模式，制衡关系真实存在 |

三个 Agent 的独立失败模式：

- **Orchestrator** 可能错误规划：叫错工具 / 漏调工具 / 死循环
- **Analyzer** 可能产生幻觉：编造无 evidence 的 claim、过度自信
- **Critic** 可能误判：放过假 claim 或过度严苛打回

这是教科书级的"对抗式多 Agent"配置（Reflexion / Self-Critique pattern）。

---

## 2. Orchestrator Agent

### 2.1 职责

- 接收外部请求（自然语言查询 / 结构化请求 / A2A skill 调用）
- 推断意图，决定调用哪些工具与 Agent
- 处理 Critic 打回，决定补数据、重推理、还是降级输出
- 控制重试上限，避免无限循环

### 2.2 工具池（Function Calling Schema）

```python
tools = [
    # 数据获取（无 LLM）
    retrieve_meta(role: str, patch: str) -> EvidenceBundle,
    retrieve_patch(patch: str) -> EvidenceBundle,
    retrieve_team(team_name: str) -> EvidenceBundle,
    retrieve_claim(claim_text: str) -> EvidenceBundle,

    # 推理（Analyzer Agent）
    analyze(bundle: EvidenceBundle, task_type: str) -> ClaimSet,

    # 审核（Critic Agent）
    critic_review(claims: ClaimSet, bundle: EvidenceBundle) -> CriticVerdict,

    # 成稿（无 LLM）
    format_report(claims: ClaimSet, format: str) -> Report,
]
```

### 2.3 控制流伪代码

```python
async def orchestrate(query):
    plan = llm.plan(query, tools)         # function calling
    bundle = await dispatch(plan.retrieve_call)

    for attempt in range(MAX_RETRIES):    # MAX_RETRIES = 2
        claims = await analyzer.run(bundle, plan.task_type)
        verdict = await critic.run(claims, bundle)

        if verdict.passed:
            return format_report(claims, plan.format)

        if verdict.reason == "missing_evidence":
            bundle = await retrieve_more(bundle, verdict.gaps)
        elif verdict.reason == "weak_reasoning":
            continue  # 让 Analyzer 重写

    return insufficient_data_response(verdict.reasons)
```

### 2.4 失败兜底

- 重试 2 次仍不通过 → 输出 `verdict: insufficient_data` + 历次 critic reasons
- LLM 调用失败 → 直接走 v2 已有的 mock fallback
- 死循环检测：plan 生成相同 tool call ≥3 次 → 强制退出

---

## 3. Analyzer Agent

职责与 v2 一致，唯一变化是**单例共享**：4 种任务类型（meta / patch / team / claim）共用同一个 Analyzer 实例，prompt 内带 `task_type` 区分。

### 3.1 输入输出

```python
input  = EvidenceBundle (统一 schema, 见 v2 第 1.4 节)
output = ClaimSet {
    claims: [
        {
            "text": "Beastmaster is a top offlane pick this patch",
            "evidence_ids": ["e1", "e2"],
            "verdict": "supported",          # supported/partial/weak/unsupported
            "confidence": "high",            # high/medium/low/none
        },
        ...
    ],
    task_type: "meta_report",
    raw_reasoning: "..."  # LLM 原始推理过程，供 Critic 审查
}
```

### 3.2 强约束

- **每个 claim 必须挂 ≥1 个 evidence_id**，否则后处理直接丢弃
- **不允许引用 bundle 之外的事实**
- **`missing` 字段非空时**，必须在 claim 中显式声明数据缺口

---

## 4. Critic Agent（v2 全新增加）

### 4.1 设计理由

Analyzer 自检属于 self-evaluation，公认偏弱：同一个 LLM 既写答案又给自己打分，倾向于自我合理化。独立 Critic 来自不同 system prompt、看不到 Analyzer 的中间推理细节，只接 claims + evidence，立场默认怀疑。

这是 Reflexion / Self-Critique 模式的标准实现，也是评委容易识别的"诚实工程"信号。

### 4.2 双层审核

**Layer 1: 规则审核（确定性，无 LLM）**

```yaml
# config/critic_rules.yaml
rules:
  - id: evidence_binding
    desc: 每个 claim 必须挂 ≥1 个 evidence_id
    severity: hard_reject

  - id: evidence_freshness
    desc: 用于 meta 类断言的 evidence freshness_days ≤ 14
    severity: hard_reject

  - id: sample_size_min
    desc: pick_rate / win_rate 类 evidence 的 sample ≥ 500
    severity: soft_warn

  - id: claim_consistency
    desc: 同一 subject 的多个 claim 不能互相矛盾
    severity: hard_reject

  - id: confidence_floor
    desc: 整体 high+medium 比例 < 50% → 整份打回
    severity: hard_reject
```

**Layer 2: LLM 审核**

只有通过 Layer 1 的 claims 才进入 Layer 2。LLM prompt 强制要求：

- 假设 Analyzer 是不可信的，找出至少一个潜在问题
- 检查 evidence 是否真的支持 claim（语义层面）
- 检查推理是否有跳跃（A → C 之间是否缺 B）
- 输出 `verdict ∈ {pass, soft_warn, reject}` + 具体 reason 列表

### 4.3 输出 schema

```json
{
  "passed": false,
  "reasons": [
    {
      "rule": "evidence_freshness",
      "claim_index": 2,
      "detail": "evidence e3 fetched 21 days ago, exceeds 14-day window",
      "severity": "hard_reject"
    }
  ],
  "gaps": ["pro_pickrate_30d"],
  "confidence_overall": "medium",
  "retry_hint": "fetch fresher evidence for claim 2 or drop the claim"
}
```

`gaps` 字段直接喂给 Orchestrator 决定下一步取数。

### 4.4 与 Analyzer 的契约

- Critic 只读 ClaimSet 和原始 EvidenceBundle，**不读 Analyzer 的内部 prompt 或 raw_reasoning**——避免 cross-contamination
- Critic 输出的 reasons 必须可追溯到具体 rule_id 或 evidence_id
- Critic 不重写 claim，只判定 pass / reject + 给 Orchestrator 提示

---

## 5. 完整调用链示例

**Q：Pudge 是不是当前版本的强势中单？**

```
[T+0]   Orchestrator: parse → task_type=meta_check, subject=pudge, role=mid
[T+1]   Orchestrator: tool call → retrieve_meta(role="mid", patch="7.41d")
[T+2]   Retriever:    返回 EvidenceBundle (5 evidences, missing=["pro_pickrate"])
[T+3]   Orchestrator: tool call → analyze(bundle, task_type="meta_check")
[T+4]   Analyzer:     生成 3 claims, 全部挂 evidence
[T+5]   Orchestrator: tool call → critic_review(claims, bundle)
[T+6]   Critic L1:    rule sample_size_min 触发 soft_warn (pickrate sample=380)
[T+7]   Critic L2:    LLM 审核 → reject claim#1
                      reason: "claim 说 S 级 ban 优先级，但 evidence 仅显示 ban_rate=8%"
[T+8]   Orchestrator: 收到 reject，attempt=1/2
                      gaps=["ban_rate_threshold_evidence"]
                      → 决策：让 Analyzer 重写（去掉过强表述），不补数据
[T+9]   Analyzer:     重写 → claim#1 改为 "Pudge 是版本受益者但未达 ban 门槛"
[T+10]  Critic:       pass (3/3 supported, confidence=medium)
[T+11]  Orchestrator: format_report(claims, format="markdown")
[T+12]  → 返回用户
```

整个链路在 trace 中可视化，**这就是 demo 的杀手锏**：评委看到 reject → retry → pass 的过程，"诚实工程"叙事自然成立。

---

## 6. 缓存与成本（修订 v2 第 1.3 节）

新增 Critic Agent 后单次 cache miss 的 LLM 调用次数变化：

| 服务 | LLM 调用次数（无重试） | LLM 调用次数（1 次重试） |
|---|---|---|
| meta_report | 3（Orchestrator + Analyzer + Critic） | 4（多 1 次 Analyzer） |
| patch_impact | 3 | 4 |
| team_report | 3 | 4 |
| verify_claim | 3 | 4 |

成本影响：
- 单次成功（无重试）成本约 **$0.06-0.15**（v2 是 $0.03-0.08）
- Orchestrator 用 GPT-4o-mini 等小模型可压回 $0.04-0.10
- 缓存层不变：Retriever 出口（Redis 1h）+ Analyzer 出口（Redis 6h）

**Critic 输出不缓存**：Critic 是质量门，每次都必须真实跑一遍。

---

## 7. 实施时间线（修订 v2 第 4 节连带建议）

v2 假设按线性 Day 1-15 推进，v2.1 调整为**两阶段重构**：

### Stage 1（v2 → v2.1 骨架，预计 1 天）

1. 把 `agents/` 里的 `data_agent.py` / `report_agent.py` 改名为 `tools/retriever.py` / `tools/formatter.py`，确认它们不调 LLM
2. 保留 `agents/analyzer.py`（重命名 `reasoning_agent.py`），加 LLM 调用框架
3. 新增 `agents/critic.py` + `config/critic_rules.yaml`
4. 新增 `agents/orchestrator.py`，挂上 4 个工具 + Analyzer + Critic
5. 路由层只调 Orchestrator，service 层降级为工具实现细节

### Stage 2（接入真实 LLM + Critic，预计 2-3 天）

1. Analyzer prompt 模板（4 种 task_type）
2. Critic Layer 1 规则编码 + Layer 2 prompt
3. Orchestrator function calling schema 定义
4. 重试 / 死循环 / 降级逻辑
5. 端到端测试 + 回测脚本（v2 第 3.3 节定义的 top-10 重合度）

### Stage 3（优化）

- Critic Layer 2 用 GPT-4，Analyzer 用 GPT-4o，Orchestrator 用 GPT-4o-mini，按价格梯度配置
- A/B：开启 Critic vs 关闭 Critic 的回测分数差，写进 README

---

## 8. v2 → v2.1 差异速查

| 维度 | v2 | v2.1 |
|---|---|---|
| Agent 总数 | 3（Retriever / Analyzer / Formatter） | 3（Orchestrator / Analyzer / Critic） |
| Tool 函数 | 没明确区分 | 2（retrieve_* / format_report） |
| Agent 判定标准 | 模糊 | 必须有 LLM 决策 |
| 审核机制 | Analyzer 内部 self-check | 独立 Critic Agent + 规则 |
| 失败模式独立性 | 弱 | 三个 Agent 各自独立 |
| 重试 / 打回循环 | 无 | Orchestrator 控制，最多 2 次 |
| LLM 调用 / 请求 | 1 | 3-4 |
| 单次成本 | $0.03-0.08 | $0.06-0.15（小模型可压回） |
| 评委可视化 | 静态结果 | reject → retry → pass trace |

---

## 9. 与 v1 / v2 的兼容性

- v1 的页面、商业化、CAP 集成章节继续有效
- v2 的 Evidence Bundle schema、Signal/Verdict 算法、Patch Notes 分阶段策略继续有效
- v2.1 仅替换"Agent 架构"一章，其他不动

后续若需要进一步演化（例如把 Analyzer 拆成 meta_analyzer / team_analyzer / claim_analyzer 多个并行实例），开 v2.2，不污染 v2.1。

---

## 10. 一句话总结

> v2.1 不是为了"更多 Agent 显得更厉害"，而是把 Agent 这个词只留给真正需要 LLM 决策的组件，并通过 Critic Agent 把"诚实工程"从口号变成可观测的运行时行为。

