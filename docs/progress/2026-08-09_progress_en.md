# DotaMind Progress Snapshot — 2026-08-09

## Pre-commit verification — V3.3-3 Stage A

### Verified

- Focused catalog-sync tests: `4 passed`.
- Ruff passes for `app/integrations/valve`, the sync script, and the focused tests.
- `compileall` passes for the Valve integration and sync script; `git diff --check` passes.
- The commit scope is limited to the V3.3-3 Stage A Valve Datafeed transport, catalog normalization and validation, offline snapshot generation, focused tests, design document, and aligned progress records.

### Boundaries

- This verification does not claim that a live catalog snapshot has been generated. At that point the live sync failed fast on a Scepter/Shard display placeholder; the later 18:37 audit identified the Sand King field as inactive stale data and corrected the gate. The sync never committed an incomplete snapshot or added guessed values or a request-path network fallback.
- Stages B-E are not implemented.

## 17:10 — V3.3-3 B1-B4 Runtime Catalog and resolver

### Completed

- Added `app/integrations/valve/catalog_repository.py`: loads manifest, hero, ability, item, and recipe snapshots once at construction, validates them with the current Pydantic models and `validate_catalog`, and returns deep copies from ID queries so callers cannot mutate global state.
- Implemented hero/item exact, fuzzy, ambiguous, and not_found resolution. Indexes cover Chinese/English names, prefix-stripped internal names, and aliases; item resolution prefers final items by default and enters recipe scope only for explicit recipe/blueprint queries.
- Added `app/agentic/tools/dota_catalog_tools.py` and moved the `resolve_hero` registration and handler out of `stratz_tools.py`. Tool name, `data.hero.hero_id` output path, and `hero_identity` mandatory evidence remain unchanged; source is now the Valve committed snapshot and result data exposes patch/generated_at/schema metadata.
- STRATZ keeps only the evidence compatibility export; hero-stat evidence name lookup now reads the Runtime Catalog.
- Added B-stage repository, snapshot-consistency, deep-copy, hero/item resolver, recipe-scope, and tool-contract tests.

### Verified

- A+B focused tests: `8 passed`.
- Ruff passes for the B implementation and tests.

### Boundary and blocker

- The worktree still has no committed `app/data/catalog/` snapshot. At that point the live Valve sync stopped on an unresolved Scepter/Shard placeholder; the later 18:37 audit corrected this to an inactive-field gating issue. Per design, `build_default_tool_registry()` raises `CatalogSnapshotError` when snapshots are missing; it does not fall back to the old YAML or access the network.
- Consequently, legacy graph/plan tests that construct the default registry fail explicitly at registry construction. Full B runtime regression must continue after E1 produces and reviews the official snapshot; no guessed data or parallel registration path was added.

## 17:12 — B-stage blocker boundary correction

- Full regression confirmed that enabling the B2 default-registry migration while snapshots are absent makes existing graph/plan tests and service construction fail at startup. Therefore this turn keeps the existing default registry and legacy hero resolver active and does not claim B2 migration complete.
- `dota_catalog_tools.register_dota_catalog_tools(registry, repository)` is implemented and verified with an injected snapshot fixture; once `app/data/catalog/` has an official snapshot, perform the one-time registration migration and remove the old registration.
- Final verification: A+B data/repository focused tests `8 passed`; full API pytest `477 passed, 20 skipped`. This is an explicit migration blocker, not a runtime fallback: the new Catalog repository itself still fails fast on missing/corrupt snapshots.

## 18:37 — Stage A Scepter/Shard display-semantics correction

### Completed

- `normalize_ability` parses and emits `shard_loc` only when `ability_has_shard=true`, and parses and emits `scepter_loc` only when `ability_has_scepter=true`; inactive stale fields emit empty strings and do not trigger token validation.
- Active Shard text prefers a non-empty `values_shard` array for each special value, while active Scepter text prefers a non-empty `values_scepter` array; both fall back to base values when the upgrade array is empty, and `[0]` is treated as a valid upgrade array.
- Ordinary names, descriptions, lore, and notes, plus structured `special_values.values/rendered_*`, continue to use base values. `granted_by_shard` / `granted_by_scepter` remain independent facts and do not participate in the `has_*` display gate.

### Verified

- Catalog-sync focused tests: `8 passed`; A+B data/repository focused tests: `12 passed`.
- Full API pytest: `481 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed in-memory build that writes no files advanced beyond the old Sand King Stinger `shard_loc` blocker; it later encountered `{s:bonus_AbilityChannelTime}` in another ordinary/talent name field, so no official snapshot has been generated yet. That separate token-association issue is outside this upgrade-field correction.

### Boundary correction

- The earlier description of Sand King Stinger as an “officially missing active Scepter/Shard placeholder” was inaccurate. The current skill has `ability_has_shard=false`, making its `shard_loc` inactive stale data; with the correct gate it no longer blocks synchronization and does not demonstrate missing current active Shard data in Datafeed.

## 19:22 — Stage A cross-auxiliary talent-bonus resolution

### Completed

- The sync filters Valve `abilitylist` to exclude items, talents, and abilities already covered by `herodata`, then fetches only the remaining English `abilitydata` as sync-time relationship input. These auxiliary abilities participate only in talent-token resolution, do not enter the hero ability catalog, and add no runtime network request.
- The reverse talent-bonus index retains source ability ID, internal name, field, value, and operation. Resolution prefers hero-owned abilities over official auxiliaries and merges token requirements from both English and Chinese talent display fields.
- Multiple sources with the same value and operation for one talent/field collapse into one fact while retaining their sources; conflicting values, operations, or structured lists still fail fast deterministically. Field matching prefers exact names before Valve `bonus_`, case, and underscore aliases.
- The generic relationship resolves Tinker `tinker_keen_teleport`, Invoker `forged_spirit_melting_strike`, Naga Siren `naga_siren_reel_in`, and Tiny/Shadow Demon same-fact multi-source and alias shapes without hard-coding heroes, abilities, or values.

### Verified

- Catalog-sync focused tests: `16 passed`; A+B data/repository focused tests: `20 passed`.
- Full API pytest: `489 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed no-write in-memory build for patch `7.41e` advanced beyond every known talent-name token, then failed fast on `%bonus_AbilityCooldown%` in an active `scepter_loc`; no incomplete snapshot was written or committed.

### Current boundary

- The official A4 snapshot is still not available. The new blocker is not a missing cross-auxiliary talent bonus but a current-skill upgrade-field alias: active Scepter text for at least Bane, Venomancer, Lifestealer, Ogre Magi, and Mars uses `%bonus_AbilityCooldown%`, while the same ability already supplies `AbilityCooldown.values_scepter`. That separate issue is left for the next change.

## 19:34 — Stage A Scepter/Shard upgrade-field aliases

### Completed

- Active Scepter/Shard replacement maps support both each official upgrade field's exact name and a derived `bonus_<field>` token. `values_scepter` / `values_shard` remain preferred, empty upgrade arrays fall back to base values, and `[0]` remains a valid upgrade value.
- Mapping uses two priority stages: real fields and their case/underscore aliases are registered first, then derived `bonus_` aliases are added. A real `bonus_` field cannot be overwritten by another field's derived alias, and different values at the same alias priority fail fast deterministically.
- Upgrade maps are built only when the corresponding `ability_has_scepter` / `ability_has_shard` flag is true; inactive stale upgrade fields do not block even if their aliases conflict. Ordinary names, descriptions, lore, notes, and structured special values continue to use the base map.

### Verified

- Catalog-sync focused tests: `19 passed`; A+B data/repository focused tests: `23 passed`.
- Full API pytest: `492 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed no-write in-memory build for patch `7.41e` advanced beyond active Scepter `%bonus_AbilityCooldown%` text for Bane, Venomancer, Lifestealer, Ogre Magi, and Mars.

### Current boundary

- The official A4 snapshot is still unavailable. The next blocker is `%base_magic_resistance%` in ordinary `notes_loc` for Lone Druid `Summon Spirit Bear` (ability ID `1342`), while the same official ability exposes `bear_magic_resistance=[25]`. This is a base-field semantic alias rather than a mechanical prefix; it remains an unresolved-token fail-fast, was not hard-coded into this upgrade-alias change, and no incomplete snapshot was written.

## 19:44 — Stage A targeted Lone Druid Spirit Bear alias

### Completed

- Following the explicit product decision, a strictly targeted exception now maps the ordinary-text token `base_magic_resistance` to the same official record's base field `bear_magic_resistance` only when `ability_id=1342` and the internal name is `lone_druid_spirit_bear`.
- The exception does not hard-code the value or add a global `base_` / `bear_` inference. A missing source field or any ID/internal-name mismatch still reaches unresolved-token fail-fast. A real `base_magic_resistance` field takes precedence, and a value conflict with `bear_magic_resistance` fails explicitly.
- Other heroes or abilities remain unaffected even if they contain the same source/token names; English and Chinese text continue to share the same identity-validated base replacement map.

### Verified

- Catalog-sync focused tests: `24 passed`; A+B data/repository focused tests: `28 passed`.
- Full API pytest: `497 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed no-write in-memory build for patch `7.41e` advanced beyond Lone Druid `%base_magic_resistance%`; no incomplete snapshot was written.

### Current boundary

- The official A4 snapshot is still unavailable. The next stable blocker is `%castpoint_tooltip%` in Chinese `notes_loc` for Bloodseeker `Blood Rite` (ability ID `5016`). The English note uses `%abilitycastpoint%`, which resolves from `AbilityCastPoint=[0.3]`, while the Chinese token has no exact match in the current base fields. That Chinese-localization field difference is outside this Lone Druid-only exception.

## 21:10 — Stage A English-authoritative Blood Rite Chinese note

### Completed

- Following the product decision, the English note for Bloodseeker `Blood Rite` (ability ID `5016`, internal name `bloodseeker_blood_bath`) is the semantic authority. The current incorrect Chinese note is replaced by a reviewed translation template: “总时间为 `%delay%` 秒的生效延迟，加上 `%abilitycastpoint%` 秒的施法时间。”
- The translation does not hard-code `2.6/0.3`; it still renders dynamically from Valve's official `delay` and `AbilityCastPoint`. English output is unchanged, and no online translation, runtime LLM, or global Chinese fallback is introduced.
- The exception requires the target English and Chinese source notes to match exactly and uniquely. English semantic-source drift or a missing/added/changed Chinese target fails fast, preventing a stale reviewed translation from being emitted. `%castpoint_tooltip%` in every other hero or ability remains unaffected.

### Verified

- Catalog-sync focused tests: `30 passed`; A+B data/repository focused tests: `34 passed`.
- Full API pytest: `503 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed no-write in-memory build for patch `7.41e` completed all hero, ability, and talent normalization and reached item-catalog processing for the first time; no incomplete snapshot was written.

### Current boundary

- The official A4 snapshot is still unavailable. The next blocker is `%customval_team_tomes_used%` in English `desc_loc` for `Tome of Knowledge` (item ID `257`, `item_tome_of_knowledge`). The token is the match-time count of tomes consumed by the team. The official `special_values` provide `xp_bonus=750` and `xp_per_use=150` but no field for that dynamic count. It is dynamic match-state display rather than a value recoverable from the static item definition, so synchronization continues to expose it through fail-fast.

## 21:33 — Stage A Tome of Knowledge static-description boundary

### Completed

- Only for `item_id=257` with internal name `item_tome_of_knowledge`, the match-time team-count suffix containing `%customval_team_tomes_used%` is removed from both localized descriptions. The static `Use: Enlighten` / “使用：启迪” effect remains intact.
- `xp_bonus` and `xp_per_use` continue to render dynamically from Valve's official `special_values`. The team count is not replaced with `0`, and no global `customval_` ignore rule is introduced.
- The complete English/Chinese static description, unique dynamic suffix, and final-suffix position must all match exactly. Source drift, a missing/duplicate target, or a non-final target fails fast. The same token in any other item remains unresolved.

### Verified

- Catalog-sync focused tests: `36 passed`; A+B data/repository focused tests: `40 passed`.
- Full API pytest: `509 passed, 20 skipped`, with only the existing Starlette/httpx deprecation warning.
- Ruff, `compileall`, and `git diff --check` pass.
- A live Datafeed no-write in-memory build for patch `7.41e` advanced beyond the Tome runtime count. Attributes, abilities, talents, and bilingual token normalization for all 127 heroes continue to complete successfully; no incomplete snapshot was written.

### Current boundary

- The official A4 snapshot is still unavailable. The next blocker is `%status_resistance%` in the English description of `Ascetic's Cap` (item ID `825`, `item_ascetic_cap`). Aeon Disk and Ceremonial Robe use the same token and both expose a resolvable `status_resistance` field; only Ascetic's Cap currently has an empty `special_values` array. This is an item-catalog issue and does not affect the now-closed hero/ability/talent normalization path.
