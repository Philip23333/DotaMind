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

## 11:25 — New-chat TI shortcut and welcome screen

### Completed

- The “本届TI最新战况” shortcut is now always visible while a new thread is idle and no longer depends on input focus. It is a long, borderless suggestion using the same background as the composer.
- Updated welcome copy to “🔥TI正在火热进行中！” and “🤖可快捷查询赛程、比赛详情与选手数据等”.
- Extended startup-overlay fade-out to 360ms, added a welcome-content fade-in, and reduced the background Dota 2 mark opacity from 10% to 4%.

### Verification

- Full Chat suite: 26 passed; ESLint, the Next.js production build, and `git diff --check` passed.

## 11:40 — New-chat motion and shortcut refinements

### Completed

- Moved automatic startup-overlay dismissal forward from 1400ms to 700ms and shortened its fade-out from 360ms to 180ms.
- Joined the TI shortcut to the composer with no gap, made it square-cornered with a slight floating shadow, and set it to 55% opacity until hover restores full opacity.
- Removed the robot emoji from the welcome subtitle and updated it to “快捷查询赛程、比赛详情与选手数据等”.

### Verification

- Full Chat suite: 26 passed; ESLint and the Next.js production build passed.

## 11:50 — TI shortcut hover state

### Completed

- The shortcut now has a transparent background and muted text by default. Hover or keyboard focus restores full text opacity, uses the composer-matching background, and adds a floating shadow.
- Restored a 5px gap and small rounded corners between the shortcut and composer.

### Verification

- Full Chat suite: 26 passed; ESLint and `git diff --check` passed.

## 12:00 — P0 downstream player-progress extraction for match details

### Completed

- `opendota.match_details` is now limited to core evidence: result, ten-player scoreboard, parse status, and draft; full `data.matches` remains available for audit and downstream processing.
- Added deterministic `dota.extract_match_player_progress`, which accepts only the `opendota.match_details.data.matches` reference, performs no network request, and projects purchase order, skill upgrades, or talent choices from explicit `player_query` and `aspects`.
- The transform emits only requested progress evidence; ordinary match details no longer carry the three event-level progress kinds automatically. Missing or multiply matched players return a direct tool error instead of a guess.
- Synchronized Controller planning rules, registry contracts, Answer Evidence boundaries, and architecture/tool/node inventory docs; Checkpoint, raw ToolResult, and Chat persistence boundaries remain unchanged.

### Verification

- Focused OpenDota tool, registry, and Prompt tests: 51 passed.
- Ruff passed for the transform, tests, and registry files.

### Known boundaries

- The transform currently supports only the three fixed progress aspects; it does not provide generic JSONPath, free-field filtering, or a Checkpoint adapter. Future domain transforms should reuse the existing ToolRegistry and reference contracts.

## 12:30 — Bound the Answer-only evidence view

### Completed

- Kept `effective_required_evidence` as the complete runtime/Critic obligation, including per-call tool `mandatory_evidence` validation.
- `answer_node` now creates a shallow Answer-only Graph view with `required_evidence` set to `global_required_evidence`; the original effective Graph is unchanged and no large ToolResult data is copied.
- Controller match-detail rules now require focused purchase, skill, or talent requests to list only the corresponding progress evidence in `plan.required_evidence`; `opendota.match_details` mandatory core evidence enters the Answer view only when the user explicitly asks for result, BP, or scoreboard data.

### Verification

- Focused Answer, Graph, Controller, and Prompt tests: 87 passed.
- Added Answer-node regression coverage proving global evidence is used while the original effective Graph remains unchanged.

## 13:20 — Global Answer evidence-view invariant

### Completed

- Generalized the Answer-node regression into a domain-independent invariant: evidence introduced only by a tool's `mandatory_evidence`, and absent from the Controller/contract Answer-visible obligation, must not reach natural-language Answer messages.
- Formally defined `global_required_evidence` as the Answer-visible obligation and `effective_required_evidence` as the runtime/Critic validation obligation in the Evidence and technical architecture documents.

### Verification

- Focused Graph coverage exercises the local Answer view, preservation of the original validation Graph, and the natural-language renderer's generic whitelist projection.

## 14:04 — Tighter default purchase presentation

### Completed

- Purchase events now include the read-only Catalog `item_price`; the raw purchase order and events are retained.
- For an explicit item-build request, negative-time purchases are aggregated in first-seen order as **出门装**; repeated items render as `× N` and appear above final inventory.
- The subsequent purchase-order table includes only non-negative-time items whose Catalog price is at least 150 gold; unresolved or lower-priced items are omitted by default without guessing a price.
- Ordinary match details and the existing final-inventory, skill-build, and talent-presentation boundaries are unchanged.

### Verification

- `tests/test_agentic_opendota_match_tools.py` and `tests/test_agentic_answer.py`: 30 passed.
- Ruff for changed files and `git diff --check` passed.

## 14:59 — Aggregate player post-match progress evidence

### Completed

- `dota.extract_match_player_progress` no longer accepts `aspects`; when the user explicitly asks for item build, purchase order, skill order, or talents, it returns the complete `player_match_progress` package for the exact player and each parsed game.
- The aggregate package keeps only player/hero identity, level, final inventory configuration (main, backpack, neutral item and enhancement), purchase timeline, ability upgrades, and talent selections; it excludes the full team, draft, raw OpenDota payload, and `neutral_history`.
- The transform emits one `player_match_progress` evidence item per game. Ordinary match details still do not extract it automatically, and cross-Run Match Artifact reuse remains out of scope.
- Controller, Answer, ToolRegistry, the prompt golden fixture, architecture documents, and README were synchronized; focused requests continue using the Answer-only evidence view and do not display upstream core match evidence.

### Verification

- API focused suite: `122 passed` (OpenDota transform, Registry, Controller, Answer, Graph, and prompt fixture).
- Ruff for changed files and `git diff --check` passed.

### Known boundaries

- 150 gold is the current default display threshold. Filtering does not alter the raw ToolResult or reduce the retained scope of explicit audit data.

## 14:28 — Skill-build and talent mapping refinement

### Completed

- OpenDota ability ID `730` is normalized as the shared `special_bonus_attributes` upgrade with the display name **全属性 +2**, rather than a missing Catalog ability.
- The skill-upgrade array's ordering field is now `upgrade_index`, not a claimed player level. The first through fourth mechanically evidenced talent selections map deterministically to player levels 10/15/20/25 while retaining their raw ordering index for audit.
- Answer renders the skill build as a horizontal arrow sequence in first-appearance order with final ranks, rather than a per-level Markdown table; talent choices appear only at 10/15/20/25.
- Default item-build presentation and ordinary match-detail boundaries are unchanged.

### Verification

- `tests/test_agentic_opendota_match_tools.py`, `tests/test_opendota_domains.py`, and `tests/test_agentic_answer.py`: 36 passed.
- Ruff for changed files and `git diff --check` passed.

## 17:46 — Deterministic purchase-display projection

### Completed

- Removed the previous price field, price threshold, and Prompt-side low-price omission rules; purchase events, `player_match_progress`, and the Answer Prompt no longer carry price-filter semantics.
- Normalized OpenDota purchase events now include the canonical Catalog `item_internal_name` and `is_terminal_item`; the raw purchase timeline remains in the upstream ToolResult for audit.
- `dota.extract_match_player_progress` emits `purchase_display`: negative-time events aggregate into starting items, non-negative events are filtered only by `POST_START_BUILD_EXCLUDED_ITEM_INTERNAL_NAMES` for Tango, Clarity, observer/sentry wards, and teleport scrolls, terminal items receive completion times, and unfinished trailing segments remain visible.
- Answer renders the build path horizontally with medium Catalog icons and `→` instead of a purchase-order table; Chat reuses its existing inline Markdown icon support.

### Verification

- API focused tests: 31 passed; Chat focused tests: 14 passed.
- Ruff for changed files and `git diff --check` passed.

### Known boundaries

- The exclusion set applies only to the post-start display projection; negative-time starting items bypass it.
- Raw purchase events remain available for audit, while Answer receives the deterministic display projection by default; unresolved post-start events without Catalog identity/image are counted as omitted.

## 17:52 — Final regression

### Verification

- Full API suite: `665 passed, 21 skipped` (one existing Starlette deprecation warning).
- Full Chat suite: `27 passed`.
- Final Answer/Prompt/OpenDota focused regression: `47 passed`; Ruff for changed files and `git diff --check` passed.

## 18:21 — Player-build horizontal layout and icon rendering

### Completed

- Removed the pseudo image URL from the Answer build-path example. Answer now emits only a single horizontal item-name-and-`→` path and no longer asks the model to generate Markdown images.
- Chat deterministically decorates equipment names as `md` Catalog icons only inside the explicit `出装、加点与天赋` player-progress subsection; this covers starting items, final equipment, and build paths without changing other inventory-table icon sizes. Stored historical answers are not migrated or reformatted.
- Each build-path segment remains horizontal; the purchase-order table and one-item-per-line layout are not restored.

### Verification

- API `tests/test_agentic_answer.py`: 20 passed; relevant Ruff check passed.
- Chat `src/lib/dotamind-api.test.ts`: 15 passed; relevant ESLint check passed.

## 19:05 — Local skill and team-logo assets

### Completed

- Valve Catalog image sync now covers heroes, non-recipe items, and ordinary abilities; ability
  paths use `/api/v1/assets/dota/abilities/{id}.png`. Skill evidence adds `ability_image_path`
  only for resolved non-talent, non-item, non-innate abilities; talents, attribute bonuses, and unresolved
  skills remain null.
- Added PandaScore Dota 2 team pagination, allowlisted image downloads, concurrent staging,
  manifest atomic replacement, and the read-only `PandaScoreTeamAssetRepository`. A Fixture adds
  `team_image_path` only on a local hit; CDN URLs are not written into ToolResult or Chat.
- Mounted `/api/v1/assets/esports`; Chat recognizes local skill/team entities, decorates skill
  sequences with `md` icons, keeps talents and attribute bonuses as plain text, and uses ordinary
  text/table icon sizes for team logos.
- Removed price-filter semantics from the Prompt, progress evidence, and purchase events; only
  `POST_START_BUILD_EXCLUDED_ITEM_INTERNAL_NAMES` remains, and negative-time starting items bypass it.

### Verification

- Full API suite: `673 passed, 21 skipped` (one existing Starlette deprecation warning); full Ruff passed.
- Full Chat suite: `30 passed`; ESLint passed.
- Valve `--images-only` was executed and strictly failed when upstream returned HTTP 404 for
  `ability 1166 (axe_one_man_army)`; staging/atomic replacement preserved the existing image
  directory and left no backup directory.

### Known boundaries

- Valve ordinary-ability sync intentionally remains strict; the upstream Catalog must provide a
  valid image before a complete skill snapshot can be generated. No partial skill images were committed.
- The PandaScore team manifest must be generated in an environment with a valid API token using
  `python scripts/sync_pandascore_team_assets.py --workers 8`; a missing or corrupt local manifest
  does not block schedule or match answers.

## 19:20 — PandaScore public-Fixture redaction

### Completed

- `_fixture_data()` now always removes upstream `opponent.image_url`, retaining only
  `team_image_path` on a local manifest hit. With no repository, no logo, or a historical Fixture,
  PandaScore CDN URLs do not reach Chat or the browser.

### Verification

- Full API suite: `673 passed, 21 skipped` (one existing Starlette deprecation warning); team-asset
  focused tests: 6 passed; Ruff and `git diff --check` passed.

## 20:18 — Exclude innate hero abilities without icons

### Completed

- Valve skill-image sync, OpenDota ability references, and hero-ability serialization now consistently exclude `is_innate`; innate abilities retain evidence-backed text and no longer receive local image paths.
- Fixed `axe_one_man_army` (ability 1166) being treated as an ordinary ability and requesting a CDN image; its 404 path no longer blocks a complete skill-image snapshot.
- Restored the sync-test fixture to an ordinary ability and added regression coverage that innate abilities are not downloaded.

### Verification

- `tests/test_dota_catalog_sync.py`, `tests/test_agentic_opendota_match_tools.py`, and `tests/test_agentic_registry.py`: 87 passed.
- Related Ruff and `git diff --check` passed.

## 20:23 — Local icon snapshots synchronized

### Completed

- Ran `sync_game_data.py --images-only --workers 8`, generating 607 ordinary skill images; innate hero abilities are absent from the snapshot, and `ability 1166` no longer requests a nonexistent image.
- Ran `sync_pandascore_team_assets.py --workers 8`, atomically generating the PandaScore team manifest and 1,377 local logos; 1,119 teams without logos were skipped under the non-blocking rule and there were zero download failures.

### Verification

- Confirmed that `app/data/catalog/images/abilities/1166.png` is absent and that `app/data/esports/teams/manifest.json` records 1,377 local resource paths.

## 20:30 — PandaScore team snapshot narrowed to recent Series

### Completed

- Team-logo sync no longer reads the full `/dota2/teams` list; by default it selects the ten newest Dota 2 Series by `begin_at` and de-duplicates teams from each Series' upcoming/running/past Fixture opponents.
- Added `--series-limit`; a successful sync still atomically replaces the entire team directory, removing the stale images from the previous full synchronization.
- The actual ten-Series synchronization generated 60 local logos; seven teams without logos were skipped under the non-blocking rule and there were zero download failures.

### Verification

- `tests/test_pandascore_team_assets.py`: 7 passed; related Ruff passed.
- The manifest records the selected ten Series IDs and 60 local assets.

## 21:11 — Build terminal-time and icon presentation consolidation

### Completed

- `is_terminal_item` now derives from Valve Catalog recipe edges: only non-recipe items with no current purchasable upgrade target are terminal; it no longer incorrectly reads a recipe scroll's own `upgrade_item_ids`.
- An explicit exclusion covers the historical Trident target that the Catalog still marks purchasable but which is not a current standard-shop item. Kaya and Sange remains terminal, while Boots of Speed, Magic Stick, and Magic Wand no longer receive completion times.
- The player-progress heading is now the combined H2 “出装、加点与天赋 · player · hero (level)”. Chat renders starting and final equipment as large icon-only assets while retaining quantities and main/backpack/neutral grouping labels; build paths retain named medium icons.

### Verification

- API: `tests/test_agentic_opendota_match_tools.py` and `tests/test_agentic_answer.py`, 31 passed.
- Chat: `src/lib/dotamind-api.test.ts`, 17 passed.

## 21:47 — Build and skill-sequence presentation refinement

### Completed

- `purchase_display.starting_items` no longer aggregates duplicate items or carries counts; every negative-time purchase remains flattened in original order, so starting equipment no longer renders `× N`.
- Chat removes the main/backpack/neutral/enhancement text from final inventory: main inventory renders only large icons, while backpack, neutral item, and enhancement render only medium icons. Starting equipment remains large icon-only.
- Answer now renders skill upgrades in `upgrade_index` order as every non-talent event. Ordinary skills and every `全属性 +2` occurrence remain separate instead of rank-grouped; talents remain in the talent-selection section only.

### Verification

- API: `tests/test_agentic_opendota_match_tools.py` and `tests/test_agentic_answer.py`, 31 passed.
- Chat: `src/lib/dotamind-api.test.ts`, 17 passed.

## 21:50 — Key build milestone times

### Completed

- Added the presentation-only `BUILD_MILESTONE_ITEM_INTERNAL_NAMES` allowlist. Terminal items and listed key intermediate items receive `milestone_at_seconds` and end their current build-path segment, without calling a key purchase a terminal completion.
- The list includes Blink Dagger, Maelstrom, Boots of Travel (including level two), Force Staff, Eul's Scepter of Divinity, Helm of the Dominator, Rod of Atos, Ghost Scepter, Vanguard, Mekansm, Echo Sabre, Diffusal Blade, Witch Blade, Arcane Boots, and Specialist's Array.
- The raw purchase timeline, terminal-item determination, and consumable filter boundary are unchanged; the allowlist affects only `purchase_display` time markers and segmentation.

### Verification

- Tool-layer basic test only: `tests/test_agentic_opendota_match_tools.py`, 11 passed.

## 21:52 — Key milestones do not split paths

### Correction

- A key intermediate item's `milestone_at_seconds` controls only its displayed time; it does not end a `→` build-path segment. Only terminal items continue to end the current segment.
- The allowlist still affects only time presentation and does not alter raw purchases, terminal determination, or path segmentation rules.

### Verification

- Tool-layer basic test only: `tests/test_agentic_opendota_match_tools.py`, 11 passed.
