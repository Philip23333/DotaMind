<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# Team

## Supported scopes

- `all`

## Filter fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| location | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| videogame_id | `integer` | yes | 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35 |  |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | no |  |  |
| location | `string` | no |  |  |
| name | `string` | no |  |  |
| slug | `string` | no |  |  |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| location | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |

## Sort fields

### all scopes

- `acronym`
- `id`
- `location`
- `modified_at`
- `name`
- `slug`
- `videogame_id`

Prefix a field with `-` for descending order.

## Special routes

### Teams by serie

Path: `/dota2/series/{serie_id_or_slug}/teams`

Path parameters:

- `serie_id_or_slug`: integer|string, required

This route lists teams for a specific serie.

#### Filter fields

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| location | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| videogame_id | `integer` | yes | 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35 |  |

#### Search fields

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | no |  |  |
| location | `string` | no |  |  |
| name | `string` | no |  |  |
| slug | `string` | no |  |  |

#### Range fields

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| acronym | `string` | yes |  |  |
| id | `integer` | yes |  |  |
| location | `string` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |

#### Sort fields

- `acronym`
- `id`
- `location`
- `modified_at`
- `name`
- `slug`
- `videogame_id`

Prefix a field with `-` for descending order.

## Query examples

```json
{
  "resource": "team",
  "search": {
    "name": "Team Spirit"
  }
}
```

## Important limitations

Use only the fields listed above for the selected scope.
