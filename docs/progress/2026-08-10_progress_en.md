# DotaMind Progress Snapshot (2026-08-10)

## 02:43 — Ascetic's Cap runtime exclusion and sync audit

### Completed

- Excluded Valve Datafeed item 825, `item_ascetic_cap`, from the default runtime catalog of currently available items. `DotaCatalogRepository` does not load the sync audit, so ID and name resolution return not found and incomplete effects are not exposed to users.
- Added `CatalogSyncAudit` / `CatalogExcludedEntity`. The sync classifies this item as `legacy_or_unclassified` and retains the official raw English/Simplified Chinese descriptions, unresolved tokens, status fields, special-value fields, recipe relations, and source endpoints.
- Scoped the exclusion to exact ID 825 plus internal name `item_ascetic_cap`. Any drift in bilingual identity, the three tokens, status fields, the sole `AbilityCooldown` special value, or recipe relations fails fast and requires renewed review; the rule is not generalized to other items.
- Expanded snapshot output to five atomically replaced files: manifest, heroes, abilities, items, and the developer-only `sync_audit.json`. Manifest counts include runtime entities only, and an audited exclusion cannot also appear in the runtime catalog.
- Aligned `DotaMind_V3.3-3_design.md` with the runtime exclusion, audit artifact, and no-incomplete-user-output boundary.

### Verification

- Catalog A+B focused: `50 passed`.
- Full API pytest: `519 passed, 20 skipped`.
- Ruff, compileall, and `git diff --check` passed.
- A targeted live audit against current Valve 7.41e data passed: item 825 was classified as `legacy_or_unclassified`; both raw localized descriptions and the `duration`, `slow_resistance`, and `status_resistance` tokens were retained; status and recipe evidence matched the reviewed shape.
- The full live no-write build advanced past item 825 and then failed fast on an unresolved token in item 81. That separate upstream gap was not added to this exception, and no formal snapshot was written.

### Current boundary

- `sync_audit.json` is a developer audit artifact, not a runtime fallback, and does not participate in resolver, tool evidence, or Answer.
- This change does not guess the missing Ascetic's Cap values or expose raw tokens such as `%status_resistance%` to users.
- The formal A4 snapshot still requires resolving the separate item 81 token gap before it can be generated and reviewed in full.

## 02:52 — Generic item-note token rendering fix

### Completed

- Fixed `normalize_item` cleaning `notes_loc` HTML without applying value replacement. All English and Simplified Chinese item notes now pass through `_render` with the current item's `special_values` replacement map.
- Added no item 81 / `item_vladmir` exception. Current Valve data already supplies `lifesteal_creeps_tooltip=12`; the official note now renders `%lifesteal_creeps_tooltip%%%` correctly as `12%`.
- Unknown or missing item-note tokens still fail fast; no raw-token display, guessed value, or other fallback was added.
- Added bilingual item-note rendering coverage and a missing-token rejection test.

### Verification

- Catalog sync focused: `48 passed`; Catalog A+B focused: `52 passed`.
- Full API pytest: `521 passed, 20 skipped`.
- Ruff, compileall, and `git diff --check` passed.
- Independent live parsing of current Valve item 81 passed: both localized notes rendered `12%` and their remaining-token lists were empty.
- The full Valve 7.41e no-write build succeeded with `127` heroes, `1707` abilities, `543` runtime items, and `1` audit exclusion. There is currently no next sync blocker, and no formal snapshot was written.

### Current boundary

- This change only fixes offline normalization before runtime catalog generation; resolver, tool, EvidenceGraph, and Answer contracts are unchanged.
- The formal A4 artifacts are now generatable, but A4 still requires a formal write plus structural and diff review of all five snapshot files before closure.

## 03:22 — A4 formal snapshot and B2 Catalog resolver switch

### Completed

- Formally ran the Valve 7.41e sync and generated the five-file snapshot under `app/data/catalog/`: manifest, heroes, abilities, items, and the developer-only sync audit.
- The formal snapshot contains `127` heroes, `1707` abilities, `543` runtime items, and `133` recipe edges. The audit contains only the `legacy_or_unclassified` exclusion for item 825, `item_ascetic_cap`, and that ID is absent from runtime items.
- Changed the default ToolRegistry to register `dota_catalog_tools.register_dota_catalog_tools` first. `resolve_hero` now has one registration with `official_snapshot` provenance, while its public tool name, `data.hero.hero_id` output path, and downstream reference contracts remain unchanged.
- Removed the old `resolve_hero` registration, input model, handler, and evidence extractor from the STRATZ module. STRATZ evidence now reads its English hero-name index from the same Catalog repository, eliminating the remaining second hero-data source.
- Deleted the old `hero_tools.py`, `app/data/heroes/dota2_heroes.yaml`, and dedicated resolver tests; the sync no longer generates the old YAML. `hero_aliases_zh.yaml` remains as the reviewed alias overlay injected into Catalog.
- Updated Datafeed patchnotes validation to accept valid letter-suffixed patches such as `7.41e`, while still allowing only a dotted numeric patch plus one optional lowercase letter; arbitrary parameters remain rejected.
- Updated the Controller golden prompt and current architecture documentation for the new Catalog resolver provenance and single-path boundary.

### Verification

- Primary-agent switch-focused suite: `102 passed`; full API pytest: `518 passed, 20 skipped`.
- Ruff, compileall, and `git diff --check` passed.
- All five formal files passed Pydantic, catalog, manifest, and sync-audit consistency validation; actual entity counts exactly match the manifest.
- Live default-registry verification: exactly one `resolve_hero`; `火女` resolves by exact match to Lina / hero ID 25; source is `official_snapshot`; snapshot patch is `7.41e`.
- Existing STRATZ plan-local reference contracts to `resolve_hero` remain valid, the OpenDota registry is unaffected, and STRATZ English hero display-name semantics are unchanged.

### Current boundary

- A4 formal snapshot generation and B2 `resolve_hero` relocation are closed. Runtime hero resolution no longer depends on the old YAML and has no network fallback.
- `dota_catalog_tools.py` currently registers only the migrated `resolve_hero`. Hero attributes, abilities, talent tree, item resolver/info, and the remaining Catalog tools still follow the V3.3-3 C-phase order.
- This work remains unstaged and uncommitted.

## 13:00 — C1-C5 Catalog query tools and EvidenceGraph closure

### Completed

- Added `dota.hero_attributes`, `dota.hero_abilities`, `dota.hero_talent_tree`, `resolve_item`, and `dota.item_info` through the single `dota_catalog_tools` registration path, for six Catalog tools including `resolve_hero`.
- All three hero-data tools require `hero_id` to reference the current plan's preceding `resolve_hero.data.hero.hero_id`; `dota.item_info.item_id` requires a preceding `resolve_item.data.item.item_id`. Literals, wrong tools/paths, and forward references are rejected.
- The attributes tool returns identity, base/growth attributes, and combat/movement fields. The abilities tool preserves hero ability-ID order while excluding talents and exposes bilingual descriptions, level values, innate/Scepter/Shard data. The talent tool emits exactly four 10/15/20/25 left/right tiers.
- The item resolver preserves exact/fuzzy/ambiguous/not_found and explicit recipe scope. Item info exposes the complete bilingual definition and emits a recipe graph only when components or upgrade targets actually exist.
- All six tools use `official_snapshot` provenance and snapshot metadata. Evidence kinds/mandatory obligations are fixed for `hero_identity`, `hero_attributes`, `hero_ability`, `hero_talent_tree`, `item_identity`, and `item_definition`; `item_recipe` is optional and produced only for real relations.
- Closed ToolRegistry, Controller catalog rendering, plan validation, plan-local reference execution, EvidenceGraph per-call mandatory, and producibility regression coverage. No intent-specific routing, request-time Datafeed HTTP, or third-party fallback was added.

### Verification

- Primary-agent Catalog/C5 focused suite: `119 passed`; full API pytest: `533 passed, 20 skipped`.
- Ruff, compileall, and `git diff --check` passed.
- Actual evidence chains produced identity, attributes, ordered abilities, and eight talent-branch evidence items for heroes; BKB produced identity/definition/recipe; Tome of Knowledge produced identity/definition only and correctly reported missing evidence when recipe was explicitly required.

### Current boundary

- C1-C5 are complete. D-stage Controller Supported/Unsupported wording, static-catalog natural-answer rules, and full graph natural-answer regressions are not yet changed.
- The changes in this section are uncommitted.

## 13:50 — D1-D3 Controller/Answer/Graph and E1 live review

### Completed

- Expanded Controller Supported/Unsupported capability text for hero attributes, abilities/innates/Scepter/Shard, four-tier talents, and item definitions/prices/effects/recipes/neutral tiers, while requiring statistical evidence for popularity, win rate, recommendations, and strength judgments.
- Added three plan-local reference examples for Lina abilities, shared-resolver Lina attributes plus talents, and BKB price plus recipe. No intent-specific routing was added.
- Extended the single `natural_language_answer` path with Catalog evidence rules for base/gain values, ability level arrays, talent tier/side, normal/innate/Scepter/Shard distinctions, item/final recipe/component/upgrade distinctions, and patch/generated_at disclosure. Static definitions cannot support recommendation, popularity, skill-build, or talent-win-rate claims.
- Added Graph end-to-end coverage for hero attributes, abilities, talents, combined queries, BKB definition plus recipe, and an item without a recipe. Every success path runs Tool→Evidence→Answer→Critic, with resolver ambiguity/not_found, bad references, missing recipe evidence, and Answer LLM errors covered.
- Completed E1 manual review of the formal 7.41e snapshot: Lina/25 attributes, normal abilities, innate Slow Burn, Scepter-granted Flame Cloak, Shard-upgraded Laguna Blade, and all four talent tiers are complete; Blink Dagger's active effect and BKB's Mithril Hammer/Ogre Axe component relation are complete.

### Verification

- Primary-agent D focused suite: `73 passed`; full API pytest at D completion: `548 passed, 20 skipped`.
- Ruff and `git diff --check` passed.
- The live review read only the committed Catalog snapshot; it performed no request-time Valve/STRATZ/OpenDota network access and used no mock Catalog business data.

### Current boundary

- D1-D3 and E1 are complete. The single natural-answer path, existing streaming behavior, and output contract remain; no card or second reviewer was added.
- E2 final full quality gates, documentation consistency review, and Git commit remain.

## 13:51 — E2 quality gates and V3.3-3 phase closure

### Completed

- Ran the final full regression for the six Catalog tools, Controller capability boundary, Answer rules, and Graph success/failure paths added in C/D.
- Updated the current architecture document for the single Catalog registration path, plan-local resolver references, EvidenceGraph obligations, static/statistical boundary, and single natural-answer path.
- Kept the daily Chinese and English progress files structurally and factually aligned. No frontend code changed and no unrelated frontend test claim was made.

### Verification

- Full API pytest: `548 passed, 20 skipped`.
- Ruff (app/tests/scripts), compileall, and `git diff --check` passed.
- The only non-blocking warning is the existing Starlette/httpx deprecation warning.

### Phase conclusion

- The V3.3-3 A-E implementation order is closed: formal Valve snapshots, Runtime Catalog/resolvers, six query tools, EvidenceGraph, Controller/Answer/Graph regression, and live review are complete.
- The current changes meet the commit gate; no remote push is included.

## 14:15 — Hero-ability answer format and query granularity closure

### Completed

- Made Controller distinguish complete hero ability-list queries from single-ability queries. Complete queries run one `resolve_hero`, then `dota.hero_abilities` and `dota.hero_talent_tree`; single-ability queries run resolver plus abilities only unless talents are also requested.
- Prevented Answer from exposing internal schema/token names such as `has_shard`, `has_scepter`, `is_innate`, `special_bonus_*`, `talent_internal_name`, and `internal_name`; it uses natural headings such as Shard upgrade, Scepter upgrade, and innate ability.
- Fixed the complete-list answer shape to bilingual hero identity plus snapshot, ordered per-ability details, and a concise final talent table with “Level | Left talent (Chinese / English) | Right talent (Chinese / English)”.
- Removed redundant ability-classification-summary and related-talents sections from complete answers, including talent internal-token suffixes beside values.
- Single-ability answers output only the requested ability and omit other abilities, classification summaries, related talents, and the full talent tree.
- Kept the single `natural_language_answer` path and existing Catalog tool/evidence payloads; no deterministic formatter, card, or second answer implementation was added.

### Verification

- Controller/Answer/Graph focused: `70 passed`; full API pytest: `550 passed, 20 skipped`.
- Ruff, compileall, and `git diff --check` passed.
- Graph regression with the formal Monkey King Catalog evidence confirms complete queries include ability plus talent evidence, single-ability queries omit talent evidence, and the user-visible example contains the talent table without internal tokens.

### Current boundary

- The single Answer LLM is constrained by explicit system rules rather than a second deterministic renderer. Original structured Catalog fields remain in internal tool evidence for audit.
- The changes in this section are uncommitted.

## 21:30 — Item recipe data and answer-format fix

### Completed

- Audited and cleaned the interrupted diff: this change keeps only Repository, `dota.item_info`, Answer formatting, related tests, and recipe documentation; all multi-turn conversation-memory changes were removed from this fix.
- Added deep-copy recipe-edge lookup to `DotaCatalogRepository` by either finished-item ID or recipe-scroll ID; a basic item is not treated as a crafted item merely because it is used as a component.
- `dota.item_info` now returns recipe-scroll, component, and true further-upgrade definitions with bilingual names, prices, `special_values`, and auditable cost details; the queried finished item remains only in the original official edge target.
- Accepted against the formal 7.41e Shiva's Guard snapshot: recipe scroll 118 costs 1250, components 9/1847/1872 cost 1400/950/900, and the calculated total is 4500, matching the finished-item price. No snapshot regeneration or hero/item hardcoded exception was added.
- Fixed Answer rules to render crafted items as a “Component (Chinese name (English)) | Price | Attributes” table with a separate scroll row; basic items show only bilingual name, price, and attributes. Answers must not claim there is no scroll when scroll evidence exists and only mention a mismatch when costs disagree.
- Aligned the V3.3-3 design and current architecture with recipe-edge, scroll, and cost-evidence semantics.

### Verification

- Repository/Tool/Answer focused: `38 passed`.
- Full API pytest: `552 passed, 20 skipped`, with one existing Starlette/httpx deprecation warning.
- Ruff, compileall, and `git diff --check` passed.

### Current boundary

- This change does not address compact Turn, multi-turn component references, or historical entity memory; “prices of the three recipe components above” remains a separate follow-up issue.
- No Catalog snapshot regeneration or third-party/network fallback was added; all changes remain uncommitted.

## 22:38 — Generic discourse-graph conversation memory

### Completed

- Replaced the domain-specific Turn `resolved_entities` field with generic `DiscourseState`: open-string kinds/labels, referents, ordered groups, links, focus, and grounding, with model and `ConversationPolicy` checks for topology, refs, status, and limits.
- Added asynchronous `DiscourseExtractor`. Its input is only the prior available discourse, the current full query, the current full answer, and structural limits. It does not read or parse the 300-character `response_summary`, and stores no IDs, prices, attributes, win rates, or other factual values.
- Extraction allows one deterministic validation-feedback retry. A second failure writes an `unavailable` empty graph and records a low-cardinality discourse metric. A successful business answer keeps its status when extraction fails; a later Controller exposes `context_missing` when that memory is required.
- Changed `PlanService._build_turn()` to async, skipped extraction for safe failures, allowed clarification turns to inherit prior discourse while extracting the current query/clarification question, and made `ChatRunExecutor` await compact Turn construction before PostgreSQL commit.
- Rendered Controller history as escaped object/group/link/focus data. Direct recall now uses `recall_referent` plus a discourse ref, with deterministic server rendering of referent names or group member names. Kinds/labels are not routing keys; current facts still require current-turn tools and evidence.
- Upgraded Redis Turns to strict `schema_version=2` discourse DTOs. Only v2 is written, old `response_summary` is never used to rebuild memory, and old session keys may expire. Older PostgreSQL JSONB Turns missing discourse load with the default empty state.
- Added the Conversation Memory design note and synchronized the current architecture, Controller design, V3.2 design reference, and Controller golden prompt.

### Verification

- Discourse/summary/render/decision/Redis focused tests: `110 passed`.
- Full API pytest: `561 passed, 20 skipped, 1 existing Starlette/httpx deprecation warning`.
- With local Redis enabled (`DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`), Redis integration passed `14 tests` and the full API suite passed `576 passed, 5 skipped`; the warning was unchanged.
- Focused Ruff, full API Ruff, compileall, and `git diff --check` were run in the final gate.
- Coverage includes Lina groups and ordered references, Shiva-style multi-component relations, open `guide` kinds, multiple groups, invalid refs/topology, limits, grounding failure, extractor unavailability, failed-turn non-reuse, historical non-evidence, and Redis v2 round-trips.

### Current boundary

- Discourse is referent and collection-selection memory, not an EvidenceGraph, factual cache, or current-turn evidence; historical names and IDs cannot be copied into downstream tool arguments.
- `response_summary` keeps the existing 300-character answer-excerpt contract; this change does not solve multi-turn reference by increasing its length.
- The changes remain uncommitted; this real-Redis validation used a random test prefix and deleted only exact test keys.
