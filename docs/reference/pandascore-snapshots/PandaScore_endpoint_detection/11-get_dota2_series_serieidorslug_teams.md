# get_dota2_series_serieidorslug_teams

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** List Dota 2 teams for a serie
- **Method:** GET
- **API path:** `/dota2/series/{serie_id_or_slug}/teams`
- **Requested path:** `/dota2/series/{serie_id_or_slug}/teams`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_teams.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List teams for the Dota 2 videogame for a given serie
> ℹ️  
> 
> This endpoint is available to all customers

## Path Parameters

| name | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| serie_id_or_slug | one of: integer, string | yes | A serie ID or slug | — |

## Query Parameters

### filter

| field | type | description | constraints |
| --- | --- | --- | --- |
| acronym | array<string> | — | minItems=1 |
| id | array<integer> | — | minItems=1 |
| location | array<string> | — | minItems=1 |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| videogame_id | array<integer; enum: 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| acronym | string | — | — |
| location | string | The team's organization location | — |
| name | string | The name of the team. | — |
| slug | string | — | minLength=1; pattern=^[a-z0-9_-]+$ |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| acronym | array<string> | — | minItems=2; maxItems=2 |
| id | array<integer> | — | minItems=2; maxItems=2 |
| location | array<string> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| acronym | acronym | -acronym | Use `-` prefix for descending order. |
| id | id | -id | Use `-` prefix for descending order. |
| location | location | -location | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| videogame_id | videogame_id | -videogame_id | Use `-` prefix for descending order. |

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
     --url 'https://api.pandascore.co/dota2/series/{serie_id_or_slug}/teams' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 teams

```json
[
  {
    "acronym": null,
    "current_videogame": {
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    },
    "dark_mode_image_url": null,
    "id": 137457,
    "image_url": null,
    "location": "PE",
    "modified_at": "2025-10-01T00:53:54Z",
    "name": "Chicleteira Bicicleteira",
    "players": [
      {
        "active": true,
        "age": null,
        "birthday": null,
        "first_name": null,
        "id": 62052,
        "image_url": null,
        "last_name": null,
        "modified_at": "2025-10-01T00:53:53Z",
        "name": "DIABLO ROJO",
        "nationality": null,
        "role": null,
        "slug": "diablo-rojo"
      }
    ],
    "slug": "chicleteira-bicicleteira"
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| acronym | string | yes | — | nullable |
| current_videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | yes | — | nullable |
| dark_mode_image_url | string; format: uri | yes | URL of the team logo | nullable |
| id | integer | yes | The ID of the team. | minimum=1 |
| image_url | string; format: uri | yes | URL of the team logo | nullable |
| location | string | yes | The team's organization location | nullable |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | The name of the team. | — |
| players | array<object> | yes | — | — |
| slug | string | yes | — | minLength=1; pattern=^[a-z0-9_-]+$; nullable |

## Resource Relationships

| field | JSON type | endpoint-local description |
| --- | --- | --- |
| players | array<object> | — |

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:50.506274Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
