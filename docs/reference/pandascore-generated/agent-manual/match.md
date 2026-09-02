<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# Match

## Supported scopes

- `all`
- `past`
- `running`
- `upcoming`

## Filter fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| begin_at | `string` | yes |  | date-time |
| detailed_stats | `boolean` | no |  |  |
| draw | `boolean` | no |  |  |
| end_at | `string` | yes |  | date-time |
| finished | `boolean` | no |  |  |
| forfeit | `boolean` | no |  |  |
| future | `boolean` | no |  |  |
| id | `integer` | yes |  |  |
| league_id | `integer` | yes |  |  |
| match_type | `string` | yes | all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| not_started | `boolean` | no |  |  |
| number_of_games | `integer` | yes |  |  |
| opponent_id | `array<one of: one of: integer, string, one of: integer, string>` | yes |  |  |
| opponents_filled | `boolean` | no |  |  |
| past | `boolean` | no |  |  |
| running | `boolean` | no |  |  |
| scheduled_at | `string` | yes |  | date-time |
| serie_id | `integer` | yes |  |  |
| slug | `string` | yes |  |  |
| status | `string` | yes | canceled, finished, not_started, postponed, running |  |
| tournament_id | `integer` | yes |  |  |
| unscheduled | `boolean` | no |  |  |
| videogame | `array<one of: integer; enum: 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, string; enum: cod-mw, cs-go, dota-2, e-basketball, e-cricket, e-hockey, e-soccer, fifa, kog, league-of-legends, lol-wild-rift, mlbb, ow, pubg, r6-siege, rl, starcraft-2, starcraft-brood-war, valorant>` | yes |  |  |
| videogame_title | `array<one of: integer, string>` | yes |  |  |
| videogame_version | `array<one of: string, unknown; enum: all, unknown; enum: latest>` | yes |  |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| match_type | `string` | no | all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground |  |
| name | `string` | no |  |  |
| slug | `string` | no |  |  |
| status | `string` | no | canceled, finished, not_started, postponed, running |  |
| winner_type | `string` | no | Player, Team |  |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| begin_at | `string` | yes |  | date-time |
| detailed_stats | `boolean` | yes |  |  |
| draw | `boolean` | yes |  |  |
| end_at | `string` | yes |  | date-time |
| forfeit | `boolean` | yes |  |  |
| id | `integer` | yes |  |  |
| match_type | `string` | yes | all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| number_of_games | `integer` | yes |  |  |
| scheduled_at | `string` | yes |  | date-time |
| slug | `string` | yes |  |  |
| status | `string` | yes | canceled, finished, not_started, postponed, running |  |
| tournament_id | `integer` | yes |  |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |

## Sort fields

### all scopes

- `begin_at`
- `detailed_stats`
- `draw`
- `end_at`
- `forfeit`
- `id`
- `match_type`
- `modified_at`
- `name`
- `number_of_games`
- `scheduled_at`
- `slug`
- `status`
- `tournament_id`
- `winner_id`
- `winner_type`

Prefix a field with `-` for descending order.

## Special routes

None.

## Query examples

```json
{
  "resource": "match",
  "scope": "past",
  "filter": {
    "tournament_id": 21698
  },
  "search": {
    "name": "Grand Final"
  }
}
```

## Important limitations

Matches can be narrowed using `league_id`, `serie_id`, or `tournament_id`. Use the narrowest identifier already known.
