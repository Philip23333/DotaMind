# 2026-08-21 Progress Snapshot

## 01:14 — TI latest-status Answer output example

### Completed

- Added a TI latest-status Markdown presentation example to the natural-language Answer Prompt selected for competition/match evidence, fixing the section order for overview, current matches, key results, upcoming schedule, and data notes.
- Corrected the key-match table to three aligned columns, `Matchup | Score | Result`, so teams, series scores, and advancement outcomes occupy their proper columns.
- Marked the example as presentation-only: teams, scores, dates, times, stages, region, series format, and source claims must not be reused without support from the current EvidenceGraph, and an unknown edition must not output a literal `X`.
- The example remains dynamically selected from evidence kinds/source without reading `intent`, tool names, or keywords, and does not alter Controller planning, tool chains, output contracts, or evidence obligations.

### Verification

- Answer focused tests: 18 passed.
- API full suite: 622 passed, 21 skipped, 1 warning.
- `uv run --project apps/api ruff check apps/api/app/agentic/prompts/answer.py apps/api/tests/test_agentic_answer.py` passed.

### Known boundaries

- This remains an LLM presentation example under `natural_language_answer`, not a deterministic `tournament_schedule_report` structured contract; sections are generated only when supported by current evidence.

## 09:30 — PandaScore Match List newest-first ordering

### Completed

- `pandascore.list_matches` now pushes `sort=-scheduled_at` to each PandaScore `upcoming`, `running`, and `past` Fixture request, and keeps descending schedule-time order after merging and deduplicating them.
- The default `limit=20` is now also pushed down as `page[size]=20` per status request, then returns the newest 20 Fixtures across statuses; the upstream default ascending first page can no longer prioritize the earliest group-stage matches.
- Updated the tool description, PandaScore API inventory, and Tool-layer contract to state the newest-first default.

### Verification

- Live-tested with the project-configured PandaScore token: `GET /dota2/matches/past?filter[serie_id]=10828&sort=-scheduled_at&page[size]=20` returned 20 rows, from `2026-08-20T13:25:00Z` first to `2026-08-15T05:20:00Z` last.
- Verified through the actual `pandascore.list_matches` handler that the default output is exactly 20 rows; the latest three schedules for the same Series were `2026-08-23T05:00:00Z`, `2026-08-23T02:00:00Z`, and `2026-08-22T11:00:00Z`.
- Focused Fixture-list ordering/request-parameter and Agentic PandaScore tool tests: 21 passed.
- `ruff check` passed for the PandaScore implementation and test files touched by this change.

### Known boundaries

- The default set still includes future, running, and finished Fixtures. “Newest” is descending `scheduled_at` (falling back to `begin_at`), not a finished-result-only filter. A caller that needs only results should pass `statuses=["finished"]`.

## 10:00 — Cross-tool dict-reference planning validation

### Completed

- Fixed the planning-time reference placeholder: a `dict` argument is no longer simulated as `{}`, but as a non-empty typed placeholder dictionary.
- `dota.resolve_valve_matches.competition` can therefore legally reference `pandascore.resolve_competition.data.competition` without being falsely rejected by `Field(min_length=1)` before any real tool call.
- Added a regression assertion for the complete PandaScore Competition -> Game context -> Valve Match Resolution plan-validation chain.

### Verification

- Minimal focused test: `tests/test_agentic_match_resolution_tools.py`, 3 passed.

### Known boundaries

- This only corrects the planning-time static type placeholder. Runtime execution still requires the upstream tool to return a real, non-empty competition context; reference-resolution and upstream execution failures remain explicit through the existing error path.

## 10:30 — Cross-source Valve mapping without OpenDota Series ID

### Completed

- `dota.resolve_valve_matches` no longer treats OpenDota `series_id` or its derived game position as a hard filter.
- A unique mapping still requires the target league, unordered team IDs, start time within 1800 seconds, duration within 5 seconds, and winner consistency when available; multiple candidates still return `ambiguous_match`, never a nearest-time selection.
- Added coverage for the live-data shape where an OpenDota match omits `series_id` but the remaining strong signals identify one record, and updated the cross-source mapping technical contract.

### Verification

- Minimal focused test: `tests/test_cross_source_match_resolution.py`, 15 passed.
- Live-tested with the two real PandaScore game contexts for Iron Wing vs Team Spirit, resolving Valve `8955197224` and `8955247801`.

### Known boundaries

- When upstream mapping has no unique Valve ID, the graph execution layer still needs an explicit short-circuit and capability-boundary result before Match Details. Controller Prompt wording cannot reliably solve that data-dependent condition.

## 11:00 — OpenDota match hero and item Catalog names

### Completed

- `opendota.match_details` player scoreboards now retain raw hero/item IDs while deterministically adding Valve Catalog English and Chinese names for heroes, six main inventory slots, backpack, neutral items, and draft heroes.
- Empty slots remain empty; hero or item IDs absent from the Catalog are explicitly marked `not_found` and never receive a guessed name.
- Scoreboard and draft evidence now carries Catalog snapshot metadata; the Answer Prompt may display names only from evidence `*_name_en` / `*_name_zh` fields and must not translate or infer them from IDs.

### Verification

- Minimal focused test: `tests/test_agentic_opendota_match_tools.py`, 4 passed.
- `ruff check` passed for the files touched by this change.

### Known boundaries

- Names come from the committed Valve Catalog snapshot. A new ID absent from that snapshot remains unnamed until the Catalog is regenerated through the repository script.

## 15:00 — Offline hero and item images

### Completed

- Committed 127 hero images and 414 non-recipe item images under `apps/api/app/data/catalog/images/`, 541 files totaling about 21.1 MiB for the current Catalog.
- Added `--images-only` to `sync_game_data.py`. It downloads from Valve's official React image CDN into a temporary directory and replaces the local image directory only after all requests succeed; failures do not overwrite the previous directory first.
- API now serves local assets at `/api/v1/assets/dota/heroes/{id}.png` and `/api/v1/assets/dota/items/{id}.png`.
- `resolve_hero`, `dota.hero_attributes`, `resolve_item`, and `dota.item_info` entity results and their identity evidence now carry deterministic `image_path` values.
- Chat reads `image_path` from `tool_results`, deduplicates images, and appends Markdown image references using the API base URL; the model does not generate image URLs.

### Verification

- Image download completed: 541 files, 22,121,037 bytes total.
- Catalog, sync, graph, and tool-chain focused tests: 71 passed; image route and resolver tests: 2 passed.
- Chat image-formatting tests: 3 passed.
- Targeted API Ruff checks passed; the sync script compiled successfully.

### Known boundaries

- This phase does not cache skill, talent, innate-skill, match-panel, team, or league images.
- Images do not receive SHA, dimension, PNG-structure, or startup-scan validation; sync only requires a successful HTTP request with a non-empty response body.

## 15:30 — Inline hero and item heading thumbnails

### Completed

- Chat no longer appends a standalone “相关图片” image section at the end of an answer.
- `formatPlanResponse()` extracts local `image_path` values from `tool_results.data.hero` / `data.item`, deduplicates them, and decorates only the first Markdown heading containing an entity name.
- Name matching prefers Chinese, then English and internal names; the Markdown image is inserted immediately before the matched name, while an answer with no matching heading remains unchanged.
- The Markdown `img` renderer adds the 28×28 rounded, cropped, vertically aligned style only for `/api/v1/assets/dota/` images; ordinary Markdown images are unaffected.

### Verification

- Full Chat test suite: 16 passed.
- ESLint: passed.
- Next.js production build: passed.

### Known boundaries

- Only hero/item query headings are decorated; repeated body names, match panels, teams, skills, and leagues are not processed.

## 15:30 — TI date-grouped schedule output template

### Completed

- Replaced the Answer Prompt's TI latest-status example with a UTC-date-first layout, rather than primarily grouping fixtures by bracket or stage across dates.
- The fixed section order is: current date (running → finished → upcoming) → future dates in ascending order → historical dates in descending order. Each UTC date is rendered at most once, with empty dates and subsections omitted.
- The current date is labelled "today" only when evidence establishes it; otherwise the exact date is shown. The example remains presentation-only, and its placeholder teams, scores, and schedule must not fill gaps in the EvidenceGraph.

### Verification

- Minimal focused Prompt test: `tests/test_agentic_answer.py -k ti_status_example`, 1 passed (17 deselected).
- `ruff check` passed for the Prompt and test files touched by this change.

### Known boundaries

- This template only constrains the LLM presentation structure; it is still not a deterministic tournament-schedule output contract. The "today" label and date membership rely on time information supplied by runtime evidence.

## 16:00 — Per-game BP and secondary data note for match details

### Completed

- Added a dedicated match-detail presentation example for natural-language Answers with match-result, cross-source mapping, scoreboard, or draft evidence. Tournament-status and match-detail templates are now selected by their respective evidence kinds, so match details do not receive the TI schedule example.
- Each game now follows the fixed order: compact duration/kills/winner summary → two full BP tables separated by team → both player scoreboards. Each team's BP table expands Ban 1–7 and Pick 1–5; rows without real actions are omitted and no placeholder heroes are added.
- A Valve Match ID appears in parentheses after the game title only when mapped. The final data note is a visually secondary blockquote + `<sub>` footnote, without CSS or HTML color styling.
- Updated the Answer architecture document to state that the match-detail template only constrains presentation and does not expand the EvidenceGraph fact boundary.

### Verification

- Minimal focused Prompt test: `tests/test_agentic_answer.py -k ti_status_example`, 1 passed (17 deselected).
- `ruff check` passed for the Prompt and test files touched by this change.

### Known boundaries

- The `<sub>` size reduction depends on the eventual Markdown renderer. If unsupported, the blockquote and its content remain, with source and fact constraints unchanged.

## 15:45 — Blink Dagger “跳刀” alias

### Completed

- Added the common Chinese alias “跳刀” to the Valve Catalog's `item_blink`; `resolve_item("跳刀")` can resolve Blink Dagger (Item ID 1).
- The sync script retains this alias rule so a later Catalog refresh will not overwrite it.

### Verification

- Tests were not run, as requested.

### Known boundaries

- This change adds only the explicit “跳刀” alias and does not introduce a general item-synonym dictionary.

## 16:00 — OpenDota match-entity images and context-sized thumbnails

### Completed

- `opendota.match_details` now carries deterministic `hero_image_path` / `item_image_path` values for player heroes, BP heroes, final inventory, backpack, and neutral-item details; missing IDs and Catalog misses use `null`.
- Chat recursively reads Catalog entities from `tool_results[*].data`, still accepts only local `/api/v1/assets/dota/.../*.png` paths, and deduplicates entity metadata by path.
- Replaced the old first-heading-only decoration with controlled Markdown image fragments selected by context: `lg` (56×56) for a single-entity H1, `md` (32×32) for ordinary lists/narrative, and `sm` (20×20) for tables and BP/roster/pick/ban sections. The same entity may render in separate player rows or games.
- Fenced code, inline code, Markdown links, and table separator rows are not rewritten. No standalone “相关图片” section is appended; image URLs remain driven by structured backend fields.
- The Markdown `img` renderer removes the `#dota-size=sm|md|lg` fragment and applies the three size styles only to local Catalog images; ordinary Markdown images keep their existing behavior.

### Verification

- Focused API OpenDota tests: 5 passed.
- Focused Chat image-formatting tests: 8 passed.
- Chat ESLint: passed.

### Known boundaries

- This change does not handle skill, team, league, or user-message images, and does not change image caching, static routes, tool registration, Evidence kinds, or Prompt contracts.

## 16:15 — Fix player-column image injection

### Completed

- Corrected Chat entity extraction: `hero_image_path` matches only `hero_name_zh` / `hero_name_en`, and `item_image_path` only item-specific names; a player record's `name` is no longer treated as a hero alias.
- Local Catalog images now use `1px` horizontal margins and no text-space between the Markdown image and entity name, avoiding extra visual gaps.

### Verification

- Added a frontend regression test that ensures a player name is not replaced by a hero icon.

### Known boundaries

- Images are still inserted only before hero or item names supported by server-provided structured image references.

## 16:30 — Match-detail Markdown and player equipment table

### Completed

- The match-detail template no longer emits `<sub>` or `<br>`; the data note is a pure Markdown blockquote so literal HTML tags are not shown when raw HTML parsing is disabled.
- Series results now use a single “Team A (wins) : Team B (wins)” line; BP tables use “order | pick | ban” and remove Ban/Pick parentheses and in-cell phase labels.
- Player tables remove the separate level column, append the level to the hero name, require thousands separators for net worth, and add a final equipment column. The Answer emits only evidence-backed item names; Chat replaces resolved items with medium icons without their names.

### Verification

- Added regression assertions for the match-detail Prompt and equipment-cell image replacement.
- Targeted API Prompt test: 1 passed (17 deselected); full API suite: 629 passed, 21 skipped, 1 warning.
- `ruff check`, all 20 Chat tests, ESLint, and the Next.js production build passed.

### Known boundaries

- A Catalog-missing item retains its original name, avoiding silent removal of equipment information present in evidence.
