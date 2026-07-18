# Project Session Context

At the start of every new session in this repository, before analyzing or editing code:

1. **Read the latest timestamp-prefixed Chinese progress snapshot** matching
   `docs/progress/YYYY-MM-DD_HH-mm_progress_zh.md` (sort by filename
   timestamp, take the newest). Use the matching `_progress_en.md` document
   when English terminology or bilingual consistency matters.
2. **Read the canonical design docs** under `docs/design/` and
   `docs/technical/` that are relevant to the task at hand. In particular:
   - `docs/design/DotaMind_MVP_v2.5.md` — primary architecture direction
     (v2.5 constrained tool calling). Treat this as the authority when
     discussing plan/graph/contract structure.
   - `docs/technical/stratz_hero_page_graphql_inventory.md` — empirical
     inventory of STRATZ hero-page GraphQL operations; authoritative for
     STRATZ tool design decisions.
   - `docs/technical/architecture.md` — current implementation map.
3. **Treat the latest progress snapshot as the primary handoff context**,
   then verify its claims against the current working tree before making
   changes. Snapshots record intent at a point in time; code may have
   moved on.
4. **Verify before recommending**. If a snapshot or design doc names a
   file, function, tool, or evidence kind, confirm it still exists in the
   current tree before relying on it. Memory of past sessions is not
   authoritative; `git log`, file reads, and grep are.
5. **Note known volatility**. STRATZ public GraphQL data drifts on an
   hour scale; tests and assertions must not pin exact win rates or
   match counts.

## Collaboration Rules

- When the user has not explicitly requested code changes, only analyze and
  discuss the issue. Do not edit files proactively.
- Treat `apps/web` as deprecated and do not modify it unless the user explicitly
  requests changes there. Use `/debug/plan` as the internal query test UI.
- After completing a meaningful phase of changes, update the progress
  documentation under `docs/progress/`. Keep the timestamp-prefixed Chinese and
  English progress snapshots aligned.

## Development Priorities

- This project is still in active development and is not yet in production.
  Prioritize implementing the target architecture and capabilities over
  preserving legacy behavior for stability.

- Do not add fallback behavior unless the user explicitly asks for it. Missing
  tools, implementation gaps, upstream errors, and bugs should be surfaced
  directly instead of hidden behind legacy paths.

- Do not use mock data to mask missing live integrations or incomplete tools.
  Mock data is acceptable only in tests or explicitly marked fixtures.

- For the v2.5 architecture, follow `docs/design/DotaMind_MVP_v2.5.md` as the
  primary design direction. Before discussing or planning architecture changes,
  read or reference this design document and keep the proposal aligned with it.

- Prefer exposing capability boundaries clearly, such as `insufficient_tools`,
  validation errors, or tool execution errors, over producing a superficially
  successful response.

- Prefer aggressive architectural simplification over low-risk but bloated
  parallel paths. When a capability is migrated to the target agentic
  architecture, remove or retire the old implementation path unless the user
  explicitly asks to keep compatibility.

- Favor deletion and consolidation. If code, routes, abstractions, mocks, or
  compatibility shims no longer serve the target architecture, remove them
  instead of preserving them "just in case."

- Avoid conservative duplicate implementations. Do not keep both old and new
  versions of the same capability merely for perceived stability during this
  development phase; expose gaps directly and continue the migration.

## Agentic Planning Semantics

- `intent` is a semantic label for the user's goal.
- It is not a routing key and must not select a fixed execution path.
- Execution is determined only by validated `tool_calls`.
- Response shape is determined by `output_contract`.
- Evidence obligations are determined by `required_evidence` and contract rules.
- Do not recreate old `task_type` behavior through `intent`. In particular,
  never add branches such as `if intent == "lane_outcome": run_lane_outcome_flow()`.
