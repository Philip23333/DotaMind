# DotaMind Progress Snapshot — 2026-08-02

## 17:44 — V3.2-6 blocker fixes and final acceptance

### Completed

- Centralized the closed `StableFailureCode` set and unknown-value normalization. Internal
  `NodeExecutionFailure` carries only safe state, node, and failure stage; raw exceptions do not enter
  state, Trace, logs, or metrics.
- Moved Run/Attempt observation to the Runner's single terminal boundary. Real results are recorded only
  after response succeeds; uncaught node, Graph, response, or finalizer failures return the same safe HTTP
  500 `execution_error`, write no Turn, and never cache completed.
- Fixed `fail_request()` to return `failed/completed/noop`; durable Memory/Redis results now drive
  idempotency metrics. Cancellation after Redis Lua commit preserves `completed + 1 Turn`, while
  pre-commit cancellation preserves `failed/takeover + 0 Turn`.
- Replaced Prometheus collectors with the 13 agreed low-cardinality, single-process metric families and
  exact names, labels, and buckets. No legacy aliases or multiprocess mode remain.
- Restricted key-value logging to allowlisted events and fields with eight-character ID prefixes.
  Controller, Tool, Recovery, Store, provider, and transport request paths no longer log exception text,
  dynamic URLs, or upstream responses.
- Reused tool results preserve the first real call's `latency_ms`. The tool counter records reuse, while the
  duration Histogram, handler count, and budget count only real dispatches.
- Enhanced `/debug/plan` with HTTP/Run/slowest-node/failure summaries, Attempt groups,
  Controller/Tools/Answer durations, tool reuse, Recovery, and budgets. Errors without runtime for
  500/503/409 render safely without exposing Store or idempotency internals.
- Marked `DotaMind_V3.2-6_design.md` and the overall V3.2 design as completed.

### Acceptance evidence

- Full suite without Redis environment variables: `460 passed, 14 skipped, 1 warning`.
- Full suite with local real Redis enabled: `474 passed, 1 warning`.
- Real Redis integration module: `14 passed`.
- `uv run ruff check app tests`, `uv lock --locked`, and `git diff --check` all passed.
- A manual `/metrics` check confirmed all 13 contract metric families and no forbidden run/session/request/
  tool-call/player IDs or query fields.
- A real local-browser `/debug/plan` run returned HTTP 200 and displayed Run duration, slowest node,
  Attempt grouping, tool durations, and budgets correctly. Full IDs were truncated and the browser console
  had no warnings or errors.

### Preserved boundaries

- One app process remains one Prometheus scrape target; automatic aggregation across multiple Uvicorn
  workers in one container is not promised.
- No Run Store, event bus, database, background aggregator, production fault switch, or business tool was added.
- Cancellation audit remains an in-process redacted log/Trace summary/metric only; complete Runs and Attempts
  are not persisted.
