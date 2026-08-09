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
