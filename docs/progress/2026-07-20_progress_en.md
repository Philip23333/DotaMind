# DotaMind Progress Snapshot: 2026-07-20

## 12:54 — V3.2-1 Run / Attempt / Budget implementation closure

- Fixed the long-term V3.2 state boundary as a flat `AgentRunState` plus the
  centralized `reset_attempt_working_state()` function. No
  `InternalAttemptState`, `current_attempt`, proxy properties, dual writes, or
  second attempt were introduced. Reset returns an independent state, clears
  all attempt-local work centrally, and deep-copies retained
  budget/history/attempts/trace values.
- Added strict runtime models, `SystemClock`/`FakeClock`, UUID4/UTC
  `RunContext`, global `RunBudget`, separate `TerminalStage`/`FailureStage`
  types, pure terminal reduction, and sanitized `AttemptRecord` summaries.
  Attempts never retain complete plans/results, answer text, Critic reasons,
  raw exceptions, or recovery fields.
- Changed `ToolExecutor.execute()` to return the original `ToolResult` plus a
  private `ToolDispatchRecord`. Registry/reference/input validation failures
  do not consume tool budget; a synchronous callback counts immediately before
  handler entry, so successful and failed handlers each count exactly once.
  Internal dispatch data is not added to public ToolResult metadata.
- Integrated `run_init -> single-attempt execution -> run_finalize -> response`
  into the Graph. Every controlled terminal is reduced before serialization
  and creates exactly one AttemptRecord. Missing effective evidence terminates
  before Answer. Deadline observation uses monotonic elapsed time and does not
  enforce a budget/timeout gate in this phase.
- Trace retains the two-event `planned -> completed/failed` order per node and
  adds run/attempt/UTC/duration fields. `run_init` and `run_finalize` are traced;
  response adds no event. Controller, handler, and Answer budgets count their
  true entry points, while Replan remains zero.
- `/api/v1/plan` now requires a strict `runtime` DTO exposing Run, Budget, and
  one sanitized Attempt; stateful safe failures also include minimal runtime.
  Existing top-level plan/tool-results/evidence/answer/review schemas remain,
  and `/debug/plan` now displays Run/Attempt/Budget and timed trace data.
- Updated the V3.2-1 and overall V3.2 designs, node inventory, technical
  architecture, and API documentation for Attempt privacy, the complete
  terminal table, private dispatch channel, monotonic deadlines, response
  responsibility migration, and the V3.2-6 unhandled-exception/cancellation
  boundary.

### Verification

- V3.2-0 characterization baseline: `87 passed, 1 warning`, preserving the
  original scenario and assertion count.
- Full API suite: `381 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- `uv run ruff check .` passed.
- `uv lock --check` passed.
- `git diff --check` passed with only the repository's existing LF/CRLF
  conversion notices.
- The exact frozen Tool Registry assertion is included in the passing suites.
  No live DeepSeek/STRATZ request was run, and no volatile STRATZ value was pinned.

## 13:11 — Overall architecture and layered diagrams

- Added `docs/design/architecture/整体架构.md` as an end-to-end view of the
  currently implemented V3.2-1 worktree, covering the request boundary,
  single-attempt Graph, constrained tool calling, evidence obligations,
  Run/Attempt/Budget, Session flow, terminal/public boundary, and the later
  V3.2-2 through V3.2-6 capabilities.
- Added Mermaid diagrams for Session injection, tool execution, evidence
  obligations, and terminal finalization to `Controller层.md`, `Tool层.md`,
  `Evidence层.md`, and `Answer+Critic层.md`, and linked the node inventory to
  the new overall architecture entry point.
- Corrected stale layered-document facts to match the current tree: tool errors
  now route directly to `run_finalize_node`, missing effective evidence closes
  before Answer, ToolExecutor uses a private `ToolDispatchRecord`, and response
  only serializes an already reduced terminal outcome plus required runtime.
- Updated `docs/design/README.md` to list `整体架构.md` as the unified entry for
  architecture documentation.

### Verification

- Local Markdown links in the modified design documents passed validation.
- `git diff --check` passed with only the repository's existing LF/CRLF
  conversion notices.
- This update only reorganized documentation, so API tests and live
  DeepSeek/STRATZ requests were not rerun.

## 13:24 — V3.2-1 terminal and audit-contract review fixes

- Fixed the missing-plan Evidence invariant that emitted only a failed trace
  and was then reduced as success. It now records a stable error and terminates
  as `error/execution_error` at the `execution` stage instead of producing
  `ok/raw_tool_results`.
- Answer results with `error` or `insufficient_evidence` now route directly to
  `run_finalize_node` without executing Critic. Failed Answer trace closes as
  `failed`, and the Attempt no longer gets a misleading Critic summary.
- Restricted `AgentTraceEvent.status` to `planned | completed | failed`.
  Critic pass/warning maps to `completed`, while Critic failure maps to
  `failed`; severity remains only in the action and Critic summary rather than
  leaking into the trace lifecycle field.
- `reset_attempt_working_state()` now clears stale `terminal_stage` and
  `run_duration_ms`, preventing a future V3.2-3 attempt from inheriting a
  sealed terminal outcome.
- Removed reference-resolution `ToolResult.metadata.stage`; dispatch stage and
  stable error code now exist only in private `ToolDispatchRecord`. Updated
  Graph/runtime regressions, layered diagrams, and the V3.2-1 specification.

### Verification

- Focused review regressions: `49 passed`.
- V3.2-0 characterization baseline: `87 passed, 1 warning`, preserving its
  original count.
- Full API suite: `387 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- `uv run ruff check .`, `uv lock --check`, and `git diff --check` passed; diff
  check emitted only the repository's existing LF/CRLF conversion notices.
- No live DeepSeek/STRATZ request was run, and no volatile STRATZ value was pinned.
