# get_dota2_series_running

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** Get running Dota 2 series
- **Method:** GET
- **API path:** `/dota2/series/running`
- **Requested path:** `/dota2/series/running`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_series_running.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List running Dota 2 series
> ℹ️  
> 
> This endpoint is available to all customers

## Path Parameters

None documented.

## Query Parameters

### filter

| field | type | description | constraints |
| --- | --- | --- | --- |
| begin_at | array<string; format: date-time> | — | minItems=1 |
| end_at | array<string; format: date-time> | — | minItems=1 |
| id | array<integer> | — | minItems=1 |
| league_id | array<integer> | — | minItems=1 |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| season | array<string> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| videogame_title | array<one of: integer, string> | A videogame title id or slug. Only for `/csgo/*`, `/codmw/*`, `/fifa/*` and `/ow/*` endpoints | minItems=1 |
| winner_id | array<unknown> | — | minItems=1 |
| winner_type | array<string; enum: Player, Team> | — | minItems=1 |
| year | array<integer> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| name | string | — | — |
| season | string | — | — |
| slug | string | — | minLength=1; pattern=^[a-z0-9_-]+$ |
| winner_type | string; enum: Player, Team | — | — |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| begin_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| end_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| id | array<integer> | — | minItems=2; maxItems=2 |
| league_id | array<integer> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| season | array<string> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |
| winner_id | array<unknown> | — | minItems=2; maxItems=2 |
| winner_type | array<string; enum: Player, Team> | — | minItems=2; maxItems=2 |
| year | array<integer> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| begin_at | begin_at | -begin_at | Use `-` prefix for descending order. |
| end_at | end_at | -end_at | Use `-` prefix for descending order. |
| id | id | -id | Use `-` prefix for descending order. |
| league_id | league_id | -league_id | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| season | season | -season | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| winner_id | winner_id | -winner_id | Use `-` prefix for descending order. |
| winner_type | winner_type | -winner_type | Use `-` prefix for descending order. |
| year | year | -year | Use `-` prefix for descending order. |

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
     --url 'https://api.pandascore.co/dota2/series/running' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 series

```json
[
  {
    "begin_at": "2025-01-12T21:00:00Z",
    "end_at": null,
    "full_name": "Raleigh: North America Open Qualifier 1 2025",
    "id": 8911,
    "league": {
      "id": 4114,
      "image_url": null,
      "modified_at": "2021-11-25T15:16:38Z",
      "name": "ESL One",
      "slug": "esl-one",
      "url": null
    },
    "league_id": 4114,
    "modified_at": "2025-01-12T22:42:15Z",
    "name": "Raleigh: North America Open Qualifier 1",
    "season": null,
    "slug": "esl-one-raleigh-north-america-open-qualifier-1-2025",
    "tournaments": [
      {
        "begin_at": "2025-01-12T21:00:00Z",
        "country": null,
        "detailed_stats": true,
        "end_at": null,
        "has_bracket": true,
        "id": 15768,
        "league_id": 4114,
        "live_supported": false,
        "modified_at": "2025-01-13T00:07:55Z",
        "name": "Playoffs",
        "prizepool": null,
        "region": "NA",
        "serie_id": 8911,
        "slug": "esl-one-raleigh-north-america-open-qualifier-1-2025-playoffs",
        "tier": "d",
        "type": "online",
        "winner_id": null,
        "winner_type": "Team"
      }
    ],
    "videogame": {
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    },
    "videogame_title": null,
    "winner_id": null,
    "winner_type": "Team",
    "year": 2025
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| begin_at | string; format: date-time | yes | — | minLength=1; nullable |
| end_at | string; format: date-time | yes | — | minLength=1; nullable |
| full_name | string | yes | — | — |
| id | integer | yes | — | minimum=1 |
| league | object | yes | — | — |
| league_id | integer | yes | — | minimum=1 |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | — | nullable |
| season | string | yes | — | nullable |
| slug | string | yes | — | minLength=1; pattern=^[a-z0-9_-]+$ |
| tournaments | array<object> | yes | — | — |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | yes | — | — |
| videogame_title | object | yes | — | nullable |
| winner_id | unknown | yes | — | nullable |
| winner_type | string; enum: Player, Team | yes | — | nullable |
| year | integer | yes | — | minimum=2012; nullable |

## Resource Relationships

| field | JSON type | endpoint-local description |
| --- | --- | --- |
| league | object | — |
| tournaments | array<object> | — |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | — |
| winner_id | unknown | — |

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:48.053113Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
