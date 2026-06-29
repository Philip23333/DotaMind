# MetaMind V3 Node / Tool / Edge Inventory

> This document lists the expected V3 graph shape and the current landing scope.
> It is an implementation guide for moving the project from fixed service
> pipelines toward a LangGraph-compatible agent workflow.

## Purpose

MetaMind is moving from:

```text
query -> route to fixed service -> fixed retriever/analyzer/formatter chain
```

to:

```text
query -> planner -> validated tool calls -> evidence graph -> answer/review/response
```

The goal is not to create a new fixed pipeline for every feature. The goal is to
make user intent drive a constrained plan, then let deterministic tools fetch
evidence that later nodes can analyze, review, and format.

## Current Implemented Shape

The current `/api/v1/plan` chain is already split into node-like functions, but
it does not use LangGraph runtime yet:

```text
AgentGraphRunner
  -> planner_node
  -> validate_plan_node
  -> tool_executor_node
  -> evidence_node
  -> answer_node
  -> critic_node
  -> formatter_node
```

Currently registered agentic tools:

```text
resolve_hero
stratz.hero_vs_hero_matchup
```

OpenDota, patch notes, and more STRATZ functions exist as integrations or legacy
pipeline capabilities, but most of them are not registered as agentic tools yet.

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

`formatter_node` should eventually become `response_node`, because the final
layer should decide the response type, not just serialize state.

## Node Inventory

| Node | Expected implementation | Current landing scope |
|---|---|---|
| `planner_node` | LLM creates a constrained `ExecutionPlan` from query, game, registry, and policy. | Already exists. Keep it as the only node that decides tool combinations. |
| `validate_plan_node` | Validate tool names, duplicate ids, max calls, mock policy, evidence requirements, and tool argument references. | Already exists. Keep validation deterministic and fail loudly. |
| `tool_executor_node` | Execute registered tools, resolve `$tool_id.data.path`, expose tool errors in state. | Already exists. Keep execution generic; do not add business branching here. |
| `evidence_node` | Convert `ToolResult[]` into an `EvidenceGraph` with evidence kinds, missing evidence, source quality, and sample metadata. | Already exists for hero identity and hero matchup evidence. Extend as new tools land. |
| `answer_node` / `analyzer_node` | Turn evidence into structured conclusions for the requested output contract. Later may use LLM with strict evidence grounding. | Already exists as rule-based `AnswerSynthesizer`. First supported output is `draft_advice`. |
| `critic_node` | Review evidence coverage, mock usage, tool failures, sample size, freshness, and answer confidence. | Already exists as rule-based `AgenticCritic`. Extend rules as tools expose richer metadata. |
| `response_node` | Select final API shape: report, direct answer, insufficient tools, validation error, or tool error. | Not implemented. Current `formatter_node` serializes state and is the migration target. |
| `replan_node` | Optional future node for one bounded retry when critic finds recoverable missing evidence. | Out of scope now. No automatic fallback or retry. |

## Tool Inventory

### Local / Constants

| Tool | Expected implementation | Current landing scope |
|---|---|---|
| `resolve_hero` | Resolve user hero names and aliases to canonical hero ids. | Implemented and registered. Uses local Dota hero constants. |
| `resolve_team` | Resolve team name/tag aliases to canonical team id and candidates. | Expected. Current resolver exists in legacy retriever, not agentic registry. |
| `resolve_patch` | Normalize patch phrases such as latest patch or 7.41d. | Expected. Not implemented as agentic tool. |

### STRATZ

| Tool | Expected implementation | Current landing scope |
|---|---|---|
| `stratz.hero_vs_hero_matchup` | Return hero matchup advantage/disadvantage, win rate, and sample size. | Implemented and registered. |
| `stratz.hero_synergy` | Return teammate synergy stats for ally hero and optional role filters. | Expected. Not implemented. |
| `stratz.lane_outcome` | Return lane outcome data for with/against hero context. | Integration method exists, not registered as a tool. |
| `stratz.hero_meta` | Return patch/week/bracket hero meta stats. | Expected. Not implemented. |

### OpenDota

| Tool | Expected implementation | Current landing scope |
|---|---|---|
| `opendota.resolve_team` | Fetch cached `/teams`, resolve exact/fuzzy team candidates, expose ambiguity. | Expected next tool. Logic exists in legacy retriever. |
| `opendota.team_recent_matches` | Return all team matches in requested window, latest match time, record, and source freshness. | Expected next tool. Logic exists in `OpenDotaTeams`. |
| `opendota.team_players` | Return current players from OpenDota team player data. | Expected next tool. Integration exists. |
| `opendota.team_heroes` | Return team hero usage from sampled match details. | Expected next tool. Integration exists. |
| `opendota.hero_stats_by_role` | Return role-filtered hero meta stats from `/heroStats`. | Expected next tool. Integration exists. |

### Patch / Local Data

| Tool | Expected implementation | Current landing scope |
|---|---|---|
| `patch.get_records` | Load structured local patch records. | Expected. Existing loader is not registered as an agentic tool. |
| `patch.hero_changes` | Return hero-specific patch changes and polarity. | Expected. Existing helper is not registered as an agentic tool. |
| `patch.item_changes` | Return item-specific patch changes and polarity. | Expected. Existing helper is not registered as an agentic tool. |

### Internal Ranking Helpers

| Tool | Expected implementation | Current landing scope |
|---|---|---|
| `rank_counter_pick_candidates` | Rank matchup candidates using matchup, sample, role, and patch evidence. | Expected later. Do not implement until enough evidence tools exist. |
| `rank_synergy_candidates` | Rank ally synergy candidates using synergy, role, and sample evidence. | Expected later. Do not implement until STRATZ synergy is available. |
| `filter_heroes_by_role` | Filter candidate heroes by requested Dota role/position. | Expected later. Can be local deterministic helper. |

## Edge Inventory

| Edge | Expected implementation | Current landing scope |
|---|---|---|
| `START -> planner_node` | Every `/api/v1/plan` request starts with planner state. | Implemented. |
| `planner_node -> validate_plan_node` | Only when planner returns `planned` with a plan. | Implemented. |
| `planner_node -> response_node` | When planner returns `insufficient_tools` or `error`. | Current target is `formatter_node`. No fallback. |
| `validate_plan_node -> tool_executor_node` | Only when plan validation succeeds. | Implemented. |
| `validate_plan_node -> evidence_node` | When validation fails, build an empty/partial graph for inspection. | Implemented for error path. |
| `tool_executor_node -> evidence_node` | Always build evidence from whatever tool results exist. | Implemented. |
| `evidence_node -> response_node` | Fatal execution errors stop before answer synthesis. | Current target is `formatter_node`. |
| `evidence_node -> answer_node` | Usable execution result proceeds to answer synthesis. | Implemented. |
| `answer_node -> critic_node` | Any synthesized answer is reviewed before response. | Implemented. |
| `critic_node -> response_node` | Pass/warning/failed review all become explicit response state. | Current target is `formatter_node`. |
| `critic_node -> replan_node` | Later bounded retry for recoverable missing evidence. | Out of scope. |
| `replan_node -> validate_plan_node` | Later retry loops back through deterministic validation. | Out of scope. |

## Implementation Priority

1. Keep `/api/v1/plan` as the experimental agentic route. Do not fallback to
   `/api/v1/query`.
2. Rename or replace `formatter_node` with `response_node` when response
   selection becomes more than serialization.
3. Register existing OpenDota team capabilities as separate tools instead of
   copying the legacy team report pipeline.
4. Register STRATZ `lane_outcome` before building synergy or lane-specific
   advice.
5. Extend `EvidenceGraph` only when a new tool needs a new evidence kind.
6. Add ranking helpers only after the raw evidence tools are stable.

## Out of Scope

- No LangGraph runtime dependency in the current landing scope.
- No automatic fallback to old report pipeline.
- No mock data to hide missing live integrations.
- No replan loop until the first-pass tool inventory is broader.
- No new fixed business pipeline for counter-pick, synergy, team, meta, or patch
  reports.

