# get_dota2_leagues

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** Get Dota 2 leagues
- **Method:** GET
- **API path:** `/dota2/leagues`
- **Requested path:** `/dota2/leagues`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_leagues.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List Dota2 leagues
> ℹ️  
> 
> This endpoint is available to all customers

## Path Parameters

None documented.

## Query Parameters

### filter

| field | type | description | constraints |
| --- | --- | --- | --- |
| id | array<integer> | — | minItems=1 |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| url | array<string; format: uri> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| name | string | — | — |
| slug | string | — | minLength=1; pattern=^[a-z0-9:_-]+$ |
| url | string; format: uri | — | — |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| id | array<integer> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |
| url | array<string; format: uri> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| id | id | -id | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| url | url | -url | Use `-` prefix for descending order. |

### pagination

| parameter | type | default | constraints | description |
| --- | --- | --- | --- | --- |
| page | one of: integer, object | — | — | Pagination in the form of `page=2` or `page[size]=30&page[number]=2` |
| per_page | integer | 50 | minimum=1; maximum=100; default=50 | Equivalent to `page[size]` |

### other query parameters

None documented.

## Request Example

Official curl example:

```curl
curl --request GET \
     --url 'https://api.pandascore.co/dota2/leagues' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 leagues

```json
[
  {
    "id": 4873,
    "image_url": null,
    "modified_at": "2022-09-25T07:46:22Z",
    "name": "Fall Festival Tournament",
    "series": [
      {
        "begin_at": "2022-09-24T14:00:00Z",
        "end_at": null,
        "full_name": "2022",
        "id": 5105,
        "league_id": 4873,
        "modified_at": "2022-09-28T12:04:12Z",
        "name": null,
        "season": "",
        "slug": "dota-2-fall-festival-tournament-fall-2022",
        "winner_id": null,
        "winner_type": null,
        "year": 2022
      }
    ],
    "slug": "dota-2-fall-festival-tournament",
    "url": null,
    "videogame": {
      "current_version": null,
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    }
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| id | integer | yes | — | minimum=1 |
| image_url | string; format: uri | yes | — | nullable |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | — | — |
| series | array<object> | yes | — | — |
| slug | string | yes | — | minLength=1; pattern=^[a-z0-9:_-]+$ |
| url | string; format: uri | yes | — | nullable |
| videogame | one of: object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object | yes | — | — |

## Resource Relationships

| field | JSON type | endpoint-local description |
| --- | --- | --- |
| series | array<object> | — |
| videogame | one of: object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object | — |

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:36.726028Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
