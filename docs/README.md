# DotaMind Documentation

This directory is the documentation entry point for the current V3 development
line.

## Start Here

Read documents in this order:

1. The latest daily cumulative Chinese progress snapshot under
   [`progress/`](./progress/), with the matching English snapshot when needed.
2. [`technical/architecture.md`](./technical/architecture.md) for the current
   code, persistence, memory, and runtime map.
3. [`design/versions/DotaMind_MVP_v2.5.md`](./design/versions/DotaMind_MVP_v2.5.md)
   for the constrained Tool Calling architecture boundaries that V3 preserves.
4. [`design/architecture/整体架构.md`](./design/architecture/整体架构.md),
   [`design/architecture/Controller层.md`](./design/architecture/Controller层.md), and
   [`design/architecture/ConversationMemory层.md`](./design/architecture/ConversationMemory层.md)
   for current design details.
5. Version blueprints under [`design/versions/`](./design/versions/) when
   historical phase intent or acceptance boundaries matter.

The current runtime has one LangGraph business path exposed through stateless
`POST /api/v1/plan` debug requests and durable PostgreSQL-backed Chat Runs. The
internal inspection UI is `GET /debug/plan`; `apps/chat` is the formal
Next.js/assistant-ui client for Chat Session and Chat Run APIs.

## Document Status

### Version blueprints

- [`design/versions/DotaMind_V3.2_design.md`](./design/versions/DotaMind_V3.2_design.md) — completed
  runtime-foundation baseline. Its original SessionStore sections are historical;
  current formal chat persistence is documented separately.
- [`design/versions/DotaMind_V3.2-1_design.md`](./design/versions/DotaMind_V3.2-1_design.md)
  — completed Run / Attempt / Budget implementation blueprint.
- [`design/versions/DotaMind_V3.3-1_design.md`](./design/versions/DotaMind_V3.3-1_design.md)
  and [`design/versions/DotaMind_V3.3-2_design.md`](./design/versions/DotaMind_V3.3-2_design.md)
  — PostgreSQL Chat and detached Chat Run historical blueprints; later memory
  and frontend changes are called out in those documents.
- [`design/versions/DotaMind_V3.3-3_design.md`](./design/versions/DotaMind_V3.3-3_design.md)
  — completed committed Valve Catalog implementation blueprint.
- [`design/versions/DotaMind_V3.3-4_design.md`](./design/versions/DotaMind_V3.3-4_design.md)
  — completed unified direct-answer and conversation-contract simplification blueprint.
- [`design/versions/DotaMind_V3.0_design.md`](./design/versions/DotaMind_V3.0_design.md) — primary
  product and capability design.
- [`design/versions/DotaMind_MVP_v2.5.md`](./design/versions/DotaMind_MVP_v2.5.md) — primary
  architecture foundation.

### Architecture design

- [`design/architecture/Controller层.md`](./design/architecture/Controller层.md),
  [`design/architecture/ConversationMemory层.md`](./design/architecture/ConversationMemory层.md),
  [`design/architecture/Validator层.md`](./design/architecture/Validator层.md),
  [`design/architecture/Tool层.md`](./design/architecture/Tool层.md),
  [`design/architecture/Evidence层.md`](./design/architecture/Evidence层.md), and
  [`design/architecture/Answer+Critic层.md`](./design/architecture/Answer+Critic层.md)
  — layer-level
  implementation detail.
- [`design/architecture/DotaMind_V3_node_tool_edge_inventory.md`](./design/architecture/DotaMind_V3_node_tool_edge_inventory.md)
  — current and target node, tool, contract, and edge inventory.

### Tool design and roadmaps

- [`design/tools/time_patch_filtering.md`](./design/tools/time_patch_filtering.md)
  and [`design/tools/STRATZ工具审计与重构输入.md`](./design/tools/STRATZ工具审计与重构输入.md)
  — tool-specific design and audit records.
- [`design/roadmaps/V3.0_功能闭环缺口盘点.md`](./design/roadmaps/V3.0_功能闭环缺口盘点.md) — V3
  capability gaps and delivery slices.
- [`design/roadmaps/agent_basic_tool_priorities.md`](./design/roadmaps/agent_basic_tool_priorities.md)
  — tool priority input.
- [`design/README.md`](./design/README.md) defines the classification rules for
  future design documents.

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

- [`progress/`](./progress/) contains one cumulative bilingual snapshot pair per
  calendar date. Legacy timestamp-prefixed snapshots remain historical; do not
  treat an older snapshot as current state.
- [`archive/`](./archive/) contains superseded product, UI, and pre-v2.5 design
  documents retained only for historical context.
- [`interview_review/Prompt职责边界与重构复盘.md`](./interview_review/Prompt职责边界与重构复盘.md)
  records verified prompt-responsibility findings and future refactoring review
  items. It is a study/review aid, not a runtime source of truth.

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
