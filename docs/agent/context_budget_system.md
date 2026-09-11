# Context Budget System Design

## 1. Overview

当前 Agent Runtime 已具备：

- execution loop
- max steps limitation
- tool call limitation
- deadline handling
- exploration deadline
- finalization state
- event streaming

Runtime 已经能够感知执行预算状态。

但是目前存在：

> Runtime 知道执行状态，而 Model 不知道。

因此模型无法根据当前执行环境调整行为：

例如：

- 是否继续 discovery
- 是否停止重复查询
- 是否优先组织最终答案

Context Budget System 的目标：

> 将 Runtime 当前执行环境状态，以临时上下文形式暴露给 Model，同时保持 Runtime 与 Model 的职责边界。

---

# 2. Design Goals

## Included

Context Budget System 负责：

1. Runtime 状态统一抽象
2. Runtime 状态暴露给 Model
3. Runtime 状态写入 Trace

---

## Explicitly Not Included

当前版本不实现：

- Planner
- 自动任务拆解
- Tool selection controller
- Tool cost model
- Query optimizer
- Context compaction
- History pruning
- Artifact eviction

---

# 3. Responsibility Boundary

设计原则：

> Runtime 告诉 Model 当前执行环境，不决定 Model 下一步业务行为。


结构：

```
Runtime

    |
    | snapshot

    v

RuntimeContext

    |
    +----------------+
    |                |
    v                v

Prompt          Trace


    |

    v

Model
```

---

# 4. RuntimeContext

## 4.1 Definition

RuntimeContext 是：

> 当前 invocation 生命周期内的临时执行状态快照。


生命周期：

```
Model invocation start

        |

Create RuntimeContext

        |

Render runtime prompt

        |

Send to Model

        |

Record trace

        |

Discard
```

---

RuntimeContext：

- 不是 Message
- 不进入 conversation history
- 不持久化
- 不参与业务逻辑决策

---

# 5. RuntimeContext Schema

## Model Visible Fields

```yaml
RuntimeContext:

  phase:
    type: RuntimePhase

  remaining_turns:
    type: integer | null

  time_pressure:
    type: TimePressure

  context_pressure:
    type: ContextPressure

  tools_available:
    type: boolean
```

---

# 6. Runtime Phase

Runtime Phase 表示当前执行阶段。

枚举：

```
EXPLORATION
CONVERGING
FINALIZATION
```

---

## EXPLORATION

正常执行阶段。

允许：

- tool call
- information gathering
- artifact observation


Model guidance:

> Continue gathering information when needed, while making efficient progress.

---

## CONVERGING

预算开始收紧。

状态：

- 仍允许工具调用
- 不禁止 exploration

但是提示：

- 优先完成用户请求
- 避免重复验证
- 避免低价值探索


---

## FINALIZATION

最终回答阶段。

状态：

```
tools_available = false
```

要求：

- 使用已有信息
- 生成最终用户回答

---

# 7. Phase Transition

状态单向变化：

```
EXPLORATION

      |
      |
      v

CONVERGING

      |
      |
      v

FINALIZATION
```

不允许：

- 回退
- 循环

---

判断原则：

优先级：

```
if finalizing:

    FINALIZATION


elif remaining budget below threshold:

    CONVERGING


else:

    EXPLORATION
```

---

# 8. Remaining Turns

## Purpose

向 Model 暴露：

> 当前还可以进行多少执行轮次。


不暴露：

- internal step id
- deadline timestamp
- runtime implementation details


示例：

```
Remaining turns:
5
```

---

# 9. Time Pressure

Runtime 不暴露精确时间。

只暴露等级：

```
healthy
limited
critical
```

目的：

让 Model 感知：

- 是否需要加快收敛

而不是：

- 自己计算 deadline

---

# 10. Context Pressure

当前版本只提供状态接口。

等级：

```
normal
high
critical
```

---

v1 不负责：

- token counting
- history compression
- context cleanup

---

# 11. Runtime Prompt

## Definition

Runtime Prompt 是：

> RuntimeContext 到 Model 输入之间的临时渲染结果。


流程：

```
RuntimeContext

        |

RuntimePromptRenderer

        |

Temporary instruction

        |

Model input
```

---

Runtime Prompt：

不是：

- system message persistence
- conversation message
- history content

---

# 12. Model Input Structure

目标：

```
System Prompt

+

Runtime Prompt

+

Conversation History

+

Tools
```

---

Runtime Prompt 每次 invocation 重新生成。

---

# 13. Runtime Prompt Template

结构：

```
Runtime state:
Execution phase:
{phase}

Remaining turns:
{x}

Time pressure:
{x}

Context pressure:
{x}

Tools available:
{x}


Guidance:
{guidance}
```

---

## Exploration Guidance

```
You may continue gathering information when needed.

Prefer efficient progress toward answering the user's request.
```

---

## Converging Guidance

```
The execution budget is becoming constrained.

Prioritize completing the user's request.
Avoid optional exploration or redundant verification.

Use additional tools only when they materially improve the answer.
```

---

## Finalization Guidance

```
Further retrieval is unavailable.

Produce the final user-facing answer now.
Use the information already available.
```

---

# 14. Trace Integration

## Goal

Trace 需要回答：

> Model 当时看到的 Runtime 状态是什么？


记录：

每次 Model invocation：

```json
{
  "runtime_context": {
    "phase": "converging",
    "remaining_turns": 5,
    "time_pressure": "critical",
    "context_pressure": "high",
    "tools_available": true
  }
}
```

---

不记录：

```
runtime_prompt
```

原因：

- prompt 可以重新生成
- 结构化数据更适合分析

---

# 15. Implementation Plan

## Step 1

RuntimeContext 基础层。

目标：

将 Runtime 已有状态结构化。

不改变：

- execution loop
- tools
- messages

---

## Step 2

Runtime Prompt Renderer。

目标：

让 Model 感知 Runtime 状态。


要求：

- 临时注入
- 不进入 history

---

## Step 3

Trace Integration。

目标：

记录 Model invocation 时 RuntimeContext snapshot。

---

# 16. Validation

验证重点：

不是答案正确性。

重点观察：

## Behavior Metrics

| Metric | Goal |
|-|-|
| model invocation count | decrease |
| tool calls | decrease |
| repeated discovery | decrease |
| artifact.read usage | become reasonable |
| finalization stability | improve |

---

# 17. Evaluation Scenario

重点：

T7:

```
最近三届 TI 的冠军、比赛过程和趋势
```

观察：

Before:

- excessive discovery
- repeated queries
- context growth


After:

- earlier convergence
- fewer redundant calls
- stable finalization

---

# 18. Future Extensions

当前冻结。

未来可能方向：

- context compaction
- artifact lifecycle management
- tool cost awareness
- planner integration

但不属于 Context Budget System v1。

---
