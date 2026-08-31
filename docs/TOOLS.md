# Tools

## Design rules

Agent-visible tools describe broad observation capabilities, not provider
endpoints or a provider ontology. A tool result remains source-attributed, while
complete provider documents stay outside model context as Artifacts.

Tool descriptions state a capability; they do not prescribe a fixed workflow.

## Current implemented surface

| Tool | Purpose | Target disposition |
| --- | --- | --- |
| `esports.search` | Discover one selected kind of professional Dota 2 esports entity | Retain |
| `game.detail` | Fetch one detailed recorded game by canonical Valve game ID | Retain |
| `artifact.grep` | Generic stored-document breadth search | Retain |
| `artifact.read` | Generic stored-document depth read | Retain |

The default Agent runtime exposes exactly these four tools. Historical
`artifact.search`, `matches.get_detail`, `teams.*`, and `players.*` modules
remain migration code but are not model-visible.

## `esports.search`

Purpose: search professional Dota 2 esports entities by one requested kind.
PandaScore is its current implementation, not a model-facing namespace.

```text
kind        required DotaMind vocabulary: league | series | tournament | match | team | player
query       optional complete-source-document text discovery
teams       optional Match-only team constraints, interpreted with AND semantics
time_scope  optional: upcoming | running | past; Series/Tournament/Match only
limit       1..50
```

The input intentionally has no `within`, `SourceLocator`, provider selector,
sort/order, pagination, `recent`, `all`, or `game` kind.

A successful response is:

```text
records[]
  source
  kind
  artifact_ref
  facts
truncated
partial
warnings[]
  code
  source
  kind
```

`facts` is a bounded structural observation. It does not contain provider-private
identity values. `artifact_ref` is always present and points to the complete
validated source document. Use generic Artifact tools for deeper reads.

For Series, Tournament, and Match lifecycle requests, the selected PandaScore
lifecycle endpoint is authoritative; its rows are not rejected by a second
status filter. `query` matches the complete source business document, so it is
not narrowed to PandaScore `search[name]`. Match Team constraints first require
one exact source Team identity per supplied name: not-found or ambiguous identity
resolution is `invalid_arguments`; no shared Match after successful resolution
is normal empty success.

### Match results

A Match Artifact preserves the provider's complete Match document. Each item in
`facts.games[]` additionally has:

```text
valve_game_id  canonical Valve/OpenDota match ID when resolved, otherwise null
resolution     deterministic resolution status
```

This does not make `game` an `esports.search` kind. `game.detail` accepts the
canonical Valve ID when recorded-game facts are needed.
If the OpenDota-dependent enrichment is unavailable, Match discovery still
returns the PandaScore document; each game reports `valve_game_id=null` and
`resolution="unavailable"` rather than pretending it was not found.

### Partial Artifact delivery

When one or more final documents are stored, a response remains successful. It
contains only records with valid ArtifactRefs plus `partial=true` and sanitized
warnings with `code`, `source`, and `kind`. `artifact_error` is reserved for the
case where no final document could be stored.

### Errors

- `invalid_arguments`: invalid kind/limit or a cross-field violation such as
  `teams` with `kind="team"`.
- `provider_error`: PandaScore discovery, validation, or another non-degradable
  Provider failure cannot satisfy a valid request.
- `artifact_error`: no final complete source document could be stored.

`records=[]` is normal success. `truncated=true` means more qualifying records
may exist than the Provider scan or final limit returned.

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
- a model-facing source-navigation locator for `esports.search`;
- provider-specific Artifact read or grep helpers;
- an `artifact.produce` tool;
- a workflow prompt that forces a particular discovery sequence.
