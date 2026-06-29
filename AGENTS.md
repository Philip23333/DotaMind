# Project Session Context

At the start of every new session in this repository, before analyzing or editing code:

1. Read the latest timestamp-prefixed Chinese progress snapshot matching
   `docs/progress/YYYY-MM-DD_HH-mm_progress_zh.md`.
2. Use the matching `_progress_en.md` document when English terminology or
   bilingual consistency matters.
3. Treat the latest progress snapshot as the primary handoff context, then
   verify its claims against the current working tree before making changes.

## Collaboration Rules

- When the user has not explicitly requested code changes, only analyze and
  discuss the issue. Do not edit files proactively.
- Treat `apps/web` as deprecated and do not modify it unless the user explicitly
  requests changes there. Use `/debug/chat` as the internal query test UI.
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

- For the v2.5 architecture, follow `docs/design/MetaMind_MVP_v2.5.md` as the
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
