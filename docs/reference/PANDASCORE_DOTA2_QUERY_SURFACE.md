# PandaScore Dota 2 collection query surface

Recorded: 2026-09-05

Status: reference only. This document records provider capabilities discovered during the
vNext esports tool rebuild. It does **not** change the current model-facing schemas and
should not be treated as a request to expose every provider field to the LLM.

## Why this exists

The vNext tools intentionally expose closed semantic contracts while PandaScore exposes a
much larger transport/query surface. This note preserves the provider-side facts so future
schema expansion can be based on known capabilities plus real agent traces instead of
rediscovering the API.

Current design rule remains:

```text
provider supports a field
        !=
model-facing tool should expose that field
```

Only add semantic fields when a concrete product or agent-eval need is demonstrated.

## Sources and confidence

Primary endpoint behavior was checked against PandaScore's current public API reference:

- https://developers.pandascore.co/reference/get_dota2_leagues
- https://developers.pandascore.co/reference/get_dota2_series
- https://developers.pandascore.co/reference/get_dota2_tournaments
- https://developers.pandascore.co/reference/get_dota2_matches
- https://developers.pandascore.co/docs/filtering-and-sorting
- https://developers.pandascore.co/docs/pagination

The public endpoint pages confirm that these collection endpoints support `filter`,
`range`, `sort`, `search`, pagination, and `per_page` up to 100. They expose the number of
sort enum values but do not always render every nested field in easily inspectable text.

Field lists below were expanded from PandaScore's generated SDK schema reference on
liblab. Treat the generated SDK pages as useful provider-schema evidence, but re-check the
current PandaScore reference before widening a production tool contract.

## Common PandaScore query semantics

PandaScore's collection query model uses provider syntax such as:

```text
filter[field]=value
search[field]=value
range[field]=...
sort=field
sort=-field
page=...
per_page=...
```

General behavior:

- `filter` performs strict equality filtering.
- `search` performs text-oriented search on supported fields.
- `range` selects values within provider-supported ranges.
- positive sort field means ascending; a `-` prefix means descending.
- collection page size is capped at 100.

These names are provider transport syntax and should remain inside adapters rather than
being copied directly into model-facing schemas.

## `/dota2/leagues`

Official collection endpoint:

```text
GET /dota2/leagues
```

Official reference reports 10 sort enum values.

### Filter fields

Generated Dota 2 league filter schema exposes:

```text
id
modified_at
name
slug
url
```

### Search fields

```text
name
slug
url
```

### Range fields

```text
id
modified_at
name
slug
url
```

### Current vNext semantic subset

`esports.league.search` currently exposes only:

```text
id
name
page
limit
```

No immediate gap was observed that justifies adding league sorting, slug, URL, or
modified-at querying.

## `/dota2/series`

Official collection endpoint:

```text
GET /dota2/series
```

Official reference reports 22 sort enum values.

### Filter fields

Generated Dota 2 series filter schema exposes:

```text
begin_at
end_at
id
league_id
modified_at
name
season
slug
videogame_title
winner_id
winner_type
year
```

`videogame_title` is present in the generated shared schema but is documented there as
applicable only to other videogame endpoint families, not Dota 2. Do not expose it for the
Dota 2 tool based on this generated type alone.

### Search fields

```text
name
season
slug
winner_type
```

### Range fields

```text
begin_at
end_at
id
league_id
modified_at
name
season
slug
winner_id
winner_type
year
```

### Current vNext semantic subset

`esports.series.search` currently exposes:

```text
id
league_id
name
season
year
page
limit
```

It currently does **not** expose sort.

A real agent trace attempted:

```json
{
  "league_id": 4106,
  "sort": "begin_at_desc"
}
```

and the call was rejected by the closed semantic schema, even though the provider endpoint
supports sorting. This is a confirmed future optimization candidate, not a change requested
by this document.

If later added, the smallest justified semantic form is likely:

```text
begin_at_asc  -> sort=begin_at
begin_at_desc -> sort=-begin_at
```

Do not expose the entire provider sort surface merely because it exists.

## `/dota2/tournaments`

Official collection endpoint:

```text
GET /dota2/tournaments
```

Official reference reports 30 sort enum values.

### Filter fields

Generated Dota 2 tournament filter schema exposes:

```text
begin_at
detailed_stats
end_at
has_bracket
id
live_supported
modified_at
name
prizepool
serie_id
slug
tier
videogame_title
winner_id
winner_type
```

`videogame_title` is again documented in the generated type as belonging to other game
endpoint families and should not be treated as a Dota 2 capability.

### Search fields

```text
name
prizepool
slug
tier
winner_type
```

### Range fields

```text
begin_at
detailed_stats
end_at
has_bracket
id
modified_at
name
prizepool
serie_id
slug
tier
winner_id
winner_type
```

### Current vNext semantic subset

`esports.tournament.search` currently exposes:

```text
id
series_id
name
page
limit
```

Provider-private `serie_id` is intentionally translated inside the adapter:

```text
series_id -> filter[serie_id]
```

No current trace requires tournament sort or additional tournament filters.

## `/tournaments/{tournament_id}/rosters`

Tournament roster endpoint:

```text
GET /tournaments/{tournament_id}/rosters
```

The vNext capability is `esports.tournament.rosters`. It returns the
tournament-time roster associated with the requested tournament stage, not the
team's current contracted-player list and not an exact per-match lineup.
`team_id` is an optional DotaMind-side deterministic filter applied after the
complete endpoint response is normalized. A missing team match returns an
empty result rather than a not-found claim.

## `/dota2/matches`

Official collection endpoint:

```text
GET /dota2/matches
```

The same query family is also available on lifecycle-specific collections such as
`/past`, `/running`, and `/upcoming`. The official reference reports 32 sort enum values.

### Filter fields

Generated Dota 2 match filter schema exposes:

```text
begin_at
detailed_stats
draw
end_at
finished
forfeit
future
id
league_id
match_type
modified_at
name
not_started
number_of_games
opponent_id
opponents_filled
past
running
scheduled_at
serie_id
slug
status
tournament_id
unscheduled
videogame
videogame_title
videogame_version
winner_id
winner_type
```

Generated-schema caveats:

- `videogame_title` is documented there as only applicable to other endpoint families.
- `videogame_version` is documented there as applicable to Valorant/LoL rather than Dota 2.

### Search fields

```text
match_type
name
slug
status
winner_type
```

### Range fields

```text
begin_at
detailed_stats
draw
end_at
forfeit
id
match_type
modified_at
name
number_of_games
scheduled_at
slug
status
tournament_id
winner_id
winner_type
```

### Current vNext semantic subset

`esports.match.search` currently exposes:

```text
id
league_id
series_id
tournament_id
team_id
name
lifecycle
sort = begin_at_asc | begin_at_desc
page
limit
```

Current adapter translations include:

```text
series_id -> filter[serie_id]
team_id   -> filter[opponent_id]
```

and semantic lifecycle routing to the corresponding collection endpoint.

The current restricted match schema remains appropriate until agent evals demonstrate a
need for additional status, winner, time-range, or detailed-stats filters.

## Pagination metadata available from PandaScore

PandaScore collection responses expose pagination information in response headers:

```text
Link       -> first / previous / next / last links when applicable
X-Page     -> current page
X-Per-Page -> current page length
X-Total    -> total item count
```

This means future result-contract work could derive values such as `has_more` or `total`
without issuing a second provider request. This is a reference observation only; no current
result schema is changed by this document.

## Snapshot comparison with current vNext schemas

| Tool | Current semantic inputs | Provider capabilities not currently exposed |
| --- | --- | --- |
| `esports.league.search` | `id`, `name`, `page`, `limit` | sort, range, modified-at, slug, URL |
| `esports.series.search` | `id`, `league_id`, `name`, `season`, `year`, `page`, `limit` | sort, time filters/ranges, winner fields, slug |
| `esports.tournament.search` | `id`, `series_id`, `name`, `page`, `limit` | sort, time filters/ranges, tier, winner, live/bracket flags, prizepool |
| `esports.tournament.rosters` | `tournament_id`, optional `team_id` | provider roster fields outside the normalized tournament-time roster contract |
| `esports.match.search` | IDs, `team_id`, `name`, `lifecycle`, begin-at sort, pagination | many status/time/winner/stat filters and broader sorting |

## Current decision

The provider query inventory remains reference-only. The roster capability is a
separate closed semantic contract and does not expose the provider's broader
roster payload or relationship-query syntax.

The discovery result should be used later as a provider-capability reference. Future
expansion should still require a concrete trace or product need and should add the
smallest semantic subset required by that need.
