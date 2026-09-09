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
esports.series.teams
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
`esports.tournament.search(series_id=...)` for tournament stages. Use
`league_id` and `year` for a bounded edition lookup.

`esports.tournament.search` resolves a competition stage within one series. It
accepts `id`, `series_id`, `name`, `page`, and `limit`, and returns a
`TournamentDTO`. Provider `serie_id` is exposed as `series_id`, while the
top-level `league_id` is preserved. Provider `matches[]` is not exposed;
navigate through `esports.match.search(tournament_id=...)` instead. Provider
`teams[]` and `expected_roster[]` are normalized into `participants[]`, whose
`team` is the tournament-level participation identity and whose
`expected_roster` represents tournament-context expected or historical roster
membership. It does not assert an exact starting five or historical `role` or
`active` values.

`esports.series.teams` returns participating team identities for one known
series. It requires `series_id` from `esports.series.search` and accepts
optional `page` and `limit` bounds. Each item is a `TeamRefDTO` containing
`id`, `name`, `acronym`, `location`, `slug`, and `image_url`; `players[]` is not
exposed because series participation is historical while embedded Team players
reflect a current roster snapshot.

`esports.match.search` is a closed semantic match-search capability. Its input
uses `id`, `league_id`, `series_id`, `tournament_id`, `team_id`, `name`,
`winner_id`, `status`, `lifecycle`, `sort`, `page`, and `limit`. It returns a
`MatchDTO`: parent competition objects are represented by IDs only;
`opponents[]` and `results[]` become ordered `participants[]`, `winner{}` is a
`TeamRefDTO`, and `games[]` becomes `MatchGameDTO[]`. A missing provider result
maps to `score=None`, while an explicit provider score of `0` remains `0`. The
schema intentionally does not expose provider query syntax or provider-private
field names. One invocation maps to one bounded provider collection request. If
its complete validated response exceeds the inline bound, the generic registry
result processor stores that response as an Artifact and returns a bounded
observation instead.

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

Both participant tools use one semantic collection request and inherit the
generic result processor for oversized responses. `TeamDTO.current_roster`
preserves the current membership snapshot while
`TournamentParticipantDTO.expected_roster` remains the historical/expected
tournament-context relation.

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
