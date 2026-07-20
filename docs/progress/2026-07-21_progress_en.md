# 2026-07-21 Progress Snapshot

## 20:30 — V3.2-2 Prompt Registry

- Completed the lightweight `agentic/prompts` module: Controller Prompt bundle, user-message
  rendering, validation-retry feedback, dormant recovery rules, and component versions/hash.
- `AgentController` freezes ToolRegistry before caching the Prompt, so Prompt rendering,
  validation, and execution share one catalog and late registration fails deterministically.
- `controller_node` writes the configured/prepared Prompt manifest to RunContext before the LLM
  call; the disabled path keeps the same audit information. The hash does not assert send or success.
- Removed unused `ContractSpec.prompt_example` and production `controller_payload()`, and removed
  the eager `planning/__init__.py` re-export to prevent import cycles.
- Added UTF-8/LF/no-BOM golden Prompt fixture plus enabled/disabled audit, freeze, hash-change,
  dormant-recovery, and fresh-import regression tests; updated V3.2-2, architecture, and technical docs.
- Verified: `ruff check .`, `pytest` (399 passed, 1 warning), `uv lock --locked`, and
  `git diff --check` pass; only existing LF/CRLF conversion notices remain.

### Unchanged boundaries

- No Recovery/Replan wiring, second Attempt, Graph edges, budget gates, public API, or persistence changes.
- Existing raw `AgentControllerResult` diagnostics remain attempt-local transient data and never enter
  the manifest, AttemptRecord, public DTO, trace, Session, or persistence boundary.

## 21:15 — Pre-merge blocker fixes

- `ToolRegistry.freeze()` now deeply seals ToolDefinition `arg_contracts`, `output_paths`, and
  `metadata`; the Controller also owns read-only Contract Registry and Sample Policy snapshots.
- A real `AgentController` and `AgentGraphRunner` must share the same Registry; a mismatch fails at
  construction. PlanService reuses an injected real Controller's sealed Registry.
- The manifest now includes `controller.history_policy.sha256`, covering only `history_window` and
  `history_max_chars`, never query, history, or Session content.
- Added semantic and version assertions for validation retry and dormant recovery rules, plus deep-freeze,
  registry-identity, and history-policy audit tests.
- Synchronized the design entrypoint, AGENTS, overall architecture, and technical architecture;
  `prompt_versions` is documented as a configured/prepared manifest.
- Verified: `ruff check .`, `pytest` (399 passed, 1 warning), `uv lock --locked`, and
  `git diff --check` pass. `git diff --check` only emits existing LF/CRLF conversion notices.
