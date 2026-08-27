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

## Deterministic behavioral evals

These evals are fixture-backed and CI-friendly. They protect general agent
behavior and architecture boundaries; they do not depend on a provider's
current schedule, result, or match count.

| Area | User request | Expected behavior |
| --- | --- | --- |
| Tournament status | 这项赛事现在是什么状态？ | Resolve the fixture competition, inspect its schedule or results, and distinguish current facts from stale data |
| Tournament schedule | 下一场什么时候开始？ | Use the resolved fixture competition and return the next scheduled match with time context |
| Match detail | Spirit 和 Falcons 最近一次交手？ | Find fixture candidate matches, resolve ambiguity, and return a grounded match summary |
| Game follow-up | 第二局详细说说。 | Reuse only valid conversation context, obtain game detail, and answer with available data |
| Player performance | Malr1ne 那局表现怎么样？ | Resolve the player and match/game, then retrieve available recorded game facts through existing match/artifact capabilities |
| Player build | 他那局出了什么、怎么加点？ | Resolve the referenced player and game, then use bounded artifact retrieval for items and ability upgrades |
| Earlier match | 那他上一场呢？ | Resolve the follow-up reference and query a separate record when needed |
| Unsupported scope | 给我当前版本全英雄强度排行 | State that ranked-meta ranking is outside vNext Core without inventing an alternative |
| Ambiguous identity | 查一下 Nigma 最近比赛 | Ask for clarification or expose candidates when identity cannot be uniquely resolved |

## Fixture-backed agent evals

These opt-in evaluations run a real configured model against fixture-backed
PandaScore and OpenDota adapters, the real `AgentRuntime`, and the current
domain-tool registry. They test autonomous agent behavior without allowing a volatile live
provider response to determine the result.

- Tool sequences are observed rather than prescribed. The model decides whether
  it needs match detail or bounded artifact retrieval.
- Assertions cover fixture-grounded facts, unavailable-data boundaries,
  provider-private ID exclusion, and general tool-call budgets.
- A multi-turn eval passes the prior transcript into a fresh runtime call, so
  follow-up references must be resolved from actual conversation context.
- `DOTAMIND_AGENT_EVAL_BASE_URL` and `DOTAMIND_AGENT_EVAL_MODEL` are required;
  `DOTAMIND_AGENT_EVAL_API_KEY` is optional for compatible endpoints.
- They are marked `agent_eval`, skipped without explicit model configuration,
  and excluded from the ordinary deterministic CI acceptance path.
- The manual console writes one JSON record per console process under
  `apps/api/tests/vnext/testResult/`. It appends each completed or terminated
  turn to that record and retains the complete tool result content and
  structured error, so the directory is local-only and must not be shared.

Scripted behavioral tests are deterministic runtime regressions; they are not
autonomous real-model agent evals.

## Manual vNext console

Run `python -m scripts.vnext_agent_console --direct "<question>"` from
`apps/api` to exercise the configured vNext chain: local vNext configuration,
the model adapter, `AgentRuntime`, the domain-tool registry, and real provider
adapters. `--direct` only disables proxy environment variables in that console
process. Each console process writes one timestamped conversation record to
`tests/vnext/testResult/`; interactive mode appends follow-up turns to that
same file and preserves complete tool results.

## Live provider smoke evals

These checks exercise real provider integrations. They verify that a provider
response can be fetched, normalized, attributed, and surfaced with its
freshness or uncertainty. They are not exact-value assertions and do not make a
provider-data change a core architecture regression.

- Search a current competition and list a small schedule or results window.
- Search a current professional team and retrieve its available roster facts.
- Search a current professional player, preserve ambiguity, and retrieve the
  selected player's current-team identity.
- Resolve a current match candidate and request available detail.
- Retrieve a static catalog item and verify its committed snapshot provenance.

## Acceptance

Deterministic behavioral evals pass only when the final answer is supported by
fixture tool results, preserves identity and provider uncertainty, avoids
unsupported claims, and does not rely on a scenario-specific runtime branch.
Live smoke evals pass when the integration succeeds with appropriate source,
freshness, and uncertainty disclosure. Exact live provider values and match
counts are never fixed assertions because esports data changes.

New functionality adds or updates an eval before it adds a new special-case
execution path.
