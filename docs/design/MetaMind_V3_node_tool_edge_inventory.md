# MetaMind V3 Node / Tool / Edge Inventory

> This document tracks the target V3 graph shape, the current implementation,
> and the next tool-splitting targets. It should be updated whenever `/api/v1/plan`
> gains new nodes, tools, contracts, or edge behavior.

## Purpose

MetaMind is moving from fixed service pipelines:

```text
query -> route to fixed service -> fixed retriever/analyzer/formatter chain
```

to a constrained agentic workflow:

```text
query -> planner -> validated tool calls -> evidence graph -> answer/review/response
```

The goal is not to create a new fixed pipeline for every feature. User intent
should drive an `ExecutionPlan`; deterministic tools fetch evidence; later nodes
synthesize, review, and format the answer. Missing tools, invalid plans, and
upstream failures are exposed directly. No fallback to the old report pipeline.

## Current Implemented Shape

The current `/api/v1/plan` chain is implemented as node functions registered in
a LangGraph `StateGraph`. `AgentGraphRunner` now owns the compiled graph and
injects the planner, tool executor, evidence builder dependencies, answer
synthesizer, and critic into thin node wrappers.

```text
AgentGraphRunner
  -> StateGraph(AgentRunState)
      START -> planner_node
      planner_node -> validate_plan_node | response_node
      validate_plan_node -> tool_executor_node | evidence_node
      tool_executor_node -> evidence_node
      evidence_node -> answer_node | response_node
      answer_node -> critic_node | response_node
      critic_node -> response_node
      response_node -> END
```

Current core pieces:

- `AgenticPlanner`: LLM creates a constrained `ExecutionPlan`.
- `Contract Registry`: centralizes output contracts, required evidence, examples,
  and plan validation against registered tool evidence kinds.
- `ToolRegistry` / `ToolExecutor`: registers deterministic tools and executes
  planned calls.
- `EvidenceGraph`: aggregates `ToolResult[]` through tool-level evidence
  extractors.
- `AnswerSynthesizer`: routes to `StructuredReportSynthesizer` or
  `NaturalLanguageAnswerSynthesizer`.
- `AgenticCritic`: checks missing evidence, mock usage, tool failures, answer
  status, and confidence.
- `response_node`: selects response type and serializes state.
- `/debug/plan`: visual debug page for trace, plan, tool results, evidence,
  answer, review, and raw JSON.

Currently registered agentic tools:

```text
resolve_hero
stratz.hero_vs_hero_matchup
stratz.lane_outcome
opendota.resolve_team
opendota.team_recent_matches
opendota.team_players
opendota.team_heroes
opendota.hero_stats_by_role
patch.get_records
patch.hero_changes
patch.item_changes
```

Currently registered output contracts:

```text
patch_impact_report
role_meta_report
team_recent_report
hero_matchup_report
draft_advice
natural_language_answer
```

`meta_list` is not an output contract. It means the internal whitelist of
structured contracts.

## Expected V3 Shape

Expected V3 graph:

```mermaid
flowchart TD
    START["START"] --> Planner["planner_node"]
    Planner -->|planned| Validate["validate_plan_node"]
    Planner -->|insufficient_tools or error| Response["response_node"]
    Validate -->|valid| Tools["tool_executor_node"]
    Validate -->|invalid| Evidence["evidence_node"]
    Tools --> Evidence
    Evidence -->|fatal tool error| Response
    Evidence -->|usable evidence| Answer["answer_node / analyzer_node"]
    Answer --> Critic["critic_node"]
    Critic -->|pass, warning, failed| Response
    Critic -. later .->|recoverable missing evidence| Replan["replan_node"]
    Replan -. later .-> Validate
```

LangGraph runtime shape:

```text
AgentRunState -> StateGraph(AgentRunState)
  add_node(planner)
  add_node(validate_plan)
  add_node(tool_executor)
  add_node(evidence)
  add_node(answer)
  add_node(critic)
  add_node(response)
  compile()
```

The LangGraph migration is runtime-only. Node business logic lives under
`apps/api/app/agentic/nodes/`, public `/api/v1/plan` response shape is
unchanged, and `replan_node` remains out of scope.

## Node Inventory

| Node | Expected implementation | Current status |
|---|---|---|
| `planner_node` | LLM creates constrained `ExecutionPlan` from query, game, tool registry, and Contract Registry. | Implemented. Uses registry-rendered contract prompt. |
| `validate_plan_node` | Validate duplicate ids and basic graph shape. Catalog validation happens in Planner. | Implemented. Keep deterministic and narrow. |
| `tool_executor_node` | Execute registered tools, resolve `$tool_id.data.path`, expose tool errors in state. | Implemented. Generic; no business branching. |
| `evidence_node` | Convert `ToolResult[]` into `EvidenceGraph` through tool-level evidence extractors. | Implemented. Uses registry `evidence_extractor` and `evidence_kinds`. |
| `answer_node` / `analyzer_node` | Turn evidence into structured reports or evidence-grounded natural language. | Implemented first pass. Structured reports are still minimal. |
| `critic_node` | Review evidence coverage, mock usage, tool failures, answer status, confidence, and later freshness/sample rules. | Implemented rule-first base. Needs evidence-kind-specific quality rules. |
| `response_node` | Select final API shape: contract output, natural answer, insufficient evidence, tool error, or capability boundary. | Implemented. Replaced old formatter role. |
| `replan_node` | Optional bounded retry when critic finds recoverable missing evidence. | Not implemented. Still out of scope. |

## Tool Inventory

### Local / Constants

| Tool | Expected implementation | Current status |
|---|---|---|
| `resolve_hero` | Resolve user hero names and aliases to canonical hero ids. | Implemented and registered. Uses local Dota hero constants. |
| `hero.enrich_identity` | Convert hero ids in evidence rows into localized names and aliases. | Next target. Needed before product-quality matchup/draft answers. |
| `resolve_patch` | Normalize patch phrases such as latest patch or 7.41d. | Not implemented as separate tool. Patch tools accept `patch="latest"`. |
| `filter_heroes_by_role` | Filter candidate heroes by requested Dota role/position. | Next target after hero enrichment. Can be local deterministic helper. |

### STRATZ

| Tool | Expected implementation | Current status |
|---|---|---|
| `stratz.hero_vs_hero_matchup` | Return hero matchup advantage/disadvantage, win rate, and sample size. | Implemented and registered. |
| `stratz.lane_outcome` | Return lane outcome data for with/against hero context. | Implemented and registered. |
| `stratz.hero_synergy` | Return teammate synergy stats for ally hero and optional role filters. | Next target. Required for teammate combo questions. |
| `stratz.hero_meta` | Return patch/week/bracket hero meta stats. | Not implemented. Lower priority while OpenDota role stats exist. |

### OpenDota

| Tool | Expected implementation | Current status |
|---|---|---|
| `opendota.resolve_team` | Fetch cached `/teams`, resolve exact/fuzzy team candidates, expose ambiguity. | Implemented and registered. |
| `opendota.team_recent_matches` | Return all team matches in requested window, latest match time, record, cache stats. | Implemented and registered. |
| `opendota.team_players` | Return current players from OpenDota team player data. | Implemented and registered. |
| `opendota.team_heroes` | Return team hero usage from sampled match details. | Implemented and registered. |
| `opendota.hero_stats_by_role` | Return role-filtered hero meta stats from `/heroStats`. | Implemented and registered. |
| `opendota.hero_detail` | Return richer per-hero stats/details for one hero. | Next target if role reports need deeper explanations. |

### Patch / Local Data

| Tool | Expected implementation | Current status |
|---|---|---|
| `patch.get_records` | Load structured local patch records. | Implemented and registered. |
| `patch.hero_changes` | Return hero-specific patch changes and polarity. | Implemented and registered. |
| `patch.item_changes` | Return item / neutral item / enchantment changes and polarity. | Implemented and registered. |
| `patch.context_for_heroes` | Join patch changes onto a candidate hero list. | Next target. Needed for draft advice and role meta explanations. |

### Internal Ranking Helpers

| Tool | Expected implementation | Current status |
|---|---|---|
| `rank_counter_pick_candidates` | Rank matchup candidates using matchup, sample, role, patch, and lane evidence. | Next target after hero enrichment and role filter. |
| `rank_synergy_candidates` | Rank ally synergy candidates using synergy, role, and sample evidence. | Next target after `stratz.hero_synergy`. |
| `rank_role_meta_candidates` | Rank role candidates using OpenDota stats plus patch context. | Later. Current role report uses raw OpenDota rows. |

## Contract Inventory

| Contract | Route | Current status | Required evidence |
|---|---|---|---|
| `patch_impact_report` | structured | Implemented minimal summary. | `patch_records` |
| `role_meta_report` | structured | Implemented minimal recommendations from role stats. | `hero_stats` |
| `team_recent_report` | structured | Implemented minimal team evidence summary. | `team_identity`, `recent_matches` |
| `hero_matchup_report` | structured | Implemented minimal matchup rows. | `matchup_win_rate` |
| `draft_advice` | structured | Implemented only counter-pick evidence rows, not full draft recommendation. | `hero_identity`, `matchup_win_rate`, `sample_size` |
| `natural_language_answer` | natural language | Implemented first pass with EvidenceGraph grounding. | none by default |

## Edge Inventory

| Edge | Expected implementation | Current status |
|---|---|---|
| `START -> planner_node` | Every `/api/v1/plan` request starts with planner state. | Implemented. |
| `planner_node -> validate_plan_node` | Only when planner returns `planned` with a plan. | Implemented. |
| `planner_node -> response_node` | Planner `insufficient_tools` or `error` stops before tools. | Implemented. No fallback. |
| `validate_plan_node -> tool_executor_node` | Only when graph-shape validation succeeds. | Implemented. |
| `validate_plan_node -> evidence_node` | Validation errors still build inspectable graph state. | Implemented for error path. |
| `tool_executor_node -> evidence_node` | Always build evidence from available tool results. | Implemented. |
| `evidence_node -> response_node` | Fatal tool execution errors stop before answer synthesis. | Implemented. |
| `evidence_node -> answer_node` | Usable execution result proceeds to answer synthesis. | Implemented. |
| `answer_node -> critic_node` | Any synthesized answer is reviewed before response. | Implemented. |
| `critic_node -> response_node` | Pass/warning/failed review all become explicit response state. | Implemented. |
| `critic_node -> replan_node` | Optional later retry for recoverable missing evidence. | Not implemented. |
| `replan_node -> validate_plan_node` | Later retry loops back through deterministic validation. | Not implemented. |

## Next Tool-Splitting Targets

Priority order for the next implementation phase:

1. `hero.enrich_identity`
   - Input: `hero_ids` or evidence refs containing `hero_id`.
   - Output: id -> localized name, internal name, aliases.
   - Evidence kinds: `hero_identity`, optionally `hero_name_map`.
   - Why: current matchup and draft answers still expose raw `hero_id` values.

2. `filter_heroes_by_role`
   - Input: hero candidate rows plus requested role/position.
   - Output: filtered candidates with role-fit metadata.
   - Evidence kinds: `role_fit`, `candidate_pool`.
   - Why: counter-pick recommendations need role-aware candidate pools.

3. `patch.context_for_heroes`
   - Input: `hero_ids` / hero names and `patch="latest"`.
   - Output: patch buffs/nerfs/neutral changes attached to those heroes.
   - Evidence kinds: `hero_patch_changes`, `patch_context`.
   - Why: draft and role reports need patch explanation, not just raw win rate.

4. `stratz.hero_synergy`
   - Input: ally `hero_id`, optional role/bracket/week filters.
   - Output: teammate synergy rows with win rate and sample size.
   - Evidence kinds: `synergy_win_rate`, `sample_size`.
   - Why: required for “my teammate picked X, what should I pick?” questions.

5. `rank_counter_pick_candidates`
   - Input: matchup evidence, role filter evidence, patch context, sample thresholds.
   - Output: ranked candidate list with rationale components.
   - Evidence kinds: `ranked_candidate`, `sample_size`.
   - Why: moves `draft_advice` from raw matchup rows to actual recommendations.

6. `rank_synergy_candidates`
   - Input: synergy evidence, role filter evidence, sample thresholds.
   - Output: ranked ally-combo candidate list.
   - Evidence kinds: `ranked_candidate`, `synergy_win_rate`, `sample_size`.
   - Why: completes the teammate-combo use case.

## Implementation Priority

1. Keep `/api/v1/plan` as the only active API workflow. Do not fallback to any
   deleted report/query route.
2. Keep deleting or retiring old paths as capabilities migrate to agentic tools.
3. Add raw evidence tools before ranking helpers.
4. Add hero identity enrichment before improving draft answer copy.
5. Improve evidence quality rules per evidence kind before claiming product-grade
   recommendations.
6. Use the LangGraph runtime as the orchestration layer for `/api/v1/plan`;
   keep future tool work inside deterministic tool contracts rather than graph
   branches.

## Out of Scope

- No automatic fallback to old report pipeline.
- No compatibility shell for deleted `/api/v1/query` or fixed report endpoints.
- No mock data to hide missing live integrations.
- No replan loop until the tool inventory is broader.
- No new fixed business pipeline for counter-pick, synergy, team, meta, or patch
  reports.
- No extra LangGraph business branches beyond the current node/edge inventory.
