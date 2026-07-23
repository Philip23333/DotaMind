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
