# DotaMind Documentation

This directory is the documentation entry point for the current
`feature/v3-functional-loop` development line.

## Start Here

Read documents in this order:

1. The latest timestamp-prefixed Chinese progress snapshot under
   [`progress/`](./progress/), with the matching English snapshot when needed.
2. [`design/DotaMind_V3.0_design.md`](./design/DotaMind_V3.0_design.md) for the
   current product stage, implemented capability map, and V3 roadmap.
3. [`design/DotaMind_MVP_v2.5.md`](./design/DotaMind_MVP_v2.5.md) for the
   constrained Tool Calling architecture boundaries that V3 must preserve.
4. [`technical/architecture.md`](./technical/architecture.md) for the current
   code and runtime map.

The current runtime has one business API, `POST /api/v1/plan`, backed by the
LangGraph agentic path. The internal query UI is `GET /debug/plan`.

## Document Status

### Current design

- [`design/DotaMind_V3.0_design.md`](./design/DotaMind_V3.0_design.md) — primary
  product and capability design.
- [`design/DotaMind_MVP_v2.5.md`](./design/DotaMind_MVP_v2.5.md) — primary
  architecture foundation.
- [`design/Planner层.md`](./design/Planner层.md),
  [`design/Validator层.md`](./design/Validator层.md),
  [`design/Tool层.md`](./design/Tool层.md),
  [`design/Evidence层.md`](./design/Evidence层.md), and
  [`design/Answer+Critic层.md`](./design/Answer+Critic层.md) — layer-level
  implementation detail.

### Roadmap and decision records

- [`design/V3.0_功能闭环缺口盘点.md`](./design/V3.0_功能闭环缺口盘点.md) — V3
  capability gaps and delivery slices.
- [`design/DotaMind_V3_node_tool_edge_inventory.md`](./design/DotaMind_V3_node_tool_edge_inventory.md)
  — node, tool, contract, and edge inventory.
- [`design/agent_basic_tool_priorities.md`](./design/agent_basic_tool_priorities.md)
  — tool priority input.
- [`design/time_patch_filtering.md`](./design/time_patch_filtering.md) and
  [`design/STRATZ工具审计与重构输入.md`](./design/STRATZ工具审计与重构输入.md)
  — scoped design and audit records.

### Technical reference

- [`technical/api.md`](./technical/api.md) — active and removed HTTP surface.
- [`technical/configuration.md`](./technical/configuration.md) — environment and
  policy sources of truth.
- [`technical/stratz_hero_page_graphql_inventory.md`](./technical/stratz_hero_page_graphql_inventory.md)
  and [`technical/stratz_player_page_graphql_inventory.md`](./technical/stratz_player_page_graphql_inventory.md)
  — empirical STRATZ operation inventories.
- [`technical/stratz_schema_reference.md`](./technical/stratz_schema_reference.md)
  and `technical/stratz_schema_introspection.json` — generated schema reference
  material.
- [`technical/cap-integration.md`](./technical/cap-integration.md) — parked
  future work; CAP/CROO integration is not on the active V3 development path.

### Progress and history

- [`progress/`](./progress/) contains immutable timestamp-prefixed bilingual
  handoff snapshots. Do not treat an older snapshot as current state.
- [`archive/`](./archive/) contains superseded product, UI, and pre-v2.5 design
  documents retained only for historical context.

## Source-of-Truth Rules

- Verify documentation claims against the current working tree before changing
  code.
- Registry definitions are authoritative for tool names, arguments, output
  paths, and evidence kinds.
- The contract registry is authoritative for output contracts.
- `apps/api/app/config/policy.yaml` and its Pydantic models are authoritative
  for business policy.
- Missing tools, invalid plans, upstream errors, and insufficient evidence are
  surfaced directly; do not document fallback or mock paths as supported
  behavior.
