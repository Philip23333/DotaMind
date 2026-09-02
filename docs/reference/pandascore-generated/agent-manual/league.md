<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# League

## Supported scopes

- `all`

## Filter fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| id | `integer` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| url | `string` | yes |  | uri |


## Search fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| name | `string` | no |  |  |
| slug | `string` | no |  |  |
| url | `string` | no |  | uri |


## Range fields

The following fields are supported by all scopes:

| Field | Type | Multiple | Enum | Format |
| --- | --- | --- | --- | --- |
| id | `integer` | yes |  |  |
| modified_at | `string` | yes |  | date-time |
| name | `string` | yes |  |  |
| slug | `string` | yes |  |  |
| url | `string` | yes |  | uri |

## Sort fields

### all scopes

- `id`
- `modified_at`
- `name`
- `slug`
- `url`

Prefix a field with `-` for descending order.

## Special routes

None.

## Query examples

```json
{
  "resource": "league",
  "search": {
    "name": "The International"
  }
}
```

## Important limitations

League does not support a `year` filter.
