# Tools

## Design rules

Agent-visible tools describe stable observation capabilities, not transport
endpoints or provider implementation details. Large complete responses remain
outside model context as temporary Artifacts and are explored through generic
Artifact tools. The default registry automatically externalizes an oversized
non-Artifact result and returns only a bounded structural observation together
with its opaque Artifact reference; Artifact retrieval tools remain inline.

The clean-slate default registry currently exposes:

```text
artifact.grep
artifact.read
esports.league.search
esports.series.search
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
```

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
Match: implemented
Team: implemented
Player: implemented
```

`esports.league.search` resolves a recurring competition identity to its
numeric league ID. Its closed input contains only `id`, `name`, `page`, and
`limit`; a year, season, or edition belongs to a future series capability. The
result intentionally exposes only each league's `id` and `name` so the ID can
be passed to a later capability.

`esports.series.search` resolves a specific edition or season of a league. It
accepts `id`, `league_id`, `name`, `season`, `year`, `page`, and `limit`, and
returns edition identity and timing fields together with an optional parent
league summary. Use `league_id` and `year` for a bounded edition lookup.

`esports.tournament.search` resolves a competition stage within one series. It
accepts `id`, `series_id`, `name`, `page`, and `limit`, and returns the semantic
`series_id` together with stage timing. Provider-private `serie_id` is not part
of the model-facing contract.

`esports.match.search` is a closed semantic match-search capability. Its input
uses `id`, `league_id`, `series_id`, `tournament_id`, `team_id`, `name`,
`lifecycle`, `sort`, `page`, and `limit`. The schema intentionally does not
expose provider query syntax or provider-private field names. One invocation
maps to one bounded provider collection request. If its complete validated
response exceeds the inline bound, the generic registry result processor stores
that response as an Artifact and returns a bounded observation instead.

`esports.team.search` resolves a Dota 2 team name, acronym, or exact ID to team
identity. Its closed input contains only `id`, `name`, `acronym`, `page`, and
`limit`; the output contains `id`, `name`, `acronym`, and `location`. Provider
roster fields are intentionally omitted. Use `esports.player.search` with the
known team ID for player discovery.

`esports.player.search` resolves professional or real-name player identity and
supports roster discovery through `team_id` and `active`. Its closed input
contains `id`, `team_id`, `name`, `first_name`, `last_name`, `active`, `page`,
and `limit`. The output includes player identity, active status, optional
nationality and role, and an optional `current_team` summary. A missing
`current_team` is valid for a free agent.

Both participant tools use one semantic collection request and inherit the
generic result processor for oversized responses. `Team.players` is not copied
into `esports.team.search`; use `esports.player.search(team_id=...)` instead.

Future domain tools must be added explicitly with a closed schema and focused
tests; the registry must not grow a universal open selector or deprecated
aliases.

## Artifact tools

`artifact.grep` searches case-insensitive literal text in one exact opaque
Artifact reference. `artifact.read` reads one exact reference using an explicit
mode:

```text
artifact.read(ref, mode="outline")
  Inspect the root structure when the document shape is unknown.
  Do not provide path, offset, or limit.

artifact.read(ref, mode="read", path=..., offset?, limit?)
  Read one explicit dotted path. Offset and limit slice only a selected list.
```

If a previous tool result provides `_artifact_path`, copy it exactly and use
`mode="read"` directly. The Artifact layer does not fetch providers, infer
business meaning, aggregate rows, or resolve identities.

Tool response references are opaque strings. They locate one temporary session
document and are not entity identities. Static manuals, when introduced by a
future capability, must be explicitly allowlisted and use the same generic
read/grep contract.

## Future domain tools

Future resource-shaped guidance may define search, detail, or lookup tools one
capability at a time. Each tool owns its supported fields and output contract;
the Controller must copy names and arguments from the rendered catalog and must
not invent provider-specific parameters. Domain workflows belong to the
capability contract and its tests, not to this generic registry baseline.
