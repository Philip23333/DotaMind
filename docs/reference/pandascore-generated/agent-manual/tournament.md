<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# Tournament

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
| country | `string` | yes |  |  |
| detailed_stats | `boolean` | no |  |  |
| end_at | `string` | yes |  | date-time |
| has_bracket | `boolean` | no |  |  |
| id | `integer` | yes |  |  |
| live_supported | `boolean` | no |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| prizepool | `string` | yes |  |  |
| region | `string` | yes | AF, ASIA, EEU, ME, NA, OCE, SA, WEU |  |
| serie_id | `integer` | yes |  |  |
| slug | `string` | yes |  |  |
| tier | `string` | yes | a, b, c, d, s, unranked |  |
| videogame_title | `array<one of: integer, string>` | yes |  |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| country | `string` | no |  |  |
| name | `string` | no |  |  |
| prizepool | `string` | no |  |  |
| region | `string` | no | AF, ASIA, EEU, ME, NA, OCE, SA, WEU |  |
| slug | `string` | no |  |  |
| tier | `string` | no | a, b, c, d, s, unranked |  |
| winner_type | `string` | no | Player, Team |  |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| begin_at | `string` | yes |  | date-time |
| country | `string` | yes |  |  |
| detailed_stats | `boolean` | yes |  |  |
| end_at | `string` | yes |  | date-time |
| has_bracket | `boolean` | yes |  |  |
| id | `integer` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| prizepool | `string` | yes |  |  |
| region | `string` | yes | AF, ASIA, EEU, ME, NA, OCE, SA, WEU |  |
| serie_id | `integer` | yes |  |  |
| slug | `string` | yes |  |  |
| tier | `string` | yes | a, b, c, d, s, unranked |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |

## Sort fields

### all scopes

- `begin_at`
- `country`
- `detailed_stats`
- `end_at`
- `has_bracket`
- `id`
- `modified_at`
- `name`
- `prizepool`
- `region`
- `serie_id`
- `slug`
- `tier`
- `winner_id`
- `winner_type`

Prefix a field with `-` for descending order.

## Special routes

None.

## Query examples

```json
{
  "resource": "tournament",
  "filter": {
    "serie_id": 10828,
    "name": "Group Stage"
  }
}
```

## Important limitations

Tournament supports `serie_id` as a filter field.

Tournament does not support `league_id` as a filter field.

Tournament does not support `year` as a filter field.

If those constraints are known at league or edition level, obtain the corresponding serie ID before querying tournaments by `serie_id`.
