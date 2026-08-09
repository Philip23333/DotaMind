# DotaMind Progress Snapshot — 2026-08-07

## 20:17 — V3.3-3 Valve static game catalog design contract

### Completed

- Added `docs/design/versions/DotaMind_V3.3-3_design.md`, freezing the Valve Datafeed offline sync, bilingual static catalog, normalization, Catalog Repository, query tools, EvidenceGraph, and natural-answer boundaries.
- Fixed the implementation order as A data sources and snapshots, B Runtime Catalog and resolvers, C query tools and Evidence, D Controller and natural answers, and E live sync and quality closure.
- Defined Valve committed snapshots as the authority for static hero/ability/talent/item definitions; STRATZ/OpenDota remain responsible only for match statistics such as usage, win rate, builds, and talent choices.
- Explicitly excluded VPK import, images/frontend cards, popular builds or talent win rates, fixed intent pipelines, and runtime network fallbacks from V3.3-3.

### Verified

- The plan was aligned with the current `sync_game_data.py`, hero resolver, ToolRegistry, EvidenceGraph, Controller Prompt, and V2.5/V3.2 architecture boundaries.
- This stage adds design and progress documentation only; sync scripts, runtime catalog, tools, prompts, APIs, and frontend behavior are unchanged.

### Boundaries

- Only A1 design-contract work is complete; A2-A5, B, C, D, and E are not implemented.
- Each later work item must be verified in design order and appended to the same-day Chinese/English progress snapshots without claiming later stages early.

## 21:05 — V3.3-3 A2-A5 data source and snapshot implementation

### Completed

- Added `app/integrations/valve/datafeed.py`, constraining Valve Datafeed access to the fixed official host, the two supported locales, bounded retry/timeout behavior, and the allow-listed hero/ability/item/patch-manifest endpoints; arbitrary URLs are rejected.
- Added `app/integrations/valve/catalog.py` with manifest, hero, ability, talent-tier, item, recipe, and bundle models, plus bilingual ID/internal-name joins, HTML/entity cleanup, special-value and talent-bonus placeholder rendering, and fail-fast checks for talent tiers, recipe graphs, dangling references, and unresolved tokens.
- Extended `scripts/sync_game_data.py`: the full normalized bundle is built and validated in memory, written to same-directory temporary files, then atomically replaced into `app/data/catalog/manifest.json` and the three catalog files; the existing hero YAML and patch JSON offline outputs remain supported.
- Added `tests/test_dota_catalog_sync.py` covering transport retry/endpoint boundaries, bilingual merge, HTML, ordinary special values, talent bonuses, Scepter text, talent tiers, unresolved tokens, identity mismatches, and snapshot schema round-tripping.

### Verified

- Focused pytest: `4 passed`.
- Ruff passes for `app/integrations/valve`, the sync script, and catalog tests.
- `python -m compileall` and `git diff --check` pass.
- A live Datafeed probe confirmed 127 heroes and 544 items currently return, with bilingual list/detail IDs and internal names joinable; the sync validator checks this before writing.

### Boundaries and blocker

- No incomplete production snapshot was committed: the real sync correctly fails before writing on Valve's current `sandking_scorpion_strike.shard_loc` `%caustic_damage_pct%` (and similar missing Scepter/Shard placeholders). The value is absent from current ability/talent special values, so guessing or a request-path fallback would violate the design contract.
- A2-A5 code and test contracts are implemented; the complete committed catalog snapshot must be regenerated after Valve Datafeed supplies those official placeholders, before entering B Runtime Catalog.

## 21:09 — A-stage regression gate

### Verified

- Full API pytest: `473 passed, 20 skipped` (with one existing Starlette/httpx deprecation warning).
- The A-stage focused suite remains `4 passed`; Ruff, compileall, and `git diff --check` all pass.

### Boundary

- The failed live sync did not write anything into `app/data/catalog/`; B Runtime Catalog has not started, and no request-path network fallback was added.

## 21:11 — A-stage final verification

- Isolated talent-bonus rendering by talent internal name so same-named fields (for example `AbilityCooldown`) cannot cross-contaminate; expanded default-display token checks to names, lore, and notes.
- Focused pytest: `4 passed`; full API pytest: `473 passed, 20 skipped`; Ruff, compileall, and `git diff --check` continue to pass.
