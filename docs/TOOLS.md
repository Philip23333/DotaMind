# Tools

## Design rules

Agent-visible tools describe broad observation capabilities, not provider
endpoints or a provider ontology. A tool result remains source-attributed, while
complete provider documents stay outside model context as Artifacts.

Tool descriptions state a capability; they do not prescribe a fixed workflow.

## Current implemented surface

| Tool | Purpose | Target disposition |
| --- | --- | --- |
| `game.detail` | Fetch one detailed recorded game by canonical Valve game ID | Retain |
| `artifact.grep` | Generic stored-document breadth search | Retain |
| `artifact.read` | Generic stored-document depth read | Retain |

The default Agent runtime exposes exactly these three tools. Historical
`esports.search`, `artifact.search`, `matches.get_detail`, `teams.*`, and
`players.*` modules remain migration code but are not model-visible.

## Esports discovery

The previous `esports.search` implementation (kind-based unified search over
League, Series, Tournament, Match, Team, Player) has been removed in the vNext
cleanup phase. It is being replaced by a PandaScore-oriented agent tool seam;
the new schema is not implemented yet.

The seam is designed as an agent-facing capability layer:

- The model is responsible for understanding user intent, selecting entity
  types, and composing multiple tool calls; it never talks to provider APIs.
- The tool is responsible for a stable discovery interface, mapping requests to
  data providers, and normalizing provider responses.
- Provider-specific fields, endpoints, pagination, and private IDs stay inside
  provider implementations. The PandaScore HTTP client remains at
  `app/vnext/providers/pandascore/` below the future capability boundary.
- The tool does not attempt to solve complete user tasks; complex workflows
  are completed through multiple tool calls.

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
  artifact_ref    game_detail:1:<valve_game_id>
  facts           bounded observation
```

The Artifact is a complete validated OpenDota-shaped source document with
`artifact_type="game_detail"` and `schema_version="1"`. This capability does
not produce a GameSummary. It has no provider selector, source match ID,
field-selection, include, scope, or event-context input.

`provider_error` means OpenDota could not fetch, validate, or confirm the
requested Valve ID. `artifact_error` means the complete detail document could
not be stored; there is no partial-success detail result.

## Artifact tools

| Tool | Purpose | Boundary |
| --- | --- | --- |
| `artifact.grep` | Schema-neutral scalar search | Returns ArtifactRef, path, and bounded preview |
| `artifact.read` | Bounded structural read | Exact ArtifactRef/path; no provider semantics |

Artifacts are a generic JSON-like corpus. `artifact.read` and `artifact.grep`
must not learn PandaScore, OpenDota, Team, Player, or gameplay-scenario logic.
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
