# Tools

## Design rules

Agent-visible tools describe broad observation capabilities, not provider
endpoints or a provider ontology. A tool result remains source-attributed, while
oversized complete tool responses stay outside model context as temporary Artifacts.

Tool descriptions state a capability; they do not prescribe a fixed workflow.

## Current temporary model-visible surface

| Tool | Purpose | Target disposition |
| --- | --- | --- |
| `game.detail` | Fetch one detailed recorded game by canonical Valve game ID | Retain |
| `artifact.grep` | Generic stored-document breadth search | Retain |
| `artifact.read` | Generic stored-document depth read | Retain |

The default Agent runtime currently exposes exactly these three tools.
The legacy `esports.search` implementation remains available to isolated tests
and internal migration code, but is not registered or model-visible.

## Target esports surface

The target model-facing esports surface is six resource-shaped tools:

```text
esports.league.search
esports.serie.search
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
```

These tools are not implemented or registered yet. Their closed resource
schemas will be defined in the next migration phase from the generated
PandaScore capabilities. Historical `artifact.search`, `matches.get_detail`,
`teams.*`, and `players.*` modules remain migration code and are not
model-visible.

## Legacy `esports.search` (internal migration)

The current `esports.search` implementation is a temporary universal resource
selector over PandaScore resources. It is retained internally so its native
executor, capabilities, observations, Artifact behavior, and isolated tests
remain usable during migration. It is not part of the default Agent registry
and is not the target model-facing contract.

The seam is designed as an agent-facing capability layer:

- Internal callers may use the implementation for capability validation against
  generated capabilities and one native PandaScore collection request.
- Provider-specific fields, endpoints, pagination transport syntax, and private
  IDs stay inside provider implementations. The PandaScore HTTP client remains
  at `app/vnext/providers/pandascore/` below the capability boundary.

Do not treat this universal selector as the target API. The target resource
tools will expose only their own closed, resource-specific vocabularies.

For internal migration tests, the legacy input accepts a resource, lifecycle
scope, native `filter`, `search`, `range`, `sort`, and bounded pagination. Their
meanings are distinct:

- `filter` is native exact filtering, commonly for IDs, relationships, and exact
  values; `search` is provider text-search and is not a substitute for it.
- `range` and `sort` only accept fields supported by the selected resource.
  Sort uses `field` for ascending and `-field` for descending; `field desc` is
  invalid.
- `scope` selects a provider lifecycle endpoint; it does not mean “recent”.
  `past` is the provider's past collection, not necessarily `status="finished"`;
  match results can include canceled or other non-finished records. Use a
  supported status/finished filter when completed results are required. Scope
  does not replace resource-specific status/date filters or sorting.
- `page_size` is the provider-side row count for this call. Keep it small when a
  task needs only a few results.

Fields are resource-specific: do not invent fields or transfer a field from one
resource to another. Unsupported fields and scopes return structured errors.
Small results retain their complete source-shaped row dictionaries. Large
results return a bounded structural preview, `returned_rows`, and a fresh opaque
`artifact:tool:*` string to the complete logical response. `returned_rows` is
always the row count in that call's complete logical response, while `has_more`
says whether the provider has a later page. `truncated=true` means the
model-facing response is only a bounded preview: inline rows are not necessarily
all returned rows, so do not infer totals or exhaustive claims from them. Use
`artifact_ref` and any returned `_artifact_path` to inspect the complete result
before making such claims. `truncated=false` means the logical result is
represented completely inline. Use the returned `_artifact_path` directly as
`artifact.read(mode="read", path=...)` with that exact ref.

Do not expand this legacy selector or use it to define a universal search DTO.

### Query discipline

Direct discovery means only `resource`, `search.name`, default `scope`, and an
optional small `page` or `page_size`. If `filter`, `range`, `sort`, non-default
`scope`, a resource relation, or any other `search` field is present, it is not
direct discovery. `search.name` is the only search field allowed for direct
discovery. Any other resource-specific `search` field, `filter`, `range`,
`sort`, non-default `scope`, or resource relation must already be established
for that resource by the current conversation or a successful tool result.
Otherwise, it reads `manual:pandascore:<resource>` before the search.

The static `manual:pandascore:*` refs are a known contract: do not read their
outline. Read `path="content"` directly with `artifact.read(mode="read")`.

After `unsupported_field` or `unsupported_scope`, the agent must not retry the
same idea with another operator; it reads the corresponding resource manual
first. `manual:pandascore:index` only discovers available manuals, while a
resource manual decides its actual query fields. Manuals decide what query is
legal; `_artifact_path` values inspect data returned by a previous tool call.

### Search patterns and completion (future agent guidance)

Future resource-shaped agent guidance may reuse three search shapes, not a
fixed workflow: recent league matches use league discovery followed by a
confirmed match relation; `past` uses `sort=["-begin_at"]`, `upcoming` uses
`sort=["begin_at"]`, and `running` uses the running scope where sorting is
usually unnecessary. Keep the page size small and stop once enough recent
matches are supported. If broad recent-match rows are dominated by null
`begin_at`, canceled/non-relevant records, or unrelated qualifiers, do not widen
the page: reuse explicit `serie` or `tournament` IDs already returned to narrow
to the most relevant recent coherent edition/stage. A specific edition or stage
resolves league -> serie -> tournament -> match; latest tournament status
resolves the current edition and stage, then reads only enough key matches to
answer. These patterns contain no provider-specific IDs and do not require a
full history or bracket reconstruction.

Before every additional call, the agent checks whether the requested answer is
already supported by collected evidence. It stops once the target and requested
freshness/scope are established with enough evidence for the intended claims.

### Evidence discipline

An explicit `winner` or `winner_id` establishes the winning entity ID. Naming
the winning team or player requires an explicit collected identity mapping for
that ID; never resolve a raw ID from model knowledge. Exact series scores
require explicit results or scores and cannot be inferred from
`number_of_games`, match format, or winner alone. Team/opponent and game-level
claims require their respective explicit evidence. `artifact.grep` locates
known text or paths; it is not an aggregation engine for standings or other
multi-row calculations. Relative-time wording such as “just finished”,
“currently”, “today”, or “recently” requires explicit timestamps relative to
the current request time. Preserve source stage labels; do not relabel Playoffs,
Group Stage, qualifier, or another stage without explicit supporting evidence.
Answers must not be more specific than their evidence.

## `game.detail`

Purpose: fetch detailed facts for one recorded Dota game identified by its Valve
game ID.

```text
input
  valve_game_id  required, positive integer

result
  source
  valve_game_id
  artifact_ref    artifact:tool:<uuid4-hex> | null
  facts           complete inline facts or bounded observation
```

When oversized, the complete logical tool response is held in the current chat
session and `facts` becomes a bounded observation. This capability does not
produce a GameSummary. It has no provider selector, source match ID,
field-selection, include, scope, or event-context input.

`provider_error` means OpenDota could not fetch, validate, or confirm the
requested Valve ID. `artifact_error` means the complete detail document could
not be stored; there is no partial-success detail result.

## Artifact tools

| Tool | Purpose | Boundary |
| --- | --- | --- |
| `artifact.grep` | Schema-neutral scalar search | Requires one exact temporary-tool or documented manual ref |
| `artifact.read` | Explicit outline or bounded path read | Requires one exact ref and `mode="outline"` or `mode="read"`; path is required only for read mode |

Artifacts are session-local JSON-like documents, not a corpus. `artifact.read`
and `artifact.grep` must not learn PandaScore, OpenDota, Team, Player, or
gameplay-scenario logic. Both accept an exact string ref returned by another
tool; manual refs remain documented static allowlist entries.
`artifact.read` uses `outline` only for root structure and `read` only for an
explicit dotted path. Choose the narrowest useful read granularity: read one
nested value such as `rows.3.results` when one value is needed; when several
adjacent rows are needed, read the parent collection such as `rows` once with
`offset`/`limit` rather than issuing many sibling reads. The stored artifact
contains the complete logical response, so a parent row/list read can expose
data replaced by `_artifact_path` pointers in the bounded preview. Offset and
limit slice a selected list, never the whole response.
PandaScore query manuals are exposed as static read-only artifacts under
`manual:pandascore:*`.
The historical GameSummary-specific `artifact.search` tool is not model-visible;
exact recorded-game retrieval uses `game.detail(valve_game_id)`.

## Rejected shapes

- a universal `esports.search` with an open `resource` selector and shared
  filter/search/range vocabulary as the target API;
- provider-named `pandascore.*` model-facing namespace;
- a model-facing source-navigation locator for esports discovery;
- provider-specific Artifact read or grep helpers;
- an `artifact.produce` tool;
- a workflow prompt that forces a particular discovery sequence;
- a universal search DTO that merges provider-specific entity schemas.
