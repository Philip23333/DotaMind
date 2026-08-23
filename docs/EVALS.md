# Evals

## Role

Scenarios belong in evaluations, not runtime branches, prompt workflows, or
tool descriptions. An eval checks whether a general-purpose agent can select
the needed domain capabilities, use conversation context, and respect data
boundaries.

## Evaluation dimensions

- Correct domain-tool selection
- Coherent tool sequence without hard-coded workflow support
- Correct entity and follow-up reference resolution
- Factual answer quality and source disclosure
- Explicit handling of ambiguity, missing data, and unsupported requests
- Tool-call efficiency and general budget compliance

## Initial scenario set

| Area | User request | Expected behavior |
| --- | --- | --- |
| Tournament status | 现在 TI 最新战况？ | Resolve the event, inspect current schedule or results, and distinguish live facts from stale data |
| Tournament schedule | 下一场什么时候开始？ | Use the resolved competition and return the next scheduled match with time context |
| Match detail | Spirit 和 Falcons 最近一次交手？ | Find candidate matches, resolve ambiguity, and return a grounded match summary |
| Game follow-up | 第二局详细说说。 | Reuse only valid conversation context, obtain game detail, and answer with available data |
| Player performance | Malr1ne 那局表现怎么样？ | Resolve player and game references, then return recorded performance facts |
| Player build | 他那局出了什么、怎么加点？ | Obtain a match build and disclose unavailable parsed fields |
| Earlier match | 那他上一场呢？ | Resolve the follow-up reference and query a separate record when needed |
| Unsupported scope | 给我当前版本全英雄强度排行 | State that ranked-meta ranking is outside vNext Core without inventing an alternative |
| Ambiguous identity | 查一下 Nigma 最近比赛 | Ask for clarification or expose candidates when identity cannot be uniquely resolved |

## Acceptance

An eval passes only when the final answer is supported by tool results, preserves
identity and provider uncertainty, avoids unsupported claims, and does not rely
on a scenario-specific runtime branch. Exact provider values and match counts
are not fixed assertions because live esports data changes.

New functionality adds or updates an eval before it adds a new special-case
execution path.
