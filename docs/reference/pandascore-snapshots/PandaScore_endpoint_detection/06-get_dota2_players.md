# get_dota2_players

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** List Dota 2 players
- **Method:** GET
- **API path:** `/dota2/players`
- **Requested path:** `/dota2/players`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_players.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List players for the Dota 2 videogame
> ℹ️  
> 
> This endpoint is available to all customers

## Path Parameters

None documented.

## Query Parameters

### filter

| field | type | description | constraints |
| --- | --- | --- | --- |
| active | boolean | Whether player is active | — |
| birthday | array<string> | — | minItems=1 |
| first_name | array<string> | — | minItems=1 |
| id | array<integer> | — | minItems=1 |
| last_name | array<string> | — | minItems=1 |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| nationality | array<string> | — | minItems=1 |
| role | array<string> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| team_id | array<integer> | — | minItems=1 |
| videogame_id | array<integer; enum: 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| birthday | string | Birth day of the player, `YYYY-MM-DD` format. `null` if unknown. **Note**: This field is only present for users running the Historical plan or above. | — |
| first_name | string | First name of the player. `null` if unknown | — |
| last_name | string | Last name of the player. `null` if unknown | — |
| name | string | Professional name of the player | — |
| nationality | string | Country code matching the nationality of the player according to the ISO 3166-1 standard (Alpha-2 code). In addition to the standard, the `XK` code is used for Kosovo. `null` if unknown | — |
| role | string | Role/position of the player. Field value varies depending on the video game.`null` if unknown. **Note**: role is only available for DotA 2, League of Legends, and Overwatch players. `null` for other video games. | — |
| slug | string | Unique, human-readable identifier for the player. `id` and `slug` can be used interchangeably throughout the API. | minLength=1; pattern=^[a-z0-9_-]+$ |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| birthday | array<string> | — | minItems=2; maxItems=2 |
| first_name | array<string> | — | minItems=2; maxItems=2 |
| id | array<integer> | — | minItems=2; maxItems=2 |
| last_name | array<string> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| nationality | array<string> | — | minItems=2; maxItems=2 |
| role | array<string> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| birthday | birthday | -birthday | Use `-` prefix for descending order. |
| first_name | first_name | -first_name | Use `-` prefix for descending order. |
| id | id | -id | Use `-` prefix for descending order. |
| last_name | last_name | -last_name | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| nationality | nationality | -nationality | Use `-` prefix for descending order. |
| role | role | -role | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| videogame_id | videogame_id | -videogame_id | Use `-` prefix for descending order. |
| team_id | team_id | -team_id | Use `-` prefix for descending order. |

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
     --url 'https://api.pandascore.co/dota2/players' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 players

```json
[
  {
    "active": true,
    "age": null,
    "birthday": null,
    "current_team": {
      "acronym": "NAVI.J",
      "dark_mode_image_url": null,
      "id": 132308,
      "image_url": "https://cdn.pandascore.co/images/team/image/132308/593px_natus_vincere_junior_2021_lightmode.png",
      "location": "UA",
      "modified_at": "2025-10-03T12:34:01Z",
      "name": "NAVI Junior",
      "slug": "navi-junior"
    },
    "current_videogame": {
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    },
    "first_name": null,
    "id": 62075,
    "image_url": null,
    "last_name": null,
    "modified_at": "2025-10-03T12:49:42Z",
    "name": "Gothic-",
    "nationality": null,
    "role": "4",
    "slug": "gothic"
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| active | boolean | yes | Whether player is active | — |
| age | number | no | Age of the player, `null` if unknown. When `birthday` is `null`, `age` is an approxiamation. Read more about [players' age](/docs/about-players-age) **Note**: This field is only present for users running the Historical plan or above. | minimum=0; nullable |
| birthday | string | no | Birth day of the player, `YYYY-MM-DD` format. `null` if unknown. **Note**: This field is only present for users running the Historical plan or above. | nullable |
| current_team | object | yes | — | nullable |
| current_videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | yes | — | nullable |
| first_name | string | yes | First name of the player. `null` if unknown | nullable |
| id | integer | yes | ID of the player | minimum=1 |
| image_url | string; format: uri | yes | URL to the photo of the player. `null` if not available. | nullable |
| last_name | string | yes | Last name of the player. `null` if unknown | nullable |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | Professional name of the player | — |
| nationality | string | yes | Country code matching the nationality of the player according to the ISO 3166-1 standard (Alpha-2 code). In addition to the standard, the `XK` code is used for Kosovo. `null` if unknown | nullable |
| role | string | yes | Role/position of the player. Field value varies depending on the video game.`null` if unknown. **Note**: role is only available for DotA 2, League of Legends, and Overwatch players. `null` for other video games. | nullable |
| slug | string | yes | Unique, human-readable identifier for the player. `id` and `slug` can be used interchangeably throughout the API. | minLength=1; pattern=^[a-z0-9_-]+$; nullable |

## Resource Relationships

None documented.

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:44.507759Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
