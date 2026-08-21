# 2026-08-14 Progress Snapshot

## 00:08 — P-10 Dynamic Answer presentation-rule assembly

### Completed

- Split the single natural-language Answer system prompt into core evidence rules and focused sections for Catalog attributes, abilities, talents, items, STRATZ metadata boundaries, weekly trends, pair-lane results, rankings, and daily trends.
- The renderer combines required and actual evidence kinds and uses STRATZ sources from EvidenceGraph / ToolResult to activate the cross-source metadata boundary; rule selection does not inspect `intent`, tool names, or natural-language keywords.
- Complete-list versus named single-ability granularity remains an Answer LLM judgment based on `current_query` / `reconstructed_goal`; talent-table rules are included only when `hero_talent_tree` is present or required.
- Mixed Catalog and STRATZ answers must attribute source metadata locally to the relevant facts; statistics-only answers must not present Catalog patch/generated_at from identity resolution as a statistics version.
- Added no `presentation_scope`, output contract, intent branch, or deterministic Catalog Renderer; Answer node, Synthesizer interface, EvidenceGraph, tools, and API behavior are unchanged.

### Verification

- `tests/test_agentic_answer.py`: 16 passed.
- `tests/test_agentic_prompts.py`, `tests/test_agentic_runtime.py`, and `tests/test_agentic_recovery.py`: 68 passed.
- Ruff passed for the affected files.
- Representative system prompts: core 432 chars, attributes 891, ability 2,065, ability+talent 2,446, item recipe 1,741; with the STRATZ source boundary, pair-lane 2,249, synergy 1,766, and daily trend 1,251 chars.

## 01:23 — P-07 Remove pair-lane keyword post-processing

### Completed

- Removed the `_enforce_pair_lane_boundaries()` call and function; natural-language Answer output is now only trimmed instead of deleting full lines that contain terms such as mid/late game, comeback, or Catalog patch values.
- Preserved the evidence-specific pair-lane, STRATZ/Catalog attribution, and unsupported-causal-conclusion rules; they enter the system prompt only for relevant EvidenceGraphs.
- Fixed possible deletion of correct negative statements and valid Catalog definition sections in mixed Catalog + STRATZ answers; streamed deltas and the final summary no longer follow different content-rewrite paths.
- EvidenceGraph, Controller, tools, Critic, output schema, and API behavior are unchanged; natural-language fact auditing remains P-12/P-06 work.

### Verification

- Focused Answer, runtime, and recovery tests: 72 passed.
- Ruff passed for the affected files.

## 01:26 — P-12 Disallow unsupported hypotheses

### Completed

- Removed the pair-lane Prompt exception that allowed an interpretation without explicit evidence when labeled as a hypothesis; EvidenceGraph is now the uniform factual boundary for natural-language Answer.
- Without evidence, Answer may report only the statistical difference and must not add gameplay interpretations or hypotheses; causal/gameplay explanations require explicit EvidenceGraph support and attribution to that evidence.
- Added no hypothesis schema, Critic text classifier, keyword filter, or deterministic Answer route; any future strategy-simulation capability should use a separate verifiable contract.
- Natural-language `summary` still lacks per-claim evidence refs; that issue moves to P-06.

### Verification

- Focused Answer, prompt, runtime, and recovery tests: 84 passed.
- Ruff passed for the affected files.

## 01:31 — P-06 Accept the sentence-level audit boundary

### Decision

- Marked P-06 as "no implementation (accepted risk)": natural-language Answer does not provide per-sentence claims/evidence refs, and Critic does not claim to verify every number, subject, or source.
- No real evaluation currently shows stable transcription errors after the model receives a clear EvidenceGraph; structured claims, a second LLM Critic, domain-field parsing, and streaming compatibility layers are not justified for this low-probability model-quality risk.
- If reproducible transcription errors appear, first evaluate model replacement/upgrades, Prompt length, EvidenceGraph structure, and generation settings; reopen contract-level auditing only if those measures are insufficient.
- This item updates only the design decision and documentation; no code or tests changed.
