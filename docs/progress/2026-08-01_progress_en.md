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

## 23:54 — Overall-architecture SessionStore status correction

### Documentation correction

- Corrected stale text in `docs/design/architecture/整体架构.md` that still described
  `InMemorySessionStore` as the only current backend and Redis/request idempotency as future
  work.
- The overview and Session sequence now consistently show `SessionStore: memory / Redis` and
  describe the V3.2-5 multi-worker lease, renewal, fencing, atomic-commit, and rebuild-recovery
  boundary.
- Clarified that data retention across Redis Server restarts still depends on AOF/RDB,
  fsync/save policy, and persistent volumes.

### Verification and boundaries

- This update changes documentation only and does not rerun tests; `git diff --check` validates
  the documentation diff.
- V3.2-5 was committed as `e67ee03` before this correction; the only current uncommitted changes
  are the architecture and bilingual progress-document fixes recorded in this section.

## 16:03 — V3.2-6 Runtime Foundation closure

### Implementation

- Added the V3.2-6 design document. Shared Attempt/Run finalizers retain one terminal resolver,
  and Attempt summaries now carry fixed failure stage/code.
- Extended the public Trace with tool, reuse, recovery, and failure fields. `/debug/plan` renders
  only existing public Trace/runtime/tool-result data.
- Added single-process Prometheus `/metrics` plus low-cardinality runtime, tool, Store/lock, and
  idempotency metrics. Deployment requires one scrape target per process.
- Unexpected graph failures now return HTTP 500 `execution_error` and write neither a Turn nor a
  completed replay. Controlled business failures retain their safe response, Turn, and replay semantics.
- Cancellation cleanup fails only the current owner's in-progress record. It never rolls back an
  already-committed atomic completion, ensuring either `completed + 1 Turn` or `failed + 0 Turn`.
- Controller, LLM, Answer, and transport logs no longer emit raw exceptions/upstream content; public
  tool errors are redacted to stable text.

### Verification

- Full pytest without Redis: `450 passed, 13 skipped, 1 warning`.
- Full pytest with `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`:
  `463 passed, 1 warning`.
- `uv run ruff check app tests`, `uv lock --check`, and `git diff --check` all passed.
- Added coverage for exception retry, post-commit cancellation replay, and the safe API 500 envelope.
  The existing real-Redis failed-takeover test continues to call `fail_request()` directly.

### Current status

- V3.2-6 is complete and business tools remain frozen. Subsequent work can be planned separately
  from the V3.2 runtime foundation.
