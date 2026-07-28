# DotaMind Progress Snapshot (2026-07-23)

## 10:01 — V3.2-3 Recovery/Replan review-blocker fixes

### Fixes

- Recovery append capacity now uses the smaller of remaining Run tool budget and
  `plan.constraints.max_tool_calls - len(plan.tool_calls)`. If the producer cover
  required for all gaps exceeds that capacity, Recovery closes directly as
  `insufficient_evidence / replan_exhausted` without spending a Replan or a second
  Controller call.
- `RecoveryFeedback.remaining_tool_budget` now carries that effective capacity, so
  Replan validation matches executable capacity.
- The Replan validator now requires every appended tool to declare at least one kind in
  `RecoveryFeedback.missing_evidence`; a valid producer plus an unrelated tool is rejected.
- In Recovery mode, generic Controller validation and Replan invariant validation now run
  together and return combined feedback.
- Removed unreachable `ToolErrorCode.duplicate_tool_call`; duplicate fingerprints still map
  directly to `execution_budget_error`.

### Tests and documentation

- Added a graph test where the original plan already reaches `max_tool_calls`, proving a
  single-attempt `replan_exhausted` without spending a Replan or a second Controller call.
- Added a valid-producer-plus-unrelated-tool rejection test and a combined generic/Replan
  validation-error test.
- Updated the V3.2-3 design document with capacity and appended-tool constraints.
- Verified: `uv run ruff check .` passes; full `uv run pytest -q` reports
  `425 passed, 1 warning`.

### Commit boundary

- `AGENTS.md` remains a user-maintained independent modification and continues to be excluded
  from the V3.2-3 commit.

## 10:07 — V3.2-3 documentation closure and V3.2-4 entry point

### Phase status

- V3.2-3 was closed by commit `9a8dfae`; the phase blueprint status now reads
  "completed" instead of "implemented, pending final commit acceptance."
- The V3.2 master design and design index now mark V3.2-3 as completed and V3.2-4 request
  idempotency as the next phase.
- There is no standalone V3.2-4 implementation blueprint yet. Before implementation, the
  phase must define the InMemory `RequestRecord`, concurrent single-flight, public-response
  replay, and single-Turn commit boundaries.

### Verification and boundaries

- This update changes documentation only and does not rerun tests. It carries forward the
  V3.2-3 pre-commit verification of `425 passed, 1 warning`, Ruff, lock, and diff checks.
- The current implementation still fixes `request_id=None` in `run_init_node` and has no
  `RequestRecord`; V3.2-4 behavior is not implemented yet.
- `AGENTS.md` remains a user-maintained independent modification outside this documentation
  update.

## 10:29 — V3.2-4 Stateful Request Idempotency

### Implementation

- `POST /api/v1/plan` now accepts an optional UUID v4 `request_id`; the first release accepts
  only `(session_id, request_id)` and returns 422 when `session_id` is absent.
- Added a canonical request hash, `RequestRecord`, and owner token. The same key/hash replays
  the allowlisted public response without a second Graph or Turn; a different hash returns
  HTTP 409 `idempotency_conflict`.
- `InMemorySessionStore` now adds claim, failed-owner takeover, TTL/capacity cleanup, and an
  atomic `complete_request_with_turn` inside the existing per-session transaction so the Turn
  and completed record commit together.
- `RunContext.request_id` is passed from internal state. Request ids never enter prompts,
  history, AttemptRecords, or public traces. Replay creates no Run and retains the original
  `runtime.run_id`.

### Tests and documentation

- Added sequential/concurrent replay, conflict, cancellation takeover, TTL, capacity, cached
  response copy, and request-id propagation coverage; aligned Route, Session privacy, and
  existing PlanService tests.
- Added the V3.2-4 phase blueprint and aligned the master design, design index, overall
  architecture, technical architecture, and API documentation.
- Verified: `uv run ruff check .` passes; full `uv run pytest -q` reports
  `436 passed, 1 warning`; `uv lock --locked` and `git diff --check` pass.

### Explicit boundaries

- The guarantee applies only to stateful requests within one InMemorySessionStore process and
  its retention window. Stateless mode, Redis, multi-worker coordination, lease/fencing,
  restart recovery, and cross-Run tool caching remain V3.2-5/6 work.
- An unhandled exception or cancellation writes no Turn and permits a later same-hash takeover;
  cross-process exactly-once behavior after an upstream side effect is not promised in this
  phase.
