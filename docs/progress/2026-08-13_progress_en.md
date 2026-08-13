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

## 04:35 — P-03 Catalog Tool-Chain Exceptions Moved to ToolRegistry Descriptions

### Completed

- Removed Controller-specific Catalog tool-chain rules and fixed-query examples for complete/single abilities, attributes/talents, and item definitions/recipes.
- ToolDefinition descriptions for `resolve_hero`, hero attributes/abilities/talents, `resolve_item`, and item info now carry the applicable tool-chain, resolution-reference, and required-evidence semantics.
- Controller retains the cross-tool boundary that static definitions cannot substitute for statistical evidence, and obtains Catalog tool chains from the rendered tool catalog.
- Did not add intent routing or a fixed pipeline, and did not modify Catalog handlers, ArgContracts, EvidenceGraph, Answer, or API behavior.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_declares_catalog_static_and_statistical_boundaries`: 2 passed.
- `git diff --check`: passed.
- Controller prompt: 37,516 characters, 510 lines, SHA-256 `f5c99b431247ce203a1963f76f0fec3916cacd2942497022aeabb5c3798712cc`.

## 15:43 — Recorded P-14 Catalog Tool-Description De-orchestration Target

### Completed

- Added P-14 to the prompt-responsibility review: the six Catalog ToolDefinition descriptions left by P-03 still duplicate call ordering, tool pairing, reference syntax, and cross-tool evidence requirements.
- The follow-up will narrow descriptions to capability, data scope, and local output conditions; `ArgContract` / `AcceptedRef` / `OutputPathContract` will remain the sole dependency source from which the model plans.
- If focused evaluation proves an example necessary, retain only one representative non-fixed-pipeline planning example; presentation scope such as abilities versus talents belongs to P-10/P-11.
- This update changes only the refactoring plan and progress documentation, not prompts or runtime behavior.

### Verification

- `git diff --check`: passed.

## 16:27 — P-14 Item 1: Narrowed the `resolve_hero` Tool Description

### Completed

- Removed `call once first`, downstream `dota.hero_*` instructions, and concrete plan-local reference syntax from the `resolve_hero` description; it now states only the hero-name resolution capability, Valve Catalog source, and three resolution states.
- The hero-id output path and downstream reference requirements remain expressed by `OutputPathContract`, `AcceptedRef`, and `requires_reference`; handlers, argument contracts, EvidenceGraph, and API behavior are unchanged.
- The remaining nine tools with clear P-14 over-orchestration have not yet been modified and will be reviewed individually.

### Verification

- `tests/test_agentic_prompts.py::test_system_prompt_matches_utf8_lf_golden_fixture` and `::test_controller_prompt_declares_catalog_static_and_statistical_boundaries`: 2 passed.

## 16:31 — P-14 Item 2: Narrowed the `dota.hero_attributes` Tool Description

### Completed

- Removed `Use after resolve_hero`, talent-tool pairing, and cross-tool required evidence from the `dota.hero_attributes` description; it now states only its official static attribute and combat-field capability.
- The hero-id dependency remains enforced by `ArgContract` / `AcceptedRef`; tool handlers, argument contracts, evidence production, and API behavior are unchanged.
- The remaining eight tools with clear P-14 over-orchestration have not yet been modified.

### Verification

- Two focused Controller prompt tests: 2 passed.

## 16:35 — P-14 Item 3: Narrowed the `dota.hero_abilities` Tool Description

### Completed

- Removed resolver ordering, mandatory talent-tree pairing for complete ability requests, single-ability call instructions, and cross-tool required evidence from the `dota.hero_abilities` description; it now states only its ordered non-talent ability-definition capability.
- Retained `non-talent` as a real data-scope boundary; whether talents are queried or presented is determined by the user request and later presentation scope.
- Reference contracts, tool handlers, evidence production, and API behavior are unchanged; the remaining seven tools with clear P-14 over-orchestration have not yet been modified.

### Verification

- Two focused Controller prompt tests: 2 passed.

## 16:46 — P-14 Item 4: Narrowed the `dota.hero_talent_tree` Tool Description

### Completed

- Removed resolver ordering, ability/attribute tool pairing, and shared-reference instructions from the `dota.hero_talent_tree` description; it now states only its ordered level 10/15/20/25 talent-tree capability.
- The hero-id dependency remains expressed by structured argument contracts; the model chooses whether to combine ability, attribute, and talent tools from the current request.
- Tool handlers, evidence production, and API behavior are unchanged; the remaining six tools with clear P-14 over-orchestration have not yet been modified.

### Verification

- Two focused Controller prompt tests: 2 passed.

## 16:49 — P-14 Item 5: Narrowed the `resolve_item` Tool Description

### Completed

- Removed fixed call ordering, downstream `dota.item_info` instructions, and concrete plan-local reference syntax from the `resolve_item` description.
- Retained the statement that explicit recipe wording selects recipe scope because it describes the resolver's real local handling of `recipe` / `图纸` / `配方` input.
- Structured reference contracts, the resolver handler, and API behavior are unchanged; the remaining five tools with clear P-14 over-orchestration have not yet been modified.

### Verification

- Two focused Controller prompt tests: 2 passed.

## 16:51 — P-14 Item 6: Narrowed the `dota.item_info` Tool Description

### Completed

- Removed resolver ordering and the cross-tool required-evidence combination for price/recipe questions from the `dota.item_info` description.
- Retained and rephrased conditional recipe-evidence production: recipe evidence exists only for items with component or upgrade relationships; price remains part of the item definition and does not require recipe evidence.
- Reference contracts, tool handlers, the evidence extractor, and API behavior are unchanged; the remaining four tools with clear P-14 over-orchestration have not yet been modified.

### Verification

- Two focused Controller prompt tests: 2 passed.

## 17:29 — Corrected the Ranked-Candidate Position-Filter Tool Contract

### Completed

- Renamed `stratz.filter_heroes_by_position` to `stratz.filter_ranked_heroes_by_position`, making clear that it handles matchup/synergy ranking candidates rather than acting as a generic filter over heterogeneous results.
- Narrowed the description to position-sample filtering, preservation of the original ranking, appended position match count/win rate, and the absence of reranking/composite scoring; removed concrete reference syntax and fixed-query routing.
- Added `requires_reference=True` to `candidate_rows`, which accepts only `data.candidate_rows` from the two ranking tools; Validator now rejects Planner-constructed candidate lists.
- Updated sample policy, the Controller tool name, tests, golden fixture, API README, Tool-layer documentation, and the node/tool/edge inventory; historical blueprints, roadmaps, and old progress snapshots retain the old name as historical records.
- The STRATZ join handler, `role_filtered_candidate_row` evidence, ranking semantics, and API behavior are unchanged; no compatibility alias is retained for the old tool name.

### Verification

- Focused registry, contract, STRATZ tool, sample-policy, config, and prompt tests: 12 passed.
- Covered a valid ranking reference, rejection of a literal candidate list, the single-week position join, preservation of original ranking fields/Wilson values, the policy key, and the golden prompt.
- `git diff --check`: passed.
