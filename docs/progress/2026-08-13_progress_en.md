# 2026-08-13 Progress Snapshot

## 01:40 — P-02 Controller Decision-Rule Deduplication

### Completed

- Kept `Conversation context rules` as the detailed source for historical-fact reuse, statistical-metric completeness, and short-follow-up inheritance.
- Kept `Decision priority` as the single decision-order authority; removed the duplicate `Decision validity invariants` and the multi-step `Final decision gate`.
- Narrowed the `Decision` section to call planning and capability boundaries after `tool_plan` is selected; `Direct-answer rules` now retain only the non-empty-answer and no-EvidenceGraph output constraints.
- Preserved the missing-metric `Completeness example` and did not change the semantic boundaries of `direct_answer`, `clarification`, `tool_plan`, or `capability_boundary`.
- Updated the Controller system-prompt golden fixture and focused prompt assertions.

### Verification

- `tests/test_agentic_prompts.py`: 12 passed.
- Controller system prompt: 39,645 characters, 606 lines, SHA-256 `da4de4875fe807fe10e5fd0002888ba2e86823d52de919dfe94a2c6fd0554e1b`.
- Full API pytest: 557 passed, 21 skipped, 1 warning (the Starlette/httpx deprecation warning).
- ToolRegistry, Contract, EvidenceGraph, and API behavior were not changed.

## 02:10 — P-09 Answer Metadata-Rule Deduplication

### Completed

- Removed the duplicate Catalog/STRATZ metadata boundary from the `pair_lane_outcome` presentation section; the global Catalog section remains the single prompt source for that boundary.
- Preserved separate lane and match result reporting, `position_ids` scope semantics, and the no-causal-inference constraint.
- Did not modify `_enforce_pair_lane_boundaries()`, EvidenceGraph, contracts, tools, or API behavior.

### Verification

- `tests/test_agentic_answer.py`: 11 passed.
- `ruff check app tests`: passed.
- `git diff --check`: passed.
- Answer prompt: 6,011 characters, SHA-256 `db8b98dbe3ce6d89b25e298cfa4b1cd4e9f63b781e0748eb19bee71fa2b1c29c`.

## 02:35 — P-08 Answer Ranking-Semantics Narrowing

### Completed

- Removed the incorrect generalization that every Hero recommendation is ranked by `wilson_rating`; Answer no longer overrides the sorting semantics already produced by tools with a generic instruction.
- Preserved lane/position `selection_mode` presentation rules and matchup/synergy's `synergy` primary ranking with `pair_wilson_rating` as a confidence co-signal.
- Did not modify ToolRegistry, tool handlers, EvidenceGraph, actual sorting, or API behavior; dynamic evidence-derived presentation constraints remain deferred to P-10.

### Verification

- `tests/test_agentic_answer.py::test_natural_language_answer_receives_catalog_rules_and_real_evidence`: 1 passed.
- `git diff --check`: passed.
- Answer prompt: 5,723 characters, SHA-256 `1e185c1e0c964ac4d515467b9a70826b3883567358d2c1e7cbe06b37e918b5c1`.

## 03:05 — P-04 Scope Tool Exceptions Moved to ToolRegistry Descriptions

### Completed

- Added each STRATZ pair-lane, matchup, synergy, lane-meta, and position-stats tool's supported or unsupported bracket, weeks_back, position, region, and game-mode semantics to its `ToolDefinition.description`.
- Removed region/mode, pair-lane, lane-meta, and player scope exceptions from Controller; retained generic cross-tool context, position-alias, and week-window guidance.
- Corrected the over-broad Controller claim that every position filter belongs in `context.position_ids`: use the selected tool's declared context or tool-call argument; `hero_position_stats` explicitly uses its `position_id` argument.
- Did not add scope metadata, Validator rules, or runtime rejection behavior; `validate_context_scope()` behavior is unchanged.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_uses_one_generic_history_first_decision_order`: 2 passed.
- `git diff --check`: passed.
- Controller prompt: 38,875 characters, 585 lines, SHA-256 `63a52b7f1aef5dabae91761a6770b05a7b0f75b1961cf651a8dc4d65559af118`.

## 03:25 — P-03 Ranking Tool Exceptions Moved to ToolRegistry Descriptions

### Completed

- Removed Controller-specific `selection_mode`, ranking, and Wilson exceptions for `lane_meta_global`, `hero_position_stats`, matchup, and synergy.
- Moved lane-meta / position-stats user-intent-to-`strong` / `popular` mappings and Sample-size policy guidance into their ToolDefinition descriptions.
- Moved matchup / synergy's `synergy` primary ranking, `pair_wilson_rating` confidence co-signal, and local Wilson z=1.96 boundary into their ToolDefinition descriptions.
- Controller now only retains the generic rule to derive selected-tool arguments, ranking semantics, and evidence interpretation from the rendered tool catalog and Sample-size policy; handler sorting, argument schemas, EvidenceGraph, Answer, and API behavior were unchanged.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_uses_one_generic_history_first_decision_order`: 2 passed.
- `git diff --check`: passed.
- Controller prompt: 38,390 characters, 560 lines, SHA-256 `c7e545208975f0b0d872a09d865cb56f7cdb14b4fd3836bce21d768afc6ba67a`.

## 04:00 — P-03 Player Tool Exceptions Moved to ToolRegistry Descriptions

### Completed

- Removed Controller-specific Steam32, profile-prerequisite, recent-match / hero-performance purpose, and `match_take` / `take` / `days` / `min_match_count` player-tool rules.
- Added identity resolution, confirmed Steam32 reference, tool-purpose, and argument-mapping semantics to the three player ToolDefinition descriptions and ArgContracts.
- Live-tested that the STRATZ schema and filtered requests accept player `regionIds: [Int]` and `gameModeIds: [Byte]`; DotaMind v1 still does not expose the capability because its string-valued QueryContext has no numeric mapping or passthrough, so Validator behavior is unchanged.
- Did not modify player handlers, QueryContext, Validator, EvidenceGraph, or API behavior.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_uses_one_generic_history_first_decision_order`: 2 passed.
- `git diff --check`: passed.
- Controller prompt: 37,855 characters, 537 lines, SHA-256 `15a30518728547d268c0f1db90dc68921605be4b518191666ea119dfed5dde0d`.

## 04:15 — Narrowed Disclosure of the Player-Filter Capability Boundary

### Completed

- Player-tool prompt text now states only that current DotaMind v1 does not support region or game-mode filters; it removes unnecessary upstream STRATZ numeric-type, mapping, and passthrough implementation details.
- Controller should disclose the capability boundary only when the user explicitly requires a region or game-mode filter, never proactively for ordinary player queries.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_uses_one_generic_history_first_decision_order`: 2 passed.
- `git diff --check`: passed.
- Controller prompt: 37,781 characters, 537 lines, SHA-256 `3888cccbd0f4da92a49d6fd03c7f24b68fa20fbe828da440814b5072d216fce3`.
