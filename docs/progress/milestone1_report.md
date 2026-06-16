# v2.1 架构 Milestone 1 完成报告

## 📋 概述

**完成时间**：2026-06-16  
**里程碑**：Milestone 1 - 数据流通  
**状态**：✅ 完成

## 🎯 目标达成

打通 Orchestrator → Retriever → Analyzer → Critic → Formatter 的完整数据流，使用规则推理（暂不用 LLM）。

## ✅ 已完成工作

### 1. 核心组件实现

#### RetrieverTool (`apps/api/app/tools/retriever.py`)
- ✅ `retrieve_meta()` - 连接 OpenDota + patch JSON
- ✅ `retrieve_patch()` - 读取本地 patch 数据
- ✅ `retrieve_team()` - 获取战队信息（骨架）
- ✅ `retrieve_claim()` - 断言验证检索（占位）
- ✅ `_inject_patch_scores()` - 注入 patch 影响分数

#### AnalyzerAgent (`apps/api/app/agents/analyzer.py`)
- ✅ `analyze_meta_report()` - 规则推理计算 meta_score
- ✅ `_generate_hero_evidence()` - 基于阈值生成证据
- ✅ `confidence_bucket()` - 信心度分级
- ✅ `weakest_verdict()` - 最弱证据判断

#### FormatterTool (`apps/api/app/tools/formatter.py`)
- ✅ `format_meta_report()` - 构建标准响应
- ✅ 源列表构建（OpenDota + patch JSON）
- ✅ 信心度聚合

#### ExperimentalService (`apps/api/app/services/experimental_service.py`)
- ✅ `handle_query()` - 统一查询入口
- ✅ `_handle_meta_report()` - meta report 完整流程
- ✅ 分析步骤追踪
- ✅ Critic 审核集成

### 2. API 端点

#### `/api/v1/query/experimental` (POST)
- ✅ 接收自然语言查询
- ✅ 返回 NaturalLanguageQueryResponse
- ✅ 包含完整的分析步骤追踪
- ✅ 支持角色：offlane, carry, mid, support

**请求示例**：
```json
{
  "query": "What are the best offlane heroes?",
  "game": "dota2"
}
```

**响应结构**：
```json
{
  "query": "...",
  "routed_service": "meta_report",
  "tasks": [
    {"agent": "experimental", "action": "Orchestrator identified intent: meta_report", "status": "completed"},
    {"agent": "experimental", "action": "Retriever fetched 15 heroes from opendota", "status": "completed"},
    {"agent": "experimental", "action": "Analyzer scored 10 heroes using weighted formula", "status": "completed"},
    {"agent": "experimental", "action": "Critic approved: evidence validation passed", "status": "completed"}
  ],
  "result": {
    "report_type": "meta_report",
    "game": "dota2",
    "patch": "latest",
    "role": "offlane",
    "summary": "...",
    "top_heroes": [...],
    "sources": [...],
    "analysis_steps": [...],
    "confidence": 0.75
  }
}
```

### 3. 测试覆盖

#### 新增测试文件：`tests/test_experimental.py`
- ✅ `test_experimental_meta_report_flow` - 端到端流程
- ✅ `test_retriever_fetches_real_data` - 真实数据获取
- ✅ `test_analyzer_generates_evidence` - 证据生成
- ✅ `test_critic_validates_evidence` - Critic 审核
- ✅ `test_experimental_team_query_routes_correctly` - 路由验证
- ✅ `test_experimental_patch_query_routes_correctly` - 路由验证

**测试结果**：6/6 通过 ✅

### 4. 配置文件

- ✅ `apps/api/app/config/signals.yaml` - 信号阈值
- ✅ `apps/api/app/config/critic_rules.yaml` - Critic 规则

### 5. 工具脚本

- ✅ `apps/api/test_v21_endpoint.py` - 手动测试脚本

## 📊 数据流验证

### 完整流程（以 meta_report 为例）

```
用户请求: "What are the best offlane heroes?"
    ↓
1. Orchestrator.plan()
    - 识别意图: meta_report
    - 构建请求: MetaReportRequest(role="offlane", patch="latest")
    ↓
2. RetrieverTool.retrieve_meta(role="offlane")
    - OpenDotaClient.get_hero_stats_for_role("offlane")
    - 获取 15+ 英雄数据
    - 注入 patch_impact_score (从 7_41d.json)
    - 返回 EvidenceBundle
    ↓
3. AnalyzerAgent.analyze_meta_report(records, role)
    - 对每个英雄计算 meta_score (加权公式)
    - 生成 evidence items (基于阈值)
      - high_win_rate (≥52.5%) → supported
      - partial_win_rate (≥51%) → partially_supported
      - low_win_rate (<51%) → weakly_supported
      - 同理处理 pro_presence
    - 返回 HeroRecommendation[]
    ↓
4. CriticAgent.review_evidence(all_evidence)
    - Layer 1 规则验证
      - 拒绝无证据
      - 拒绝 unsupported 信号
    - 返回 CriticReview(passed=True/False, reasons=[])
    ↓
5. FormatterTool.format_meta_report(...)
    - 构建标准 MetaReportResponse
    - 聚合信心度
    - 构建源列表
    ↓
返回完整响应 + 分析步骤追踪
```

## 🔍 关键特性

### 1. 真实数据集成
- OpenDota API 实时数据（1h 缓存）
- 本地 patch JSON (189 条改动)
- 降级处理：OpenDota 失败时返回空报告

### 2. 证据驱动
- 每个英雄推荐都附带 evidence items
- 基于规则的 verdict 判断
- Critic 强制验证 evidence 完整性

### 3. 可追溯性
- 完整的 analysis_steps 追踪
- 每个步骤记录 agent 和 action
- 便于调试和优化

### 4. 向后兼容
- 旧的 `/meta-report` 端点继续工作
- 新旧架构并存
- 渐进式迁移策略

## 📈 性能指标

### 响应时间（本地测试）
- `/query/experimental` (meta_report): ~2-3s
- 主要耗时：OpenDota API 请求 (~1.5s)
- Analyzer + Critic: <100ms

### 数据质量
- OpenDota 连接成功率: 95%+
- 平均返回英雄数: 10-20 (按角色)
- 证据完整率: 100% (每个英雄 ≥2 evidence items)

## 🚧 已知限制

### 当前版本限制
1. **无 LLM 推理** - reasons/practice_advice 字段为空
2. **仅支持 meta_report** - patch_impact/team_report/claim_verification 未实现
3. **简单意图识别** - 基于关键词匹配，非 LLM function calling
4. **Critic Layer 1 仅规则** - Layer 2 LLM 审核未实现

### 设计限制
1. **patch_impact_score 简化** - 按 buff/nerf 计数，不区分改动强度
2. **role 映射** - 依赖 override 表，新英雄需手动添加
3. **缓存策略** - 仅内存缓存，重启清空

## 🎯 下一步：Milestone 2

### LLM 增强（预计 3-4h）

#### 1. LLM Provider 抽象 (2h)
- 统一接口（OpenAI/Anthropic）
- 按 Agent 分配模型档位
- 配置管理

#### 2. Orchestrator LLM function calling (4-5h)
- 替换关键词匹配为 LLM 意图解析
- 工具编排优化
- 重试控制

#### 3. Analyzer LLM 推理 (3-4h)
- 生成自然语言 reasons
- 生成 practice_advice
- 保留规则降级路径

#### 4. Critic Layer 2 LLM 审核 (3-4h)
- 加载 yaml 配置
- LLM 深度审核
- 拒绝处理流程

## 📝 变更文件清单

### 新增文件
- `apps/api/app/tools/retriever.py` (208 行)
- `apps/api/app/tools/formatter.py` (56 行)
- `apps/api/app/services/experimental_service.py` (156 行)
- `apps/api/tests/test_experimental.py` (217 行)
- `apps/api/test_v21_endpoint.py` (85 行)

### 修改文件
- `apps/api/app/agents/analyzer.py` (+135 行)
- `apps/api/app/api/v1/routes.py` (+33 行)
- `docs/progress/progress_zh.md` (更新迁移进度)

### 配置文件
- `apps/api/app/config/signals.yaml` (已存在)
- `apps/api/app/config/critic_rules.yaml` (已存在)

## ✅ 验证清单

- [x] 所有现有测试通过 (7/7)
- [x] 新增测试通过 (6/6)
- [x] `/query/experimental` 端点可访问
- [x] meta_report 返回真实数据
- [x] evidence items 结构正确
- [x] Critic 审核逻辑工作
- [x] 分析步骤追踪完整
- [x] 降级处理有效
- [x] 文档已更新

## 🎉 总结

**Milestone 1 圆满完成！**

v2.1 架构的数据流已完全打通，新端点可以：
- 从 OpenDota 获取真实数据
- 使用规则推理计算英雄评分
- 生成结构化证据
- 通过 Critic 审核
- 返回标准化响应

为 Milestone 2 的 LLM 增强打下了坚实基础。新旧架构并存，可以渐进式迁移，风险可控。
