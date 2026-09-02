<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# Player

## Supported scopes

- `all`

## Filter fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| active | `boolean` | no |  |  |
| birthday | `string` | yes |  |  |
| first_name | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| last_name | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| nationality | `string` | yes |  |  |
| role | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| team_id | `integer` | yes |  |  |
| videogame_id | `integer` | yes | 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35 |  |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| birthday | `string` | no |  |  |
| first_name | `string` | no |  |  |
| last_name | `string` | no |  |  |
| name | `string` | no |  |  |
| nationality | `string` | no |  |  |
| role | `string` | no |  |  |
| slug | `string` | no |  |  |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| birthday | `string` | yes |  |  |
| first_name | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| last_name | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| nationality | `string` | yes |  |  |
| role | `string` | yes |  |  |
| slug | `string` | yes |  |  |

## Sort fields

### all scopes

- `birthday`
- `first_name`
- `id`
- `last_name`
- `modified_at`
- `name`
- `nationality`
- `role`
- `slug`
- `videogame_id`
- `team_id`

Prefix a field with `-` for descending order.

## Special routes

None.

## Query examples

```json
{
  "resource": "player",
  "search": {
    "name": "..."
  }
}
```

## Important limitations

Use only the fields listed above for the selected scope.
