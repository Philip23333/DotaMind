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
