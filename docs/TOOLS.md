# Tools

## Design rules

Agent-visible tools describe stable observation capabilities, not transport
endpoints or provider implementation details. Oversized complete logical tool
responses are retained as temporary Artifacts and explored through generic
Artifact tools. The default registry externalizes a validated non-Artifact
result larger than the configured inline threshold (12 KiB by default) and
returns a bounded structural observation together with its opaque Artifact
reference. That observation uses the configured observation budget (35 KiB by
default) and may still include small scalar leaves. Artifact retrieval tools
remain inline; `artifact.read` applies the same configured serialized-result
bound. Both limits use UTF-8 serialized bytes and are configured by
`DOTAMIND_TOOL_INLINE_MAX_BYTES` and `DOTAMIND_TOOL_OBSERVATION_MAX_BYTES` in
the root `.env` or process environment; the inline limit must not exceed the
observation limit.

The accepted shared-result target uses these same two root `.env` settings in
both stages: one centrally parsed/injected budget, tool-owned normal size handling,
and a common final result-size check. Independent query/answer 35 KiB literals
have been removed, while the default remains 35 KiB. Grep pages within that same
budget. [ARTIFACTS.md](ARTIFACTS.md#shared-tool-result-byte-budget) owns the
configuration, byte measure and per-result handling contract. Source implementation
does not imply a running-service restart or deployment.

Tools without an individual timeout use `DOTAMIND_TOOL_TIMEOUT_SECONDS` (60
seconds by default, finite positive seconds; decimal values are allowed). A
timeout declared by a tool takes precedence. The operation remains bounded by
the original execution deadline and cancellation; a per-tool timeout does not
restart that deadline. Configure the default in the root `.env` or process
environment, with process values taking precedence.

“Not executed” and “executed and failed” describe different facts. The Adapter
now classifies malformed tool-argument JSON and truncated tool-call responses
before a ModelResponse reaches Runtime, preserving the rejected batch; see
[`agent/model_output_and_recovery.md`](agent/model_output_and_recovery.md).
Runtime records the rejected assistant call and one paired, explicitly
non-executed error result per call, then permits at most two corrective
generations for consecutive rejected batches. Rejected calls never invoke
ToolRegistry or become checkpoint evidence. If correction is exhausted, Answer
Stage uses only reliable results already produced in the current request. Valid
JSON with invalid tool fields and checkpoint-source errors keep their existing
per-call rules. Primary answer truncation enters the degraded attempt; degraded
answer truncation reaches deterministic fallback. Both paths are offline-tested;
live Provider compatibility remains unverified.

The clean-slate default registry currently exposes:

```text
artifact.grep
artifact.read
artifact.query
math.calculate
esports.league.search
esports.series.search
esports.series.teams
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
catalog.lookup             # local Valve hero/item names
web.search                 # when Tavily MCP is enabled and discovery succeeds
player.profile             # when a STRATZ token is configured
player.recent_games        # when a STRATZ token is configured
game.detail                # when OpenDota is explicitly enabled
esports.game.resolve       # when game resolution and its required providers are enabled
```

## Local calculation and answer verification

`math.calculate` is registered without Provider configuration. Input contains
`expression`, optional `variables` (default `{}`), and optional `result_unit`
(`"seconds"` or `null`, default `null`). Variables are strict finite numbers or
nonempty numeric lists. Null, booleans, strings, objects/Artifact references,
nested lists and partially missing lists are rejected, never coerced or skipped.

The AST allowlist admits decimal literals, variables, `+ - * /`, parentheses,
unary signs, numeric lists, and `sum/mean/min/max` with one nonempty numeric list.
Powers, modulo, floor division, comparisons, boolean/conditional expressions,
strings, attributes, indexing, comprehensions, arbitrary calls and argument
expansion are rejected. No `eval`, network, file or Artifact access is used.

Internal Decimal arithmetic uses 28 significant digits. Final results have at
most four fractional digits with half-up rounding; trailing zeros are removed,
negative zero becomes zero, and integer results are JSON integers. Success
returns `expression`, `variables`, numeric `result`, `result_unit`, `label`,
`equation`, and boolean `rounded`. The program substitutes variables and retains
parentheses; `equation` uses `≈` if arithmetic or output rounding discarded
nonzero digits, otherwise `=`. This is bounded decimal arithmetic, not
arbitrary-precision exact mathematics.

For `result_unit="seconds"`, `label` formats the final rounded result with the
same signed `MM:SS[.fraction]` function as GameDetail; otherwise it is `null`.
For example `a-b`, with `a=1478`, `b=1010`, returns `468`, `"07:48"` and
`"(1478 - 1010) = 468"`. Unit declaration controls display; it does not validate
dimensions. The tool cannot verify source selection, entity, timestamp, or the
model's subsequent copying. Results do not modify GameDetail.

Bounds: expression 1024 characters, 32 variables, 256 numeric variable values
total, 1–100 values per list, 256 AST nodes, depth 32, substituted expression
8192 characters, and numeric/intermediate magnitudes at most `10^15` with
nonzero magnitudes at least `1e-100`. Unknown variables, division by zero,
unsupported syntax and bounds violations use `invalid_arguments`, with no
partial/null success. Normal registry validation details identify variable paths.
If a rounded fractional result cannot survive JSON-number serialization without
changing its decimal value, return an error rather than a contradictory equation.

Definitions carry a generic `access` property: `external_data` (default),
`local_artifact_read` or `pure_compute`. Answers declare only read-only tools in
the latter two categories; Runtime checks access again before dispatch. Catalog,
guide, Provider and task-state tools remain unavailable during answers.

Answer verification has no total tool-call ceiling and no cumulative result-byte
admission limit. Primary entry, degraded entry and answer tool-loop continuations
use one full-request watermark preflight, with the same capacity rules and atomic
compaction workflow as execution. Deterministic tests cover this behavior; live
model quality remains a separate acceptance step.

Each result must fit the configured shared observation budget (default 35 KiB).
Under the accepted target, tool-owned paging/externalization/narrow-read errors
handle expected large results, then one common exit checks final content in
both stages. Unexpected oversized content becomes a bounded error before entering
model-visible history. This final check is not an additional answer-only quota;
the former hardcoded answer gate has moved to the shared exit.
Identical name/argument calls remain rejected; their request-local record survives
compaction, retries and degraded
attempts. Calls, errors and returned bytes remain observable metrics, not a
cumulative admission quota. Stage deadlines, cancellation, access checks and
existing protocol/failure handling remain in force; compaction or retry must not
restart an attempt's deadline. The existing degraded-stage deadline is unchanged.
Before every execution or answer model request, including requests after answer
tool results, use the same configured full-request high-watermark compaction
policy. The existing no-progress guard and capacity/recovery/fallback paths apply.
See [ARCHITECTURE.md](ARCHITECTURE.md#two-stage-context-governance)
for the unified contract. An expired deadline stops preflight before another
capacity or compaction attempt, preserving its deadline failure reason.

Answer prompts require original-Artifact checks for numerical and summary claims,
exact entity/time/metric/unit matching, and calculator use for arithmetic. Prompt
instructions do not guarantee compliance or correct input selection. Ordinary
history and Trace retain verification calls/results, without Provider retrieval
or task-checkpoint mutation. Artifact-bound calculator variables, result
writeback and automated factual verification remain outside the calculator's
first version. Structured Artifact query is the separate generic capability below.

## Structured Artifact query

`artifact.query(ref, expression, fields, offset=0, limit=20)` selects object
records by exact field conditions and returns requested direct members with
their original record paths. [ARTIFACTS.md](ARTIFACTS.md#structured-query)
owns its complete input/output, JSONPath subset, missing-value, continuation,
error and resource-limit contract. It is registered in the default registry and
available to execution and local answer verification, with deterministic checks.

Use `grep` to discover member-name and scalar-value locations, `read` for known exact paths,
`query` for conditional record selection and multi-field retrieval, and
`math.calculate` for temporary arithmetic from verified inputs. Query reads one
stored Artifact, remains generic, and does not fetch Provider data, infer Dota
semantics, regenerate time labels or alter the stored document. The
access property is `local_artifact_read`; normal execution and bounded answer
verification may use it. Answers follow the same stage permissions,
per-result bounds, deadlines and context governance; query adds no call or
cumulative byte quota.

For Larl's `20:00`, `25:00`, `30:00` samples, an illustrative target expression is:

```text
$.data.players[?@.identity.account_id == 106305042].minute_timeline[?@.time_seconds == 1200 || @.time_seconds == 1500 || @.time_seconds == 1800]
```

Request `time_seconds`, `time_label`, `net_worth`, `experience`, `last_hits` and
`deaths` in `fields`. These are fields of the selected record; the query engine
does not identify or add them automatically. The account predicate uses the
player's actual `identity.account_id` path, not a top-level player member.
Use conditions on source timestamps,
not consecutive list positions or inferred minutes. Exact timestamp absence
produces no matching row, without interpolation. A query result verifies the
selection the model requested, not whether that selection answers the user or
whether the model faithfully copies it. The full single-time request/result
example and missing/null distinctions are in the owner contract.

## Esports search capabilities

The current entity hierarchy is:

```text
Competition entities

League
  ↓
Series
  ↓
Tournament
  ↓
Match
  ↕
Team

Participant entities

Player
  ↓ current team
Team
```

Capability status:

```text
League: implemented
Series: implemented
Tournament: implemented
Tournament rosters: implemented
Match: implemented
Team: implemented
Player: implemented
```

`esports.league.search` resolves a recurring competition identity to its
numeric league ID. Its closed input contains only `id`, `name`, `page`, and
`limit`; a year, season, or edition belongs to a future series capability. Each
result exposes the frozen `LeagueDTO` identity fields `id`, `name`, `slug`, and
`image_url`; nested provider navigation such as `series[]` is not included.

`esports.series.search` resolves a specific edition or season of a league. It
accepts `id`, `league_id`, `name`, `season`, `year`, `winner_id`, `tier`, `page`,
and `limit`, and returns the frozen `SeriesDTO`: series identity, edition,
timing, winner, and tier metadata together with `league_id`. It does not expose
the parent `league{}` object or navigation-only `tournaments[]`; use
`esports.tournament.search(series_id=...)` to find Tournament stages within a
known Series. Source Series names can themselves include qualifiers, regions, or
Play-In stages, so do not infer a strict hierarchy from a name. Use `league_id`
and `year` for a bounded edition lookup; do not re-query a parent when the
available context is sufficient.

`esports.tournament.search` resolves a competition stage within one series. It
accepts `id`, `series_id`, `name`, `page`, and `limit`, and returns a
`TournamentDTO`. Provider `serie_id` is exposed as `series_id`, while the
top-level `league_id` is preserved. Provider `matches[]` is not exposed;
navigate through `esports.match.search(tournament_id=...)` instead. Provider
`teams[]` and `expected_roster[]` are normalized into `participants[]`, whose
`team` is the tournament-level participation identity and whose
`expected_roster` represents tournament-context expected or historical roster
membership. It does not assert an exact starting five or historical `role` or
`active` values. A final may not have a separate Tournament record; locate its
Match from the records and Match details rather than assuming one exists. The
tool does not require a fixed League-to-Series-to-Tournament query sequence.

`esports.series.teams` returns participating team identities for one known
series. It requires `series_id` from `esports.series.search` and accepts
optional `page` and `limit` bounds. Each item is a `TeamRefDTO` containing
`id`, `name`, `acronym`, `location`, `slug`, and `image_url`; `players[]` is not
exposed because series participation is historical while embedded Team players
reflect a current roster snapshot.

Both participant tools use one semantic collection request and inherit the
generic result processor for oversized responses. `TeamDTO.current_roster`
preserves the current membership snapshot while
`TournamentParticipantDTO.expected_roster` remains the historical/expected
tournament-context relation.

`esports.match.search` is a closed semantic match-search capability. Its input
uses `id`, `league_id`, `series_id`, `tournament_id`, `team_id`, `name`,
`winner_id`, `status`, `lifecycle`, `sort`, `page`, and `limit`. It returns a
`MatchDTO`: parent competition objects are represented by IDs only;
`opponents[]` and `results[]` become ordered `participants[]`, `winner{}` is a
`TeamRefDTO`, and `games[]` becomes `MatchGameDTO[]`. A missing provider result
maps to `score=None`, while an explicit provider score of `0` remains `0`. The
schema intentionally does not expose provider query syntax or provider-private
field names. One invocation maps to one bounded provider collection request.
Every successful `esports.match.search` result is stored once as a complete
session Artifact and returns an `artifact_ref`, including empty and small results.
For a response within the configured inline size limit, `value` contains the
complete response only when the added envelope also fits the observation budget.
Larger responses and small responses whose envelopes exceed that budget use the
usual bounded structural observation. Other tools retain their existing size-based
externalization behavior. The stored Artifact records `esports.match.search` as
its producing tool in session metadata, outside the business document.

When `esports.game.resolve` is available, it can continue from this search
Artifact using `match_artifact_ref`, `match_path`, and `game_position`.
`match_path="items.0"` selects the first Match in the stored search document;
`game_position=4` selects source position 4 within that Match. The path is
relative to the stored document even when an inline observation nests results
under `value`, so do not prefix the path with `value.`. If the current observation
is enough to select a Match, continue directly without first calling
`artifact.read`. The resolver validates the producing tool, document, and Match
before extracting its PandaScore ID on the server. Generic `artifact.read` and
`artifact.grep` remain unaware of Match-resolution semantics.

`esports.team.search` resolves a Dota 2 team name, acronym, or exact ID to team
identity. Its closed input contains only `id`, `name`, `acronym`, `page`, and
`limit`; the output is a `TeamDTO` containing `id`, `name`, `acronym`,
`location`, `slug`, `image_url`, and `current_roster`. Provider `players[]` is
normalized into the current roster snapshot. A single provider position maps to
one semantic role, while mixed positions such as PandaScore `"1/2"` map to
multiple roles: `["carry", "mid"]`. This is current Team membership, not a
historical roster. Use `esports.player.search(team_id=...)` when a Player-side
filter or discovery task is needed.

`esports.player.search` resolves professional or real-name player identity and
supports roster discovery through `team_id` and `active`. Its closed input
contains `id`, `team_id`, `name`, `first_name`, `last_name`, `active`, `page`,
and `limit`. The output is a `PlayerDTO` containing `id`, `name`, `active`,
optional semantic `role` values, player identity metadata, and an optional
`current_team` `TeamRefDTO`. Mixed PandaScore positions such as `"1/2"` map
to multiple roles such as `["carry", "mid"]`; `current_team` is a lightweight
current-team reference and does not embed a roster. A missing `current_team`
is valid for a free agent.

## Explicit entity display references (capability injection, answer rendering, and model guidance implemented)

Application composition now attaches a program-generated `display_ref` to
explicit Team objects when the configured local display directory confirms their
PandaScore IDs. The injected paths are `esports.team.search` items,
`esports.series.teams` items, `esports.tournament.search` participant Teams,
`esports.match.search` participant Teams, and non-null
`esports.player.search.current_team` values. It batches each result's distinct
Team references before the generic result processor runs. Provider names and
image URLs remain unchanged; the directory's current snapshot is used only to
confirm identity, not to replace Provider facts. A Team without a local image
still receives a reference, while an absent local Team record leaves the field
null. No reference is inferred from `winner_id` or arbitrary fields.

The same application-level enrichment now attaches Valve references to
`catalog.lookup` entries and `hero.guide` name objects. Catalog references are
limited to found Hero and Item entries; its input remains unchanged and does not
add Ability lookup. Guide references cover `hero_name`, Pub starting items,
progression and situational items, Pub skill abilities, and Pro item/ability
timeline name objects. Enrichment runs after cache reading, Pro position
filtering, section projection, and existing Catalog name resolution, but before
generic result externalization. Only explicitly typed IDs in the returned
result are considered; unknown IDs (including ability ID `0`) receive no
reference. Repeated ability entries remain in their original order.

The shared product prompt tells the model to copy a reference only from the
matching entity object's returned `display_ref`, never to construct one from a
name, acronym, provider ID, or image URL. It recommends sparse use in the final
answer where an image helps identify the entity. The reference is for rendering,
not a tool input or a new lookup capability. Its syntax is owned by
[`agent/product_run_state.md`](agent/product_run_state.md), and the shared records
are owned by [`DATA.md`](DATA.md). Real-model selection and placement quality
remain to be evaluated.

The first version covers Hero, Item, Ability, and Team. A Player entity does not
receive a reference, although a Team already present as a `TeamRefDTO` relation
may. Unknown or unresolved entities receive no fabricated reference. The
reference follows the entity in the result before generic Artifact
externalization; it is not emitted as a separate cross-reference table.

This design adds no image-search or image-insertion tool. Existing provider
`image_url` fields remain source facts and are not model-created display handles.
The Team paths and the Catalog/hero-guide paths described above currently emit
the optional field.

## Optional web search

When Tavily MCP is enabled and startup discovery validates the remote
`tavily_search` input schema, the default registry exposes one local tool:
`web.search`. Its input schema is the discovered remote JSON Schema, passed to
the model and used for local validation without a lossy Pydantic conversion.
Invalid arguments are rejected before opening an MCP session.

Each discovery or search operation uses a fresh Streamable HTTP MCP session and
one bounded timeout. The API key is sent only as an Authorization bearer
header; it is not part of tool arguments, model messages, traces, or sanitized
errors. Startup discovery is explicit and asynchronous. If disabled, missing a
key, or unable to validate the expected tool/schema, search is not registered;
PandaScore capabilities remain available. There is no background rediscovery
or automatic retry.

Successful results preserve the remote tool name, retrieval time, structured
content when supplied, and ordered content blocks. Valid JSON text blocks also
retain their original text alongside a parsed representation. Error results
are never treated as evidence; empty results remain distinguishable from
failures. Unsupported binary blocks are described without embedding their
payload, and linked MCP resources are not fetched. Large outputs continue
through the generic session Artifact externalizer.

Configure the root `.env` or process environment with
`DOTAMIND_TAVILY_MCP_ENABLED=true`, `DOTAMIND_TAVILY_API_KEY`, and optionally
`DOTAMIND_TAVILY_MCP_URL` / `DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS`; environment
variables take precedence over `.env`. Restart the API after configuration
changes. A dry smoke check makes no network request:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m scripts.smoke_tavily_mcp
```

The explicit `--execute` option performs discovery and one bounded search; use
it only when a live provider call is intended.

Future domain tools must be added explicitly with a closed schema and focused
tests; the registry must not grow a universal open selector or deprecated
aliases.

All esports search responses use the envelope `items`, `page`, `limit`, and
`anomalies`. An anomaly is a short, model-visible description of a local
provider mapping problem; normal missing data remains `None` or `[]`. A local
malformed item may be skipped while other valid items are returned. A provider
response with an invalid top-level shape still fails as a protocol error.
Anomaly paths use provider-source locations such as
`provider.items[0].games[2]`, not indexes into the returned DTO collection.

## Artifact tools

`artifact.grep(ref, pattern, offset=0, limit=20)` recursively
searches member names and scalar values in one exact referenced document, using
case-insensitive literal substring matching. It has no search-mode parameter.
Member names match at their own nodes, not as complete path strings. Null and
empty-container fields are discoverable; an ancestor-name match does not repeat
all descendants. Results contain `matches`, `offset`, `limit`, actual `returned`,
`next_offset` and `truncated`; each match contains `ref`, the exact dotted `path`,
`preview` and `value_type`, without `matched_on`. Containers expose only type and
direct item count. Limit defaults to 20 and is at most 100; preview is at most
200 characters. The complete result fits the shared configured observation budget
(default 35 KiB), retaining whole matches. Continue with `next_offset`, which uses
actual returned count; a single match/envelope that cannot fit fails explicitly.

The simplified interface and paging/shared budget are implemented with deterministic
checks. Use grep for discovery, read for exact paths, query for
conditional record selection. The complete contract is owned by
[ARTIFACTS.md](ARTIFACTS.md#retrieval-contract). No new zero-match prompt rule is
part of this target.

`artifact.read` reads one exact reference using an explicit mode:

```text
artifact.read(ref, mode="outline")
  Inspect the root structure when the document shape is unknown.
  Do not provide path, offset, or limit.

artifact.read(ref, mode="read", path=..., offset?, limit?)
  Read one explicit dotted path. Offset and limit slice only a selected list.
```

If a previous tool result provides `_artifact_path`, copy it exactly and use
`mode="read"` directly. The Artifact layer does not fetch providers, infer
business meaning, aggregate rows, resolve identities, or restore a prior turn's
Artifact references into conversation history.

Tool response references are opaque strings. They locate one temporary session
document and are not entity identities. Static manuals, when introduced by a
future capability, must be explicitly allowlisted and use the same generic
read/grep contract.

## Task planning and checkpoints

Task-plan completion/checkpoint order is serial; retrieval may batch or run in
parallel while prioritizing the current item. Do not infer a mandatory parent
lookup chain for esports tools: a known target ID can be used directly by the
capability accepting that ID. League lookup is needed when discovering the
competition identity, not merely because a question mentions a year or edition.

`task.checkpoint` accepts only `key` and `value`. Runtime automatically collects
all eligible, unconsumed observations owned by the current task in the current
request. Without a plan it collects unowned observations. Successful ordinary
results, including externalized results and business outcomes such as `unresolved`,
and successful raw `artifact.read` observations qualify. The presence of an
Artifact reference or preview pointer does not disqualify a result. The result
returns `checkpoint_id`, `key`, and `source_count`; actual source call IDs remain
in internal checkpoint state and Trace, not model-authored input.

`artifact.grep`, task-control results,
errors, deferred materializations, and lifecycle receipts are not checkpoint
sources. Sources must remain in the effective current-request history and may
be consumed only once. Each successful source records its execution-time task
owner; inline ownership is the active task key captured before the tool
execution group starts. For `artifact.read`, an omitted `task_key` uses that
same captured current key, while a known explicit key may be pending, active,
or completed. An unknown key is rejected before the reader runs. With no plan,
the source remains unowned. Task ownership is checkpoint metadata only:
completing an item does not block later Artifact reads or reopen the item, and
a read never infers ownership from the Artifact reference. A checkpoint
consumes its automatically collected source metadata; other observations retain their
original owner and cannot drift into a later task's candidates.

A checkpoint stores model-organized task state and observations obtained while
processing that task, not precise citations proving each conclusion. Success
means that state was accepted and the plan advanced; it does not verify the
business conclusions or guarantee completeness. Checkpointing does not force
externalization, change the configured spill threshold, or release raw results
from conversation history.

With an active plan, `key` must match its current item. Without a plan, a new
checkpoint under the same key replaces the whole earlier value and requires new
eligible observations. Expected key/plan conflicts return `invalid_task_state`
with `reason`, requested/current keys and statuses. No eligible observations
returns `invalid_checkpoint_source`. Either failure saves nothing, consumes no
metadata, and does not advance the plan. Runtime does not rewrite the key or skip
unfinished tasks; genuine internal exceptions remain execution failures.

## Future domain tools

Future resource-shaped guidance may define search, detail, or lookup tools one
capability at a time. Each tool owns its supported fields and output contract;
the Controller must copy names and arguments from the rendered catalog and must
not invent provider-specific parameters. Domain workflows belong to the
capability contract and its tests, not to this generic registry baseline.

## `hero.guide` cache query

The input and DTO contract for `hero.guide(hero_id, position, section)` is
defined in `app.vnext.capabilities.hero.guide`. The application registers this
tool only when `DOTAMIND_DATA_DIR` selects the shared file cache. Without that
setting the tool is not registered; Redis is not a guide-cache fallback. A
missing or invalid file partition does not fall back to Redis. The
public input, section values, Pub/Pro boundaries, and DTO remain unchanged.
`hero_id` is a strict positive
integer, `position` is a strict integer from 1 through 5, and `section` is one
of `all`, `items`, `skills`, or `pro_examples` (default `all`). The input does
not accept a name, provider/source selector, URL, or refresh flag.

`HeroGuideResult` combines `pub_guides[]` and `pro_examples[]` with independent
`pub_metadata` and `pro_metadata`. The DTO records Pub builds, starting-item
options, item observations, skill sequences, and talents; Pro examples expose
source match identity, optional position and its basis, and ordered item/ability
events. It also includes `hero_name` and `catalog_version`; returned item entries
and Pro item/ability events carry a `resolved_name`, while each Pub skill
sequence carries an `abilities[]` list in exact correspondence with `ability_ids`.
Raw statistics stay in source JSON objects. DTO construction does not
filter sections, compute totals, rank/truncate candidates, or pair Pub item and
skill candidates.

Source metadata can represent available, empty, or missing data, and can retain
stale available data alongside a last refresh error. Retrieval and attempt times
require timezones; the source `updated_at` remains an unparsed string. The D2PT
HTTP client, pure Pub/Pro parsers, `FileHeroGuideCache`, `HeroGuideService`, and
`hero.guide` tool are implemented. With `DOTAMIND_DATA_DIR`, the API reads the
file partitions from that same directory used by the Catalog loader. The Service
reads both partitions once per query, never refreshes on a
miss, and does not expose the raw body or complete source rows. File reads do not
cache contents or write, repair, or refresh files, so an atomic replacement is
visible on the next query.
The cache has no TTL, keeps the last successful snapshot after a failed attempt,
and remains independent of session Artifacts.

The query reads Pub by hero plus position and Pro by hero, then filters Pro
examples to the exact requested hero and position. It reports `missing` when no
snapshot exists, `empty` when the successful snapshot has no matching candidates,
and `available` otherwise. Data is stale at or beyond 36 hours, or after a
refresh failure; section projection does not change status or totals. Totals are
pre-projection hero-position counts. A single cache read error returns the other
source when available; two read errors become a fixed `tool_execution_error`
with per-source safe codes. Large outputs use the existing generic Artifact
externalization and can be explored with `artifact.read` or `artifact.grep`.
After filtering and section projection, the Service uses its injected local
`EntityNameResolver` to add Valve catalog labels to only the visible IDs. It
resolves the requested hero even when both cache partitions are missing and
returns the catalog snapshot version as `catalog_version`. Duplicate occurrences remain
in source order and each receives an independent name object. ID zero stays
`unknown` with empty names; unknown IDs do not remove events or skill entries.
This enrichment runs at query time and is not written into guide snapshots. It
does not call the separate `catalog.lookup` tool. Names identify the local Valve
catalog, not D2PT or OpenDota source fields. When `DOTAMIND_DATA_DIR` is
configured, each query creates its resolver from the active snapshot before the
first cache read and keeps it for that query; without the setting it uses the
bundled catalog repository.
The operator-only command `python -m app.vnext.data_updates refresh-guides`
invokes the serial refresher with `FileHeroGuideCache`; the daily `refresh-all`
task uses the same file-backed guide path. Neither is a model-facing tool or HTTP
endpoint. `migrate-guides` remains an operator-only one-time importer for legacy
Redis snapshots. A model cannot trigger refresh or migration, or perform
entity-ID mapping; cache misses remain ordinary missing-source results. The
existing generic Artifact externalization and retrieval contract is unchanged.

## Steam player and game-detail tools

`player.profile` and `player.recent_games` are the implemented STRATZ-backed
Steam32 capabilities. Both register only when `DOTAMIND_STRATZ_TOKEN` is
configured. The profile query accepts an exact unsigned Steam32 account ID; it
does not accept names, SteamID64 values, or PandaScore player IDs. Its source
object is retained as JSON. `retrieved_at` records when DotaMind fetched the
response, not when STRATZ last updated the profile.

`player.recent_games(steam_account_id, limit=5)` returns at most 20 source
records. It requests `PlayerType.matches` with `take=limit`, `orderBy: DESC`,
and `playerList: SINGLE`; the historical schema inventory describes this as
date-descending order and a single row for the requested SteamAccountId. The
adapter validates the outer account and each returned player-row identity,
requires usable match IDs/timestamps, rejects duplicate IDs or malformed rows,
and locally sorts only after the provider has selected the bounded subset.
`valve_game_id` comes from STRATZ `MatchType.id` and composes with the existing
`GameDetailInput`. One live spot check for `8960882635` matched STRATZ and
OpenDota IDs, start time, and duration. A raw query for one participant
returned 20 rows newest-first, with only that account in each row; the supplied
match predates the bounded sample. This single-account result is not a general
provider-availability guarantee.

`game.detail(valve_game_id)` reads one existing OpenDota match by Valve single-
game ID. It registers only when `DOTAMIND_OPENDOTA_ENABLED=true`; the base URL
defaults to `https://api.opendota.com/api`, the API key is optional, and the
finite request timeout defaults to 20 seconds. Configure these with
`DOTAMIND_OPENDOTA_BASE_URL`, `DOTAMIND_OPENDOTA_API_KEY`, and
`DOTAMIND_OPENDOTA_TIMEOUT_SECONDS`. The key is sent as the `api_key` query
parameter and is excluded from settings/client representations and tool errors.
The endpoint follows the [OpenDota matches API documentation](https://docs.opendota.com/#tag/matches);
OpenDota's [API tier announcement](https://blog.opendota.com/2018/04/17/changes-to-the-api/)
describes public free-tier use without a key. Composition and registry creation
do not make provider calls. Process environment variables take precedence over
the root `.env`.

The input is a Valve single-game ID, not a PandaScore Match, Series, or Game ID.
It may come from the user, `player.recent_games`, or a resolved
`esports.game.resolve` result.

**Current implementation:** the governed eight-section DTO is returned in
`data` and passed to generic Artifact externalization. Complete validated source
records remain internal. The tool binds to `GameDetailService`,
which constructs its public result from an internal `OpenDotaGameRecord` read.
The resolver consumes the internal record directly. Both use the same adapter
and client, but changing the public result no longer changes the resolver's
record type. No extra HTTP read is introduced by the Service.

**Output contract:** keep the input and match provenance envelope, then return
the eight-section `data` DTO defined in
[`agent/game_detail_data.md`](agent/game_detail_data.md). The OpenDota source
identity is validated before projection. The result Artifact contains the
complete governed DTO, with no raw-object field or model-facing way to retrieve
the original response. Generic `artifact.read` and `artifact.grep` remain
ordinary document operations.

The DTO includes English/Chinese entity names at typed hero, item,
ability, and event-unit fields, so reading a game does not require an explicit
`catalog.lookup` call just to decode IDs or source unit/item keys. It retains
canonical IDs, converts internal keys exactly using local data, and records one
`catalog_version` and `unit_mapping_version` in the result envelope. Event types
use fixed verified business enums. Unmapped keys/codes remain scalar evidence
only in `coverage`; unknown entities or names do not erase known match facts.
This enrichment and the public DTO switch are implemented and tested offline.
They do not change the Catalog tool input, introduce unit lookup as a new model tool,
or add image/display behavior.

The DTO keeps source absence distinct from zero and empty values, and a missing
field does not show that an event did not happen. The lookup does not request
replay parsing. Large results continue to use generic Artifact externalization
and narrower `artifact.read` paths. Deterministic coverage uses local HTTP
mocks. The prior live cross-check for `8960882635` supports the ID mapping for
that observed match only; this implementation has not yet been tested against
live OpenDota.

`esports.game.resolve` keeps complete candidate detail reads internal and exposes
only resolution evidence in its Artifact. It cannot be used as a separate route
to retrieve those raw details. This boundary is implemented; the `game.detail`
public DTO switch is also implemented. The evidence contract and checks are tracked in
[`DATA.md`](DATA.md) and [`EVALS.md`](EVALS.md).

The public tool validates the closed DTO after conversion. Unknown source
extensions and previous raw player/build paths are not retrievable from its
Artifact. The model reads the needed DTO sections through ordinary generic
Artifact paths, with names already attached to their entities.

The `game.detail` tool description states the stable interpretation of its
governed fields: `data.match.match_date` is the `Asia/Shanghai` calendar date,
`data.match.score` contains Radiant/Dire hero-kill counts rather than series game
wins, and `data.economy.radiant_gold_adv` must not be relabeled as net-worth
difference. These semantics remain owned by the game-detail data contract.

`catalog.lookup(kind, ids)` resolves up to 20 exact positive hero or item IDs
against the active local Valve Dota 2 catalog snapshot. It returns each requested
ID as `found` or `unknown`, optional English/Chinese display labels, and the
snapshot version. With `DOTAMIND_DATA_DIR` unset, it uses the bundled snapshot;
when configured, it uses the file-backed snapshot managed by the API loader. Each
lookup captures one repository and uses it for all IDs and version metadata.
These names are local catalog labels, not fields returned by STRATZ or OpenDota;
unknown IDs remain unknown. The standalone lookup does not mutate a stored
detail or make network requests. The detail Service performs local
enrichment independently during DTO construction, before Artifact storage.

For an account-to-game workflow, use `player.profile` only when profile data is
requested, and query `player.recent_games` directly when a Steam32 account is
provided only to ask about recent games. Fetch `game.detail` only for the
selected game, passing its `valve_game_id` unchanged. Identify the account's
player row by exact `account_id`; a name, hero, team, or slot is not a substitute.
For ordinal follow-ups such as “the second game”, use the earlier list retained
in the conversation rather than refreshing and changing its order. If that
list is unavailable, ask to retrieve or clarify it instead of guessing.
Describe explicit statistics as facts, interpretations as interpretations, and
missing evidence as unknown. A scoreboard cannot establish when or why an event
happened, and absent timeline or purchase data does not prove that the event or
purchase did not occur.

`found=false` means only that the profile response did not contain a usable
profile object; it does not establish that the account is absent or has no Dota
2 history. An empty recent-games list is valid, and fewer rows than requested
does not prove history completeness. An empty player row is preserved as such
and cannot support claims about that player's hero, result, or performance in
the game. Missing statistics remain missing, and the tool does not derive win
rates or other aggregates. The game-detail adapter rejects unusable or
mismatched source detail rather than returning an empty successful result.
Reading existing game data does not submit a replay for parsing.

## Esports game-resolution capability (opt-in product registration implemented)

The existing `esports.match.search` stores its complete logical response in a
session Artifact and records `esports.match.search` as storage metadata.
`esports.game.resolve` continues from that Artifact. Product composition registers
it only when `DOTAMIND_GAME_RESOLUTION_ENABLED=true`,
`DOTAMIND_OPENDOTA_ENABLED=true`, and `DOTAMIND_PANDASCORE_TOKEN` is non-empty.
The OpenDota API key remains optional. Startup composition performs no provider
probe. Its closed input is:

```text
esports.game.resolve(match_artifact_ref, match_path, game_position)
```

`match_artifact_ref` must identify a document in the current session store,
`match_path` must be exactly `items.<non-negative integer>`, and
`game_position` is a strict positive integer identifying the source Game
position, not a Game ID or array index. The path chooses a Match in the stored
search document; the position independently chooses a Game within that Match.
Do not add the inline envelope's `value.` prefix to `match_path`. The continuation
verifies the producing tool from Artifact store metadata, validates the complete
document as a `MatchSearchResult`, selects the requested Match, and extracts its
strict positive ID on the server. It does not trust a source field embedded in
the document. The model cannot pass
a provider-private Match ID, a handcrafted Match object, team dictionaries,
timestamps, time windows, or read budgets.

The existing `GameResolutionService.resolve(match_id, game_position,
confirmed_mappings=...)` calls the bounded Provider once with its configured read
policy. The Provider obtains trusted Match context and finite OpenDota search
data; the Service only converts the read attempt and its outcome. Composition
reuses the PandaScore client and the same OpenDota game-detail adapter for both
resolution reads and the `GameDetailService` behind `game.detail`. The resolver
uses internal `get_game_record(match_id)` results rather than public detail DTOs.
The continuation passes an empty mapping.
Duplicate assignment and mapping reuse across separate tool calls, and
whole-Match consistency, are therefore not guaranteed.

The initial read policy defaults to 1,800 seconds start-time tolerance, 5 seconds
duration tolerance, at most 20 League candidates, 8 candidate details, and 30
total logical adapter reads (including cache hits). Configure it with
`DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS`,
`DOTAMIND_GAME_RESOLUTION_DURATION_TOLERANCE_SECONDS`,
`DOTAMIND_GAME_RESOLUTION_MAX_LEAGUES`,
`DOTAMIND_GAME_RESOLUTION_MAX_CANDIDATE_DETAILS`, and
`DOTAMIND_GAME_RESOLUTION_MAX_REQUESTS`. These are adjustable request bounds,
not validated accuracy or coverage targets. Runtime's default 60-second tool
timeout and the original execution deadline still apply; the request budget does
not guarantee that every permitted read finishes before the deadline.

`DOTAMIND_GAME_RESOLUTION_MAX_CONCURRENCY` defaults to 4; set it to 1 for serial
reads. Each resolution reads Match context and the League directory before its
dependent phases. League-list reads run concurrently within one phase, followed
by concurrent candidate-detail reads only after every selected list has completed.
Each phase checks its full logical request budget before starting. Workers retain
source order in the collected result; a failure stops queued work, cancels and
joins active siblings, and preserves the original structured error/cancellation.
The bound applies per resolution call, not across all API users.

Within one product Runtime request, successful validated Match context, League
directory/list reads, and OpenDota game records are reused. `game.detail` can
project a record already read by resolution without another remote fetch. Each
game still receives full independent identity checks over the selected scope.
The cache is internal, returns independent copies with original record timestamps,
and is released at request completion or cancellation; it is not an Artifact or
a cross-request cache. Failed reads are not cached. The public `requests_started`
count remains logical reads; source-read logs distinguish remote attempts from hits.

The implemented internal capability result is `EsportsGameResolutionResult`:

| Field | Meaning |
|---|---|
| `status` | `resolved` or `unresolved` |
| `game_position` | The selected positive position |
| `valve_game_id`, `method` | Present only for a confirmed cross-source identity |
| `reason` | Closed unresolved category; absent for a resolved identity |
| `providers` | Sources whose reads returned successfully, in read order |
| `retrieved_at` | Completion time of the internal read attempt, with timezone |
| `data` | Request/stage/read-count metadata and existing target, League-selection, and resolution results; excludes internal raw source collections |

Unresolved reasons distinguish `match_not_found`, target-game failures,
`insufficient_signals`, `insufficient_context`, `no_league_candidates`,
`no_candidates`, `ambiguous`, `evidence_insufficient`, `mapping_conflict`,
`no_acceptable_candidate`, and `search_scope_incomplete`. Budget exhaustion is a
stable `tool_execution_error` with `budget_exhausted` details; it is not returned
as an unresolved success. Provider structured errors and cancellation propagate.
An invalid internal attempt raises a contract error.

Only `status="resolved"` confirms `valve_game_id` as the selected Game's identity
and makes it valid input to `game.detail`. For `status="unresolved"`, inspect the
reason and evidence; do not select a candidate ID yourself. The complete
resolution evidence is saved in the returned Artifact. This tool confirms
identity and may fetch candidate game details as evidence. It does not
automatically invoke the `game.detail` tool. The Artifact retains selection
results, timing differences, participant/winner comparisons, team-to-side
associations, and unresolved reasons. It excludes the complete Match context,
League catalog, League match lists, and candidate detail bodies. Selected
Game/League source records already carried by matching evidence remain visible.
Request game facts separately with `game.detail(valve_game_id)` after confirmation.

The resolver confirms identity only:

```text
esports.game.resolve → valve_game_id → model may call game.detail
```

It does not return a complete game report, and `game.detail` does not gain a
PandaScore ID input. The tool always stores the complete resolution result once
through generic Artifact externalization and returns the normal inline or bounded
observation. It does not add a resolution-specific Artifact type. The tool is
absent from the default inventory unless the opt-in setting and all required
services are present. The evidence rules and known source limitations are owned by
[`DATA.md`](DATA.md) and
[`reference/opendota-cross-source-identity.md`](reference/opendota-cross-source-identity.md).
