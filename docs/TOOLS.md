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
| `matches.get_detail` | Transitional locator-based detail bridge | Replace with `game.detail` |
| `teams.search` / `teams.get_detail` | Transitional Team discovery and detail | Keep only until the replacement path is accepted |
| `players.search` / `players.get_detail` | Transitional Player discovery and detail | Keep only until the replacement path is accepted |
| `artifact.search` | Exact stored-Artifact availability lookup | Retain |
| `artifact.grep` | Generic stored-document breadth search | Retain |
| `artifact.read` | Generic stored-document depth read | Retain |

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

This does not make `game` an `esports.search` kind. The target `game.detail`
capability accepts the canonical Valve ID when recorded-game facts are needed.
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

## Artifact tools

| Tool | Purpose | Boundary |
| --- | --- | --- |
| `artifact.search` | Exact stored-document availability lookup | Does not fetch or produce a document |
| `artifact.grep` | Schema-neutral scalar search | Returns ArtifactRef, path, and bounded preview |
| `artifact.read` | Bounded structural read | Exact ArtifactRef/path; no provider semantics |

Artifacts are a generic JSON-like corpus. `artifact.read` and `artifact.grep`
must not learn PandaScore, OpenDota, Team, Player, or gameplay-scenario logic.

## Rejected shapes

- separate League/Series/Tournament/Match/Team model tools;
- a `pandascore.*` model-facing namespace;
- a model-facing source-navigation locator for `esports.search`;
- provider-specific Artifact read or grep helpers;
- an `artifact.produce` tool;
- a workflow prompt that forces a particular discovery sequence.
