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

Input accepts a resource, normal lifecycle scope, native `filter`, `search`,
`range`, `sort`, and bounded pagination. Unsupported fields and scopes return
structured errors. Small results retain their complete source-shaped row
dictionaries. Large results return a bounded structural preview, `total_rows`,
and a fresh opaque `artifact:tool:*` string to the complete logical response;
use `artifact.read` or `artifact.grep` with that exact ref to inspect omitted
fields. This does not alter the source query or provider request.

Do not reintroduce a search-engine abstraction, a universal search DTO, or
scenario-specific query plumbing while the new seam is pending.

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
PandaScore query manuals are exposed as static read-only artifacts; start with
`manual:pandascore:index` and read the relevant resource ref from that index.
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
