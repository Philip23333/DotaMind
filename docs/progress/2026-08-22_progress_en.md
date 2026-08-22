# 2026-08-22 Progress Snapshot

## 01:00 — Denser Markdown match-detail presentation

### Completed

- The match-detail Answer template now uses one horizontal BP table per team: the first column is the order label and the next seven columns hold that team's pick and ban sequence.
- The player table is now `Player / Hero | K/D/A | Net Worth | Inventory | Skill Build and Talents`. Normal match details show only upgrade/talent counts, while inventory is grouped into main, backpack, neutral, and enhancement entries.
- When purchase, skill-build, or talent evidence exists, Answer receives an on-demand “Build, Skills, and Talents” section rule. It expands a target player's full purchase order, upgrades, and actual talent selections only when the current request explicitly asks for them.
- Chat remains Markdown-only: horizontal BP hero names are deterministically replaced by medium icons with no visible name; the combined hero column and main inventory use medium icons, while backpack, neutral item, and enhancement use small icons.
- Markdown tables now have a horizontal-scroll container. No icon size, structured match panel, HTML collapse, Controller routing, or data-layer contract was added.

### Verification

- Answer targeted tests: 18 passed.
- Chat `dotamind-api` targeted tests: 11 passed.

### Known boundaries

- Pure Markdown has no real collapse interaction; normal match details do not automatically render all ten players' full purchase and upgrade logs.
- There are no offline skill or talent icon assets yet, so skill-build and talent details remain evidence-backed text and Markdown tables.

## 01:05 — Full validation for Markdown match details

### Verification

- Full API suite: 655 passed, 21 skipped, 1 warning.
- Answer Prompt and targeted Ruff checks passed.
- Full Chat suite: 8 test files and 24 tests passed.
- Chat ESLint and Next.js production build passed.
- `git diff --check` passed.

## 01:43 — OpenDota player evidence field projection

### Completed

- Fixed duplication in `match_details_evidence()`: scoreboard, purchase, skill-build, and talent evidence no longer carry complete player objects independently.
- Scoreboard evidence keeps display fields and purchase/skill/talent counts; each progress evidence keeps only its own sequence plus player/hero identity fields.
- The raw `ToolResult`, two-layer EvidenceGraph structure, Answer Prompt, Chat Run, and frontend remain unchanged.

### Verification

- `tests/test_agentic_opendota_match_tools.py`: 9 passed.
- OpenDota evidence projection regression assertions and focused Ruff checks passed.
- Replayed the extractor with the persisted real three-game ToolResult: Answer messages decreased from about 3.10 MB to 1.30 MB; the raw ToolResult was unchanged.

### Known boundary

- This change does not remove `EvidenceGraph.tool_results`, so it does not change the overall raw-result-to-Answer Prompt model; it only removes cross-kind field duplication inside evidence.

## 02:10 — Controller minimization of match-detail evidence planning

### Completed

- Normal match-detail `required_evidence` is explicitly limited to the identity mapping, result, parse status, draft, and ten-player scoreboard facts it presents.
- Purchase timelines, skill builds, and talent selections become evidence obligations only when the user explicitly asks for the respective history; they are no longer planned merely because `opendota.match_details` can produce them.
- Tool Registry producible-evidence contracts, Graph execution paths, and `intent` routing semantics remain unchanged.

### Verification

- `tests/test_agent_controller.py`: 42 passed.
- Ruff passed for Controller rules, the OpenDota tool description, and targeted tests.
- `git diff --check` passed.

## 02:20 — Answer-specific Evidence View

### Completed

- Natural-language Answer no longer serializes the complete `EvidenceGraph` or raw `tool_results`; it sends only the evidence matching the required kinds, missing entries, and data quality.
- Purchase, skill-build, and talent evidence not required by the current request neither activates presentation rules nor enters the Answer Prompt.
- Raw tool results remain in execution state for audit, test observation, and later deterministic processing.

### Verification

- `tests/test_agentic_answer.py`: 20 passed.
- New regression coverage proves raw tool results and unrequested player-progress evidence stay out of Answer, while an explicit purchase request projects only purchase evidence.
- Answer-focused Ruff and `git diff --check` passed.

## 02:35 — Compact Chat history responses

### Completed

- Before persistence and the `result` event, Chat Run projects a response to status, reason/error code, Answer, and runtime summary; it no longer retains plan, raw tool results, EvidenceGraph, review, errors, or trace.
- To preserve existing Markdown hero/item icons, it derives a deduplicated lightweight `catalog_visual_entities` list from raw tool results without retaining the raw payload.
- Session reads apply the same projection to older complete `public_response` rows, so refreshes stop redownloading historical large results without a migration.

### Verification

- Focused API tests: `tests/test_chat_response.py`, `tests/test_chat_run_executor.py`, and `tests/test_chat_routes.py`: 10 passed, 1 warning.
- Chat `src/lib/dotamind-api.test.ts`: 12 passed; related ESLint passed.
- API Ruff and `git diff --check` passed.

## 02:50 — P0 full automated regression

### Verification

- Full API suite: 660 passed, 21 skipped, 1 warning.
- Full API Ruff and `git diff --check` passed.
- Full Chat suite: 8 test files and 25 tests passed.
- Chat ESLint and Next.js production build passed.

### Test closure

- Synchronized the Controller system-prompt golden fixture with the stage-1 rule text.
- Updated the complete Catalog ability-answer test to assert the JSON Answer Evidence View; its complete-ability plan already explicitly requires talent evidence, so no Answer projection boundary was loosened.

## 10:50 — Preserve Catalog visuals when reading compact Chat responses

### Completed

- `compact_chat_response()` now preserves existing `catalog_visual_entities` on already compact responses, and derives them from raw `tool_results` only for legacy responses that lack the field.
- This fixes the second compaction during session reads from dropping Markdown hero/item visual entities from newly persisted Chat Runs.

### Verification

- Added focused coverage for compact-response idempotency and for preserving visual entities when a session reads the new compact format.

## 11:05 — Correct match-detail icon semantics

### Completed

- Corrected compact Chat Catalog visual projection: records with `hero_image_path` / `item_image_path` now collect only entity-specific names, so a player's generic `name` is no longer written as a hero or item alias.
- Added frontend context protection for the combined player / hero column: the hero icon is inserted only after ` · `, so even a legacy compact response with a bad alias cannot replace the player name.
- Horizontal BP hero icons now use `lg`; player inventory retains the main-inventory label and medium icons, while backpack, neutral, and enhancement entries show small icons only. The enhancement icon remains inside parentheses without its text label.
- Removed the “skill leveling and talents” column from normal match-detail player tables. The on-demand detail rules for an explicitly requested player's skill leveling or talents remain unchanged.

### Verification

- Focused Chat icon-formatting tests: 13 passed.
- Focused API compact-response and Answer Prompt tests: 2 passed (20 deselected); Ruff passed for affected files.
- Full API suite: 662 passed, 21 skipped, 1 warning; full Chat suite: 26 passed; ESLint and the Next.js production build passed.

### Known boundaries

- Persisted legacy compact responses are not migrated. The frontend player / hero column protection prevents their polluted aliases from replacing player names; new responses use the corrected visual projection.

## 11:10 — Icon position in the combined player / hero column

### Completed

- The combined player / hero column still identifies the hero only from text after the ` · ` separator, but moves the identified hero icon to the beginning of the entire cell: “hero icon player · hero (level)”.

### Verification

- Focused Chat `dotamind-api` tests: 13 passed; ESLint and `git diff --check` passed.
