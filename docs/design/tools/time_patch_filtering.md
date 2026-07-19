# Time & Patch Filtering for Agentic Tools

> Problem-framing doc for the agentic tool layer's time and patch scoping.
> Drives the work for this session: make time / patch filtering actually
> function from natural-language queries across both providers (STRATZ,
> OpenDota). Update as the design firms up.

## Scope of this session

Solve the tool-layer filtering problem for **time** ("最近一个月 / 最近 N 周 /
本周") and **patch** ("这个版本 / 7.38 版本"). The planner's job is to translate
a user's temporal intent into tool arguments; today that translation is broken
or inconsistent. Out of scope: UI, caching, ranking.

## Current state: two parallel time models

The codebase has two unrelated ways to express "when", and they do not reconcile.

### STRATZ — `week` (absolute week epoch)

- Defined as a cross-cutting scope filter on
  [`QueryContext.week`](../../../apps/api/app/agentic/models.py): `int | None`,
  `ge=0`. **Verified meaning of `null`: the most recent *completed* week — NOT
  all time.** See [Verified findings](#verified-findings--stratz-week-semantics).
- GraphQL type is `Long` (seconds-since-epoch of a STRATZ week boundary), see
  the queries in [stratz/heroes.py](../../../apps/api/app/integrations/stratz/heroes.py).
- Passed through `context.week` by four handlers: `pair_lane_outcome`,
  `hero_matchup_ranking`, `lane_meta_global`, `hero_position_stats`
  ([stratz_tools.py:597,641,707,759](../../../apps/api/app/agentic/tools/stratz_tools.py)).
- The planner prompt's stated contract
  ([controller.py](../../../apps/api/app/agentic/planning/controller.py)):
  *"week is a single STRATZ week epoch (seconds), not a range; for 'last N
  weeks' use the most recent week epoch."* — the "not a range" half is correct;
  the "last N weeks" guidance is wrong (see P1/P3 below).

### OpenDota — `days` (relative window)

- A **per-tool argument**, not on `QueryContext`. e.g.
  `team_recent_matches.days: int = 30`
  ([opendota_tools.py:28](../../../apps/api/app/agentic/tools/opendota_tools.py)).
- Computed server-side by Python:
  `cutoff = time.time() - args.days * 86400`
  ([opendota_tools.py:353](../../../apps/api/app/agentic/tools/opendota_tools.py)).

### Patch — separate dimension, not connected to time

- Patch is its own evidence source via `patch.get_records` / `patch.hero_changes`
  / `patch.item_changes` ([patch_tools.py](../../../apps/api/app/agentic/tools/patch_tools.py)).
- STRATZ hero stats take `week`, **not** patch. So "7.38 版本的 PA 胜率"
  cannot be cleanly scoped on STRATZ today.

## Verified findings — STRATZ `week` semantics

Probed live (2026-07-03, DIVINE_IMMORTAL) via
[scripts/stratz_week_probe.py](../../../apps/api/scripts/stratz_week_probe.py)
across all three production endpoints. Same shape on every endpoint:

| week value            | stats total | laneOutcome total | heroVsHeroMatchup total |
| --------------------- | ----------: | ----------------: | ----------------------: |
| `null`                | 1,360,365   | 1,617,054         | 66,109                  |
| current (in-progress) |   185,299   |   221,711         |  9,456                  |
| prev1 (last complete) | 1,360,365   | 1,617,054         | 66,109                  |
| prev2                 | 1,136,667   | 1,325,663         | 49,854                  |
| prev4                 | 1,312,733   | 1,524,831         | 57,869                  |

Conclusions (evidence-backed, not assumed):

1. **`week` is a single bucket** — one STRATZ week of data per call. Each
   distinct week epoch returns a different same-magnitude total.
2. **`null` == latest *completed* week** — byte-for-byte equal to `prev1` on
   all three endpoints. It is **not** "all time". Every production STRATZ tool
   defaults to `context.week=None`, so today every STRATZ query is implicitly
   scoped to the most recent complete week, but the evidence reports
   `filters.week: null` as if unscoped. That mismatch is a labeling bug
   regardless of whether one-week-default is the desired product behavior.
3. **No range/window support.** "Last N weeks" cannot be fetched in one call —
   it requires N calls (one per week epoch) plus client-side aggregation.
4. **The current (in-progress) week is partial** (~1/7 of a complete week when
   probed ~1 day into the week). Avoid it for stable stats; prefer the latest
   completed week.
5. **Week epoch is computable.** STRATZ weeks align to 604,800-second
   boundaries from the Unix epoch: `current_index = floor(now / 604800)`;
   current week epoch = `current_index * 604800`; latest completed week =
   `(current_index - 1) * 604800`. (Corroborated by the test fixture
   `week=1782345600 == 2947 * 604800` in test_agentic_evidence.py.) The backend
   has a clock; the planner LLM does not — so epoch resolution belongs in the
   executor, not the plan.

## Problems

### P1. The planner can never set `week` — STRATZ time filtering is inert from NL

The prompt instructs the LLM: *"for 'last N weeks' use the most recent week
epoch."* But the planner LLM has no clock and no knowledge of the current
STRATZ week epoch (STRATZ weeks are not ISO weeks; they are provider-specific
epoch boundaries). It cannot compute the value. In practice `week` is almost
always `null`. With the [verified semantics](#verified-findings--stratz-week-semantics),
that means almost every STRATZ query silently runs against the **latest
completed week only** — not all-time, and not the window the user asked for.

**Net effect:** natural-language time scoping on STRATZ hero/matchup queries is
non-functional. The LLM is told to emit an epoch it cannot compute; the
executor never fills it in; and the default (`null`) is itself a one-week
scope masquerading as "no filter".

### P2. Relative vs absolute are not unified

"最近一个月 PA 的胜率" maps to `days=30` on OpenDota but has no equivalent on
STRATZ, where `week` pins a single week point. There is no shared time-window
abstraction above the two providers, so the same user intent produces
semantically different filters depending on which provider a tool hits.

### P3. STRATZ `week` real semantics — RESOLVED

Verified against the live API; see
[Verified findings](#verified-findings--stratz-week-semantics). Outcome:
`week` is a **single weekly bucket**; `null` means **latest completed week**
(not all-time); no range form exists. This settles the prompt's internal
contradiction in favor of "single bucket", and exposes the bigger issue that
`null` is a one-week scope, not "no filter".

### P4. Patch and time are not bridged

"This patch / since 7.38" is the most common Dota temporal filter. Patch lives
on its own evidence axis and STRATZ hero stats only accept `week`, so a patch
range cannot be applied to STRATZ hero/matchup queries. To support "本版本胜率"
on STRATZ we need either a patch→week-epoch mapping or a different scoping
strategy.

## Open questions to resolve before designing the fix

1. ~~**STRATZ `week` semantics (P3).** Single-bucket or lower-bound?~~
   **RESOLVED 2026-07-03:** single-bucket; `null` = latest completed week. See
   [Verified findings](#verified-findings--stratz-week-semantics).
2. **How can the backend supply the clock the planner lacks (P1)?** Candidates:
   the executor injects the current STRATZ week epoch(s) into the context at
   plan-build time; or the planner returns a *relative* intent ("last 4 weeks")
   and a deterministic resolver expands it to a concrete `week` value after the
   LLM returns. The LLM should never be asked to emit a raw epoch. Given the
   verified "one call = one week" constraint, "last N weeks" implies N calls —
   the resolver+executor must fan out and aggregate.
3. **Unified time-window abstraction (P2).** Should `QueryContext` grow a
   relative window (e.g. `weeks_back` / `since`) that each tool maps to its
   provider-native form, instead of the LLM choosing absolute vs relative per
   provider? Note the cost asymmetry: OpenDota `days` is one call; STRATZ
   `weeks_back=N` is N calls.
4. **Patch→time bridge (P4).** Where does a patch↔week-epoch mapping live, and
   is it maintained manually per patch or derived from STRATZ's patch data?
5. **Is "latest completed week" the right STRATZ default?** Today `null`
   silently means that. Decide explicitly: keep one-week-default and *label*
   it correctly, or switch the unscoped default to a multi-week aggregate
   (with the N-call cost that implies).

## Design — STRATZ per-tool windowing (weekly buckets)

**Implemented 2026-07-03.** STRATZ gets first-class windowing, implemented
*inside* each STRATZ handler. A shared backend helper resolves a relative
`weeks_back` to concrete **completed**-week epochs; each handler fans out and
returns **one bucket per week — never merged across weeks** (each bucket is
STRATZ's own weekly data, so per-week `synergy`/rates stay valid). Empty weeks
are preserved so the synthesizer can show trend and call out gaps. OpenDota is
untouched (its native `days` window already works from NL). The LLM only ever
produces a relative integer, never an epoch.

> Pivot note: an earlier sketch of this design merged N weeks into one
> aggregated view. That was dropped during review — aggregating imposes a
> homemade statistic (pooled rates; non-additive `synergy` nulled then
> re-sorted) that is hard to verify and silently changes the ranking meaning.
> Weekly buckets are relayed data with provenance: lighter, more honest, and
> they show trend. `aggregation_mode: weekly|aggregate` (default `weekly`) is
> deferred; weekly buckets are its raw input.

### Why this shape (not a separate LLM-callable time-map tool)

Scope filters live on plan-level `QueryContext`, which is (a) set-once-per-plan
and (b) not ref-resolvable — the `$ref` mechanism only applies to tool args
([contracts.py:279-333](../../../apps/api/app/agentic/planning/contracts.py)). So a
tool that "returns week epochs" has no consumer: its output cannot be wired
into `context.week`. Resolution therefore must happen inside the handler, which
has the clock (`time.time()`). The shared helper centralizes the epoch math;
no cross-week merge is needed because each weekly bucket is returned as-is,
so each evidence shape's existing per-week filter/sort/select applies unchanged.

### Data model

- [`QueryContext.week: int | None`](../../../apps/api/app/agentic/models.py)
  (absolute epoch) → **`weeks_back: int | None`** (relative). `null`/unset →
  treated as `1` (latest completed week), matching today's effective behavior
  once the `null` label is fixed.
- Bounded via policy: `1 ≤ weeks_back ≤ cap` (recommend `cap = 8`, in
  `policy.yaml`). Reject out-of-range in the existing planner validation path
  so the LLM gets a retry signal rather than a silent clamp.
- The wire layer [stratz/heroes.py](../../../apps/api/app/integrations/stratz/heroes.py)
  is unchanged: it still takes absolute `week` and maps 1:1 to GraphQL `$week`.
  Handlers call it once per resolved epoch.

### Shared helper

```python
WEEK_SECONDS = 604_800

def resolve_recent_completed_weeks(weeks_back: int, *, now: float) -> list[int]:
    """Epochs of the last `weeks_back` *completed* STRATZ weeks, newest first.
    The in-progress current week is always skipped (verified partial: ~1/7 size
    one day in)."""
    idx = int(now // WEEK_SECONDS)
    return [(idx - k) * WEEK_SECONDS for k in range(1, weeks_back + 1)]
```

### Per-handler weekly buckets

Each handler: resolve epochs → for each epoch, fetch that week's raw records and
run the handler's **existing** per-week filter/sort/dedupe/select on them → wrap
the surviving rows in a `{week_epoch, week_index, window_label, rows}` bucket
(rows may be `[]`) → concatenate buckets newest-first. For `weeks_back == 1`
this is exactly today's single-call path; `synergy` and all STRATZ rates stay
intact within each week because nothing is merged.

- **`hero_matchup_ranking`** — per week: `_filter_matchup_rows` (sort `synergy
  desc, match_count desc`), then flatten advantage/disadvantage into rows with a
  `source_side` tag.
- **`pair_lane_outcome` / `lane_meta_global`** — per week: filter to partner /
  `_dedupe_pair_rows` + `min_sample_size` + top `highlight_top`.
- **`hero_position_stats`** — per week: optional sort + `take` when filtering by
  position.

Top-level result adds `weeks_with_record` and `missing_week_epochs` (weeks whose
`rows == []`) so a partial-week gap is visible to the synthesizer; the critic at
`graph.py:60` needs no change (a 1-of-N-weeks result did obtain evidence).

### Result + evidence labeling

`filters` is **augmented** (existing fields like `bracket_basic_ids`,
`position_ids`, `take`, `min_sample_size` are kept) with a resolved-window
block; the per-week rows live in a canonical `weekly_buckets` list:

```jsonc
{
  "weekly_buckets": [
    {"week_epoch": 1782345600, "week_index": 1, "window_label": "latest_completed_week", "rows": [ /* … */ ]},
    {"week_epoch": 1781740800, "week_index": 2, "window_label": "prior_completed_week",   "rows": []}
  ],
  "weeks_with_record": 1,
  "missing_week_epochs": [1781740800],
  "filters": { "weeks_back": 2, "week_epochs": [1782345600, 1781740800], "weeks_resolved": 2, "skipped_current_week": true }
}
```

Evidence extractors flatten `weekly_buckets`: one `EvidenceItem` per row, each
carrying `week_epoch`/`week_index`/`window_label`. OpenDota `days` is already
explicit; no change. The natural-language synthesizer prompt instructs the LLM
to compare across weeks and state trend, and to name any `missing_week_epochs`.

### Planner prompt

- Delete the wrong line: *"week is a single STRATZ week epoch (seconds), not a
  range; for 'last N weeks' use the most recent week epoch."*
- Replace with: *"weeks_back (STRATZ only) = number of recent completed weeks
  to fetch as per-week buckets, 1–8; set it for window queries ('最近两周' → 2).
  Leave null for the default (latest completed week). Prefer 最近 N 个已完成周
  over 本周 (the current STRATZ week is partial). Never emit raw week epochs."*
- Keep OpenDota `days` guidance as-is.

### Ripple / migration

- [`models.QueryContext`](../../../apps/api/app/agentic/models.py): rename field +
  validator bounds.
- [`stratz_tools.py`](../../../apps/api/app/agentic/tools/stratz_tools.py): 4
  handlers gain epoch-resolution + per-week fan-out (no merge); add
  `resolve_recent_completed_weeks`, `_with_retry`, `_bucket`/`_week_summary`
  helpers; evidence extractors flatten `weekly_buckets`.
- [`synthesizer.py`](../../../apps/api/app/agentic/answer/synthesizer.py): prompt
  constant asks for per-week trend + `missing_week_epochs` disclosure.
- [`controller.py`](../../../apps/api/app/agentic/planning/controller.py): prompt text +
  the worked-example `context` field name (`week` → `weeks_back`).
- Tests (`test_agentic_evidence.py`, `test_agentic_stratz_tools.py`): the
  `1782345600` literal → `weeks_back`; keep one unit test asserting
  `resolve_recent_completed_weeks(1)` at a frozen `now` returns that epoch.
- [`heroes.py`](../../../apps/api/app/integrations/stratz/heroes.py): no change.
- [`policy.yaml`](../../../apps/api/app/config/policy.yaml): add `weeks_back` cap
  (+ default).

### Cost / limits

- `weeks_back = N` ⇒ N STRATZ calls per STRATZ tool in the plan. With STRATZ
  rate-limiting and the SSL flakiness observed during probing, handlers must
  reuse a retry/backoff wrapper (the probe's `_graphql_with_retry`) and share
  one `StratzTransport` across the fan-out.
- Cap at 8 as a guardrail; revisit if real queries need more.

### Out of scope here (but now easier)

- **Patch↔time bridge (P4):** a patch release date → `weeks_back` (relative to
  now) becomes a trivial mapping once we expose patch timestamps; deferred.
- **Unifying with OpenDota `days`:** intentionally NOT done — OpenDota already
  handles windows natively in one call; forcing it through this mechanism would
  add cost for no benefit.

## Decision log

- **2026-07-03 — STRATZ `week` semantics (closes P3):** `week` selects a single
  STRATZ week (604,800s-aligned bucket); `null` returns the latest *completed*
  week; no range/window form exists. Verified across `heroStats.stats`,
  `heroStats.laneOutcome`, `heroStats.heroVsHeroMatchup` at DIVINE_IMMORTAL.
  Consequence: any multi-week intent requires N fan-out calls + client
  aggregation, and epoch values must be computed by the backend (which has a
  clock), not the planner LLM. Raw evidence in
  [Verified findings](#verified-findings--stratz-week-semantics); re-runnable
  via [scripts/stratz_week_probe.py](../../../apps/api/scripts/stratz_week_probe.py).
- **2026-07-03 — STRATZ windowing shape (closes P1/P2 for STRATZ):** implement
  per-tool windowing (reading 2), not a separate LLM-callable time-map tool.
  `QueryContext.week` (absolute epoch) → `weeks_back` (relative int, 1–8); a
  shared `resolve_recent_completed_weeks()` helper computes epochs inside each
  STRATZ handler, which fans out and merges raw records per evidence shape.
  Chosen because `QueryContext` is set-once and not ref-resolvable, so an
  epoch-producing tool has no consumer; resolution must live in the handler.
  OpenDota `days` left as-is. Full design above; P4 (patch↔time) deferred.
- **2026-07-03 — Implemented as weekly buckets, not aggregation:** the per-tool
  windowing was built to return one bucket per completed week (empty weeks
  preserved), not a merged aggregate. Pivot rationale: aggregating N weeks
  imposes an unverifiable homemade statistic (pooled rates; non-additive
  `synergy` nulled then re-sorted), silently changing `hero_matchup_ranking`'s
  meaning; weekly buckets keep STRATZ's per-week `synergy`/rates valid and show
  trend. `weeks_back` (1–8, default 1) on `QueryContext`; `StratzPolicy` cap in
  `policy.yaml` enforced via `validate_context_scope`; `_now()` clock + retry
  in handlers; synthesizer prompt asks for per-week trend. 128 agentic/config
  tests pass; live `--weeks-back 2` returns 2 buckets (~1 week each, synergy
  present). Aggregation mode + patch↔time (P4) still deferred.
