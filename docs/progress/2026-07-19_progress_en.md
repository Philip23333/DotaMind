# DotaMind Progress Snapshot: 2026-07-19

## 14:16 — Deterministic recall-answer removal

- The Controller now applies idempotent normalization to schema-valid recall
  decisions: free-form `answer` is forced to `null` for `quote_user_query`,
  `recall_entity`, and `recall_assistant_summary`, while social answers remain
  unchanged.
- `decision_validate_node` repeats normalization at Graph runtime and writes the
  decision, kind, and tool plan back to state, so custom Controllers cannot
  bypass the rule. Logs record only the response mode, never the discarded
  answer content.
- Historical `basis` validation is unchanged: unavailable Turns, mismatched
  fields, failed Turns, and missing entity matches still return a decision
  validation error. The defense-in-depth error now directly instructs recall
  decisions to use JSON `null` for `answer`.
- The Controller Prompt now distinguishes recall and social decisions: recall
  selects a non-empty basis and lets the server render from validated Turns;
  social uses an empty basis and a textual answer.
- Regression tests cover all three recall modes, preserved social answers,
  idempotence, invalid basis handling, and a single-call case where the model
  says Shadow Fiend but the stored Lina Turn deterministically wins.

### Verification

- Full API suite: `356 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- `uv run ruff check .` passed.
- `uv lock --check` passed.
- `git diff --check` passed with only the repository's existing LF/CRLF
  conversion notices.
- No live DeepSeek/STRATZ network request was run in this phase.

## 15:09 — V3.2 Agent Runtime Foundation target design

- Created the `codex/v3.2-agent-runtime-foundation` branch, froze new business
  tools, and made Agent runtime architecture the next development phase.
- Added `docs/design/DotaMind_V3.2_design.md`. The target design covers
  `RunContext`, `RunBudget`, `AttemptRecord`, bounded Recovery/Replan,
  cross-attempt tool-fingerprint reuse, `request_id` idempotency,
  `RedisSessionStore`, Prompt Registry, observability, and privacy boundaries.
- Replan is globally bounded with `max_replans=1`, a total tool-call limit, and
  a total runtime deadline. Tool/transport errors, invalid plans, Answer
  failures, and sparse results caused by explicit user constraints are not
  automatically retried.
- Delivery order is Run/Attempt/Budget, Prompt Registry, bounded Replan, request
  idempotency, Redis Session Store, then observability and fault injection.
  Business-tool development remains frozen until those gates are complete.
- Updated the root README and `docs/README.md` to distinguish implemented V3.0
  capabilities, the V3.2 target runtime, and the v2.5 constrained tool-calling
  foundation, while also documenting cumulative daily snapshots.
- This phase delivers design and documentation entry points only; target nodes,
  Redis, Replan, and idempotency are not described as implemented behavior.

### Verification

- `git diff --check` passed with only existing LF/CRLF conversion notices.
- The V3.2, V3.0, v2.5, and technical architecture documentation targets all
  exist.
- No API runtime code changed, so no API tests or live DeepSeek/STRATZ requests
  were run in this phase.

## 16:12 — V3.2-0 freeze and guardrail closure

- Updated `DotaMind_V3_node_tool_edge_inventory.md` to preserve the current
  V3.0 single-attempt graph while separately listing the V3.2 target
  `run_init`, `attempt_finalize`, `recovery`, `attempt_reset`, and
  `run_finalize` nodes; every target node is explicitly marked not implemented.
- Added an auditable map from the five Controller decisions, current Graph
  branches, terminal error precedence, Session privacy, Tool/Evidence
  contracts, and deleted legacy route to their existing characterization
  tests, establishing the behavioral baseline for later V3.2 phases.
- Tightened the default Tool Registry test from a known-tool subset assertion
  to exact equality with the frozen catalog. Adding or removing a business
  tool during V3.2 now fails the test directly.
- This phase adds no runtime state, target Graph nodes, Replan, `request_id`, or
  Redis behavior. Tests still avoid pinning exact values from volatile STRATZ
  data.

### Verification

- Focused V3.2-0 guardrails: `87 passed, 1 warning`.
- Full API suite: `356 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- `uv run ruff check .` passed.
- `uv lock --check` passed.
- `git diff --check` passed with only existing LF/CRLF conversion notices.
- No live DeepSeek/STRATZ network request was run in this phase.

## 16:50 — V3.2-1 blueprint and design-document classification

- Added `docs/design/versions/DotaMind_V3.2-1_design.md`, recording V3.2-1 as
  the single-attempt Run / Attempt / Budget implementation blueprint. It defines
  the target graph, runtime package, `RunContext`, `RunBudget`, `AttemptRecord`,
  trace, terminal finalization, the public runtime allowlist, configuration,
  work packages, test matrix, and definition of done.
- V3.2-1 keeps one Graph execution: only target `run_init_node` and
  `run_finalize_node` are introduced. Budgets are modeled and counted without
  adding new error routes; `attempt_finalize_node`, Recovery/Replan, tool
  fingerprints, `request_id`, Prompt Registry, and Redis remain in their later
  designated phases.
- Reorganized `docs/design/` into four categories: `versions/` for version
  blueprints, `architecture/` for layer/runtime architecture, `tools/` for
  tool-specific design, and `roadmaps/` for capability gaps and priorities.
  Added `docs/design/README.md` as the classification and reading-order index.
- Updated the root README, `docs/README.md`, `AGENTS.md`, archive entry point,
  internal design links, technical references, and canonical paths in code
  comments. Every local Markdown link under the moved design tree resolves,
  and current files no longer contain the old category paths; historical
  progress snapshots were left unchanged.
- This phase changed only documentation, documentation paths, and related
  comments/document-generation strings. It did not implement V3.2-1 runtime
  code or change the Tool Registry or API behavior.

### Verification

- Full API suite: `356 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- Local Markdown-link resolution under `docs/design/` passed; stale-path search
  across current non-historical files returned no matches.
- `uv run ruff check .` passed.
- `uv lock --check` passed.
- `git diff --check` passed with only existing LF/CRLF conversion notices.
- No live DeepSeek/STRATZ network request was run in this phase.
