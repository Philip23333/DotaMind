# Cross-source Valve match resolution

## Scope

Phase 2 maps one resolved PandaScore Game to one OpenDota/Valve match. It does
not add a database mapping table, scrape webpages, call paid PandaScore detail
routes, or provide STRATZ fallback.

## Inputs and outputs

`dota.resolve_valve_match` accepts only these declared references:

```text
pandascore.resolve_competition.data.competition
pandascore.resolve_match_game.data.resolution_input
```

The result exposes explicit IDs:

```text
data.match.valve_match_id
data.match.opendota_league_id
data.match.opendota_series_id
data.mapping
```

`data.mapping.method` is `inferred_cross_source`; it records
`candidate_count`, `matched_on`, and start/duration deltas. It must not be
described as a native PandaScore Valve field.

## Deterministic matching

1. Normalize spacing, punctuation, and case; match competition name plus exact
   year to one OpenDota league.
2. Resolve both teams through the existing OpenDota team resolver. If a name is
   ambiguous, query each candidate's `/teams/{team_id}/matches` records and use
   exact `leagueid == target league id` participation as the only disambiguator.
   Exactly one participating candidate resolves with `league_participation`;
   zero or multiple participating candidates remain `ambiguous_team`.
3. Fetch `/leagues/{league_id}/matches` through `OpenDotaTransport` and require
   unordered team-ID equality, start delta at most 1800 seconds, duration delta
   at most 5 seconds, series position by sorted start time, and winner
   consistency when a winner is available.
4. Return `resolved` only for exactly one candidate. Zero candidates returns
   `not_found`; multiple candidates returns `ambiguous_match`.

The tolerances are configured by
`policy.cross_source_match_resolution` and are hard filters, not weighted
scoring or closest-match fallback.

## Statuses and evidence

The resolver can return `resolved`, `league_not_found`, `ambiguous_league`,
`team_not_found`, `ambiguous_team`, `insufficient_signals`, `not_found`, or
`ambiguous_match`. Only `resolved` with positive IDs emits the mandatory
`cross_source_match_mapping` and `valve_match_identity` evidence. Downstream
OpenDota summary/draft tools may then consume the declared Valve ID reference.

## Known sample and live verification

For PandaScore Series 10828 / Match 1631694 / Game 738652, the known OpenDota
candidate is Valve `8943244303` (league `19719`, series `1130066`). The current
OpenDota team catalogue returns two equally scored `Nigma Galaxy` candidates,
but only team `10136357` has Team Matches with exact `leagueid=19719`; team
`7554697` has no participation in that league. The live resolver therefore
returns `resolved`, with `resolution_method=league_participation`, eight league
matches for team `10136357`, and `team_league_participation` in `matched_on`.
The final Valve ID still comes from the complete league-match hard filters.
