# DotaMind Progress Snapshot (2026-08-01)

## 22:48 — V3.2-5 completion fixes and final acceptance

### Corrections

- Redis append/complete Lua scripts now replace only the top-level `turn_index` at the end
  of canonical JSON, so nested same-name fields such as `context_scope` are preserved.
- Added real-Redis acceptance coverage for nested-field integrity, failed takeover, same-session
  serialization, different-session concurrency, and rejection of expired-owner
  renew/release/append/complete/fail operations.
- Synchronized `AGENTS.md`, the V3.2 overview design, the V3.2-5 design, and the design entry
  document; V3.2-6 observability and fault injection is the next phase after V3.2-5.

### Verification

- Full pytest with `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`:
  `459 passed, 1 warning`.
- Normal pytest without the Redis environment variable: `446 passed, 13 skipped, 1 warning`;
  all skips are real-Redis integration tests.
- `uv run ruff check app tests`, `uv lock --locked`, and `git diff --check` all pass.

### Current status

- V3.2-5 implementation and real-Redis acceptance are complete. Redis Server restart durability
  still depends on AOF/RDB, fsync/save policy, and persistent volumes.
- The V3.2-5 changes remain in the working tree and are not committed; review the complete diff
  before committing.
