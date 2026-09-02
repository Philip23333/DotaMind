<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# Serie

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
| end_at | `string` | yes |  | date-time |
| id | `integer` | yes |  |  |
| league_id | `integer` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| season | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| videogame_title | `array<one of: integer, string>` | yes |  |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |
| year | `integer` | yes |  |  |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| name | `string` | no |  |  |
| season | `string` | no |  |  |
| slug | `string` | no |  |  |
| winner_type | `string` | no | Player, Team |  |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| begin_at | `string` | yes |  | date-time |
| end_at | `string` | yes |  | date-time |
| id | `integer` | yes |  |  |
| league_id | `integer` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| season | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| winner_id | `array<unknown>` | yes |  |  |
| winner_type | `string` | yes | Player, Team |  |
| year | `integer` | yes |  |  |

## Sort fields

### all scopes

- `begin_at`
- `end_at`
- `id`
- `league_id`
- `modified_at`
- `name`
- `season`
- `slug`
- `winner_id`
- `winner_type`
- `year`

Prefix a field with `-` for descending order.

## Special routes

None.

## Query examples

```json
{
  "resource": "serie",
  "filter": {
    "league_id": 4106,
    "year": 2026
  }
}
```

## Important limitations

Serie supports both `league_id` and `year` filter fields, which can be used together to identify a league edition.
