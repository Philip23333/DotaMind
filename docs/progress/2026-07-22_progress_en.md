# DotaMind Progress Snapshot (2026-07-22)

## 14:17 — V3.2-2 baseline commit and V3.2-3 bounded missing-evidence Recovery/Replan

### Baseline

- The lightweight V3.2-2 Prompt Registry closure was committed separately as
  `8eb0051`; its pre-commit verification result was `396 passed, 1 warning`.
- The user-maintained `AGENTS.md` modification remains unstaged and was not mixed into the
  V3.2-2 or V3.2-3 feature scope.

### V3.2-3 implementation

- The Graph now converges through `attempt_finalize -> recovery -> terminal/replan` and
  keeps only one controlled back edge, `attempt_reset -> controller`; each Run can contain
  only one or two contiguous Attempts.
- Recovery handles only reachable plain global missing-evidence gaps. Critic, tool errors,
  extractor failures, per-call evidence gaps, and Answer errors do not trigger Replan.
- Attempt 1 must retain Attempt 0's complete call prefix and plan scope, keep normalized
  `required_evidence` exactly equal, and use previously unused tools to cover every gap.
- A Run-local canonical fingerprint cache now reuses same-id successful and failed results
  without retry; the same fingerprint under a changed id returns
  `execution_budget_error`.
- A shared node-entry deadline/budget guard was added, plus another deadline/tool-budget
  check before every unreused handler that passed pre-dispatch validation. Attempt 1 checks
  deadline again before startup, while closure nodes remain available after deadline.
- `AttemptRecord.recovery_code` describes only why the current Attempt started: Attempt 0 is
  always null, an actually started Attempt 1 is `missing_evidence`, and finalized historical
  Attempts are never rewritten.
- Public runtime now accepts one or two Attempts and adds `attempts[].recovery_code` plus
  `tool_call_statuses[].reused`; feedback, baseline, fingerprints, and cache remain internal
  transient state.
- `controller.recovery_rules=v1` is now in the Prompt manifest. Recovery messages reuse the
  original system prompt, original user envelope, and full baseline decision, while the
  V3.2-2 system golden/hash remains unchanged.

### Documentation and verification

- Added `docs/design/versions/DotaMind_V3.2-3_design.md` and aligned the V3.2 master design,
  design index, current architecture, node inventory, and API documentation.
- Added synthetic Registry/FakeController/FakeClock tests covering successful recovery,
  second-attempt gaps, no producer, all three Replan budgets, prefix invariants,
  success/failure reuse, duplicate handling, per-handler budget/deadline, Attempt startup
  deadline, public fields, and privacy boundaries.
- Verified: `uv run ruff check .` passes; full `uv run pytest -q` reports
  `422 passed, 1 warning`; `uv lock --locked` passes; `git diff --check` passes with only
  existing Windows LF/CRLF notices.

### Explicitly deferred

- Critic Recovery, tool retry/fallback, more than one Replan, cross-Run cache, request
  idempotency, Redis, per-tool TraceEvents, metrics, and in-flight forced cancellation remain
  unimplemented.
