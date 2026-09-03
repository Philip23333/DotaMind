# Tools

## Design rules

Agent-visible tools describe broad observation capabilities, not provider
endpoints or a provider ontology. A tool result remains source-attributed, while
oversized complete tool responses stay outside model context as temporary Artifacts.

Tool descriptions state a capability; they do not prescribe a fixed workflow.

## Current implemented surface

| Tool | Purpose | Target disposition |
| --- | --- | --- |
| `esports.search` | Search PandaScore-backed Dota 2 esports resources with validated native query fields | Retain |
| `game.detail` | Fetch one detailed recorded game by canonical Valve game ID | Retain |
| `artifact.grep` | Generic stored-document breadth search | Retain |
| `artifact.read` | Generic stored-document depth read | Retain |

The default Agent runtime exposes exactly these four tools. Historical
`artifact.search`, `matches.get_detail`, `teams.*`, and `players.*` modules
remain migration code but are not model-visible.

## Esports discovery

The previous `esports.search` implementation (kind-based unified search over
League, Series, Tournament, Match, Team, Player) was removed in the vNext
cleanup phase. The replacement is a PandaScore-oriented agent tool seam.

The seam is designed as an agent-facing capability layer:

- The model is responsible for understanding user intent, selecting entity
  types, and composing multiple tool calls; it never talks to provider APIs.
- The tool is responsible for a stable discovery interface, validation against
  generated capabilities, and one native PandaScore collection request.
- Provider-specific fields, endpoints, pagination transport syntax, and private
  IDs stay inside provider implementations. The PandaScore HTTP client remains
  at `app/vnext/providers/pandascore/` below the capability boundary.
- The tool does not attempt to solve complete user tasks; complex workflows
  are completed through multiple tool calls.

Input accepts a resource, lifecycle scope, native `filter`, `search`, `range`,
`sort`, and bounded pagination. Their meanings are distinct:

- `filter` is native exact filtering, commonly for IDs, relationships, and exact
  values; `search` is provider text-search and is not a substitute for it.
- `range` and `sort` only accept fields supported by the selected resource.
  Sort uses `field` for ascending and `-field` for descending; `field desc` is
  invalid.
- `scope` selects a provider lifecycle endpoint; it does not mean “recent”.
- `page_size` is the provider-side row count for this call. Keep it small when a
  task needs only a few results.

Fields are resource-specific: do not invent fields or transfer a field from one
resource to another. Unsupported fields and scopes return structured errors.
Small results retain their complete source-shaped row dictionaries. Large
results return a bounded structural preview, `returned_rows`, and a fresh opaque
`artifact:tool:*` string to the complete logical response. `returned_rows` is
always the row count in that call's complete logical response, while `has_more`
says whether the provider has a later page. `truncated=true` means only the model-facing
preview was bounded, not that provider rows are missing. Use the returned
`_artifact_path` directly as `artifact.read(mode="read", path=...)` with that
exact ref. This does not alter the source query or provider request.

Do not reintroduce a search-engine abstraction, a universal search DTO, or
scenario-specific query plumbing while the new seam is pending.

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

### Search patterns and completion

The production agent receives three reusable search shapes, not a fixed
workflow: recent league matches use league discovery followed by a confirmed
match relation; `past` uses `sort=["-begin_at"]`, `upcoming` uses
`sort=["begin_at"]`, and `running` uses the running scope where sorting is
usually unnecessary. Keep the page size small and stop once enough recent
matches are supported. A specific edition or stage resolves league -> serie ->
tournament -> match; latest tournament status resolves the current edition and
stage, then reads only enough key matches to answer. These patterns contain no
provider-specific IDs and do not require a full history or bracket
reconstruction.

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
multi-row calculations. Answers must not be more specific than their evidence.

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
explicit dotted path. Offset and limit slice a selected list, never the whole
response.
PandaScore query manuals are exposed as static read-only artifacts under
`manual:pandascore:*`.
The historical GameSummary-specific `artifact.search` tool is not model-visible;
exact recorded-game retrieval uses `game.detail(valve_game_id)`.

## Rejected shapes

- separate League/Series/Tournament/Match/Team model tools;
- a `pandascore.*` model-facing namespace;
- a model-facing source-navigation locator for esports discovery;
- provider-specific Artifact read or grep helpers;
- an `artifact.produce` tool;
- a workflow prompt that forces a particular discovery sequence;
- a universal search DTO that merges provider-specific entity schemas.
