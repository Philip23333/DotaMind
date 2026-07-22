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

## 21:40 — V3.2-2 lightweight revision

- Removed the defensive layer outside the phase boundary: `ToolRegistry.freeze()` now only closes
  registration, retaining the invariant that `register()` fails after Controller construction without
  copying or deeply sealing ToolDefinition contents.
- Removed Contract Registry / Sample Policy snapshots, Graph Registry identity validation, and the
  PlanService branch that reused a real injected Controller's Registry. The default production path
  still registers and validates tools before constructing Controller, GraphRunner, and executor with
  the same Registry.
- Removed `controller.history_policy.sha256`; the manifest now records only the system-prompt SHA-256
  and connected renderer versions. Dynamic query, history, and retry feedback remain outside it.
- Removed the corresponding deep-freeze, snapshot, Registry-identity, and history-policy tests while
  retaining golden, enabled/disabled manifest, sent-system hash, post-freeze registration rejection,
  catalog/contract/sample-policy hash-change, and fresh-import coverage.
- This section supersedes the deep-freeze, snapshot, identity-check, and history-policy-hash details in
  the 21:15 entry. Recovery/Replan, Graph/API/Attempt, and persistence boundaries remain unchanged.
- Verified: `ruff check .`, `pytest` (395 passed, 1 warning), `uv lock --locked`, and
  `git diff --check` pass.

## 22:00 — V3.2-2 lightweight acceptance closure

- Tightened the V3.2-2 and Tool-layer documentation: only the default PlanService assembly is
  constrained to have Controller, GraphRunner, and ToolExecutor read the same Registry instance with
  registration closed; it is no longer described as an immutable collection.
- Made the non-goals explicit: no deep ToolDefinition freeze, Contract Registry/Sample Policy snapshots,
  arbitrary dependency-injection identity validation, or history-policy hash.
- Added default `PlanService()` assembly coverage asserting that Controller, Runner, and Executor all use
  `service.registry`; it does not expand into identity defenses for arbitrary injected objects.
- Verified: `ruff check .`, `tests/test_plan_service.py` (11 passed), the full `pytest` suite
  (396 passed, 1 warning), and `uv lock --locked` pass.
