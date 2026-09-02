# get_dota2_matches

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** List Dota 2 matches
- **Method:** GET
- **API path:** `/dota2/matches`
- **Requested path:** `/dota2/matches`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_matches.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List matches for the Dota 2 videogame
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
| detailed_stats | boolean | Whether the match offers full stats | — |
| draw | boolean | Whether result of the match is a draw | — |
| end_at | array<string; format: date-time> | — | minItems=1 |
| finished | boolean | — | — |
| forfeit | boolean | Whether match was forfeited | — |
| future | boolean | `true` for future matches only, `false` for past matches only. Filtering is done on the `begin_at` value, so  matches with `running` status will not appear if `true`. | — |
| id | array<integer> | — | minItems=1 |
| league_id | array<integer> | — | minItems=1 |
| match_type | array<string; enum: all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground> | — | minItems=1 |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| not_started | boolean | — | — |
| number_of_games | array<integer> | — | minItems=1 |
| opponent_id | array<one of: one of: integer, string, one of: integer, string> | A Team or a Player (id or slug). You can use`filter[winner_type]=Team` or `filter[winner_type]=Player` to focus on teams or players. | minItems=1 |
| opponents_filled | boolean | Whether a match has opponents filled i.e. opponents are not TBD. | — |
| past | boolean | — | — |
| running | boolean | — | — |
| scheduled_at | array<string; format: date-time> | — | minItems=1 |
| serie_id | array<integer> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| status | array<string; enum: canceled, finished, not_started, postponed, running> | — | minItems=1 |
| tournament_id | array<integer> | — | minItems=1 |
| unscheduled | boolean | — | — |
| videogame | array<one of: integer; enum: 1, 3, 4, 14, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, string; enum: cod-mw, cs-go, dota-2, e-basketball, e-cricket, e-hockey, e-soccer, fifa, kog, league-of-legends, lol-wild-rift, mlbb, ow, pubg, r6-siege, rl, starcraft-2, starcraft-brood-war, valorant> | — | minItems=1 |
| videogame_title | array<one of: integer, string> | A videogame title id or slug. Only for `/csgo/*`, `/codmw/*`, `/fifa/*` and `/ow/*` endpoints | minItems=1 |
| videogame_version | array<one of: string, unknown; enum: all, unknown; enum: latest> | Filter by the names of videogame versions, all versions using `filter[videogame_version]=all`, or by the latest version using `filter[videogame_version]=latest` Only for `valorant/*` and `/lol/*` endpoints. | minItems=1 |
| winner_id | array<unknown> | — | minItems=1 |
| winner_type | array<string; enum: Player, Team> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| match_type | string; enum: all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground | — | — |
| name | string | — | — |
| slug | string | — | minLength=1; pattern=^[ a-zA-Z0-9_-]+$ |
| status | string; enum: canceled, finished, not_started, postponed, running | — | — |
| winner_type | string; enum: Player, Team | — | — |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| begin_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| detailed_stats | array<boolean> | — | minItems=2; maxItems=2 |
| draw | array<boolean> | — | minItems=2; maxItems=2 |
| end_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| forfeit | array<boolean> | — | minItems=2; maxItems=2 |
| id | array<integer> | — | minItems=2; maxItems=2 |
| match_type | array<string; enum: all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| number_of_games | array<integer> | — | minItems=2; maxItems=2 |
| scheduled_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |
| status | array<string; enum: canceled, finished, not_started, postponed, running> | — | minItems=2; maxItems=2 |
| tournament_id | array<integer> | — | minItems=2; maxItems=2 |
| winner_id | array<unknown> | — | minItems=2; maxItems=2 |
| winner_type | array<string; enum: Player, Team> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| begin_at | begin_at | -begin_at | Use `-` prefix for descending order. |
| detailed_stats | detailed_stats | -detailed_stats | Use `-` prefix for descending order. |
| draw | draw | -draw | Use `-` prefix for descending order. |
| end_at | end_at | -end_at | Use `-` prefix for descending order. |
| forfeit | forfeit | -forfeit | Use `-` prefix for descending order. |
| id | id | -id | Use `-` prefix for descending order. |
| match_type | match_type | -match_type | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| number_of_games | number_of_games | -number_of_games | Use `-` prefix for descending order. |
| scheduled_at | scheduled_at | -scheduled_at | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| status | status | -status | Use `-` prefix for descending order. |
| tournament_id | tournament_id | -tournament_id | Use `-` prefix for descending order. |
| winner_id | winner_id | -winner_id | Use `-` prefix for descending order. |
| winner_type | winner_type | -winner_type | Use `-` prefix for descending order. |

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
     --url 'https://api.pandascore.co/dota2/matches' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 matches

```json
[
  {
    "begin_at": "2025-10-04T17:00:37Z",
    "detailed_stats": true,
    "draw": false,
    "end_at": "2025-10-04T21:26:39Z",
    "forfeit": false,
    "game_advantage": null,
    "games": [
      {
        "begin_at": "2025-10-04T17:00:37Z",
        "complete": true,
        "detailed_stats": true,
        "end_at": "2025-10-04T17:29:56Z",
        "finished": true,
        "forfeit": false,
        "id": 728640,
        "length": 1619,
        "match_id": 1249621,
        "position": 1,
        "status": "finished",
        "winner": {
          "id": 137002,
          "type": "Team"
        },
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-04T17:30:00Z",
        "complete": true,
        "detailed_stats": true,
        "end_at": "2025-10-04T17:57:14Z",
        "finished": true,
        "forfeit": false,
        "id": 728641,
        "length": 2613,
        "match_id": 1249621,
        "position": 2,
        "status": "finished",
        "winner": {
          "id": 134208,
          "type": "Team"
        },
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-04T18:12:52Z",
        "complete": true,
        "detailed_stats": true,
        "end_at": "2025-10-04T19:13:50Z",
        "finished": true,
        "forfeit": false,
        "id": 728642,
        "length": 2928,
        "match_id": 1249621,
        "position": 3,
        "status": "finished",
        "winner": {
          "id": 134208,
          "type": "Team"
        },
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-04T19:31:01Z",
        "complete": true,
        "detailed_stats": true,
        "end_at": "2025-10-04T20:16:02Z",
        "finished": true,
        "forfeit": false,
        "id": 728643,
        "length": 2122,
        "match_id": 1249621,
        "position": 4,
        "status": "finished",
        "winner": {
          "id": 137002,
          "type": "Team"
        },
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-04T20:34:01Z",
        "complete": true,
        "detailed_stats": true,
        "end_at": "2025-10-04T21:26:39Z",
        "finished": true,
        "forfeit": false,
        "id": 728644,
        "length": 2645,
        "match_id": 1249621,
        "position": 5,
        "status": "finished",
        "winner": {
          "id": 134208,
          "type": "Team"
        },
        "winner_type": "Team"
      }
    ],
    "id": 1249621,
    "league": {
      "id": 4807,
      "image_url": "https://cdn.pandascore.co/images/league/image/4807/799px-european_pro_league_2023_lightmode-png",
      "modified_at": "2023-12-23T22:10:19Z",
      "name": "European Pro League",
      "slug": "dota-2-european-pro-league",
      "url": null
    },
    "league_id": 4807,
    "live": {
      "opens_at": null,
      "supported": false,
      "url": null
    },
    "match_type": "best_of",
    "modified_at": "2025-10-04T21:36:30Z",
    "name": "Grand final: KALMY vs ES",
    "number_of_games": 5,
    "opponents": [
      {
        "opponent": {
          "acronym": "KALMY",
          "dark_mode_image_url": "https://cdn.pandascore.co/dark_images/team/dark_image/134208/262px_kalmychata_2025_darkmode.png",
          "id": 134208,
          "image_url": "https://cdn.pandascore.co/images/team/image/134208/262px_kalmychata_2025_lightmode.png",
          "location": "RU",
          "modified_at": "2025-09-29T21:53:57Z",
          "name": "Kalmychata",
          "slug": "kalmychata"
        },
        "type": "Team"
      },
      {
        "opponent": {
          "acronym": "ES",
          "dark_mode_image_url": null,
          "id": 137002,
          "image_url": "https://cdn.pandascore.co/images/team/image/137002/119px_e_spoiled_allmode.png",
          "location": "",
          "modified_at": "2025-10-04T17:30:15Z",
          "name": "eSpoiled",
          "slug": "espoiled"
        },
        "type": "Team"
      }
    ],
    "original_scheduled_at": "2025-10-04T16:00:00Z",
    "rescheduled": false,
    "results": [
      {
        "score": 3,
        "team_id": 134208
      },
      {
        "score": 2,
        "team_id": 137002
      }
    ],
    "scheduled_at": "2025-10-04T16:00:00Z",
    "serie": {
      "begin_at": "2025-09-08T12:00:00Z",
      "end_at": "2025-10-05T19:00:00Z",
      "full_name": "Season 30 2025",
      "id": 9663,
      "league_id": 4807,
      "modified_at": "2025-09-26T17:06:51Z",
      "name": "",
      "season": "30",
      "slug": "dota-2-european-pro-league-30-2025",
      "winner_id": null,
      "winner_type": "Team",
      "year": 2025
    },
    "serie_id": 9663,
    "slug": "kalmychata-vs-espoiled-2025-10-04",
    "status": "finished",
    "streams_list": [
      {
        "embed_url": null,
        "language": "en",
        "main": true,
        "official": true,
        "raw_url": "https://kick.com/epldota_en2"
      },
      {
        "embed_url": "https://player.twitch.tv/?channel=epl_dota",
        "language": "ru",
        "main": false,
        "official": false,
        "raw_url": "https://www.twitch.tv/epl_dota"
      }
    ],
    "tournament": {
      "begin_at": "2025-09-26T18:00:00Z",
      "country": null,
      "detailed_stats": true,
      "end_at": "2025-10-04T21:26:00Z",
      "has_bracket": true,
      "id": 17691,
      "league_id": 4807,
      "live_supported": false,
      "modified_at": "2025-10-05T06:29:49Z",
      "name": "Playoffs",
      "prizepool": null,
      "region": "WEU",
      "serie_id": 9663,
      "slug": "dota-2-european-pro-league-30-2025-playoffs",
      "tier": "d",
      "type": "online",
      "winner_id": 134208,
      "winner_type": "Team"
    },
    "tournament_id": 17691,
    "videogame": {
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    },
    "videogame_title": null,
    "videogame_version": null,
    "winner": {
      "acronym": "KALMY",
      "dark_mode_image_url": "https://cdn.pandascore.co/dark_images/team/dark_image/134208/262px_kalmychata_2025_darkmode.png",
      "id": 134208,
      "image_url": "https://cdn.pandascore.co/images/team/image/134208/262px_kalmychata_2025_lightmode.png",
      "location": "RU",
      "modified_at": "2025-09-29T21:53:57Z",
      "name": "Kalmychata",
      "slug": "kalmychata"
    },
    "winner_id": 134208,
    "winner_type": "Team"
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| begin_at | string; format: date-time | yes | — | minLength=1; nullable |
| detailed_stats | boolean | yes | Whether the match offers full stats | — |
| draw | boolean | yes | Whether result of the match is a draw | — |
| end_at | string; format: date-time | yes | — | minLength=1; nullable |
| forfeit | boolean | yes | Whether match was forfeited | — |
| game_advantage | integer | yes | ID of the opponent with a game advantage | minimum=1; nullable |
| games | array<object> | yes | — | — |
| id | integer | yes | — | minimum=1 |
| league | object | yes | — | — |
| league_id | integer | yes | — | minimum=1 |
| live | object | yes | — | — |
| map_picks | array<object> | no | **Only applies to Valorant matches. The field will not be present on other video games matches.** Map picks, `null` when map picks data is unavailable. **Important:** `map_picks` field is only present in the response for subscribers of Valorant Historical plan. | nullable |
| match_type | string; enum: all_games_played, best_of, custom, first_to, ow_best_of, red_bull_home_ground | yes | — | — |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | — | — |
| number_of_games | integer | yes | Number of games | minimum=0 |
| opponents | array<object> | yes | — | — |
| original_scheduled_at | string; format: date-time | yes | — | minLength=1; nullable |
| rescheduled | boolean | yes | Whether match has been rescheduled | nullable |
| results | array<unknown> | yes | — | — |
| scheduled_at | string; format: date-time | yes | — | minLength=1; nullable |
| serie | object | yes | — | — |
| serie_id | integer | yes | — | minimum=1 |
| slug | string | yes | — | minLength=1; pattern=^[ a-zA-Z0-9_-]+$; nullable |
| status | string; enum: canceled, finished, not_started, postponed, running | yes | — | — |
| streams_list | array<object> | yes | — | — |
| tournament | object | yes | — | — |
| tournament_id | integer | yes | — | minimum=1 |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | yes | — | — |
| videogame_title | object | yes | — | nullable |
| videogame_version | object | yes | — | nullable |
| winner | one of: object, object | yes | — | nullable |
| winner_id | unknown | yes | — | nullable |
| winner_type | string; enum: Player, Team | yes | — | — |

## Resource Relationships

| field | JSON type | endpoint-local description |
| --- | --- | --- |
| games | array<object> | — |
| league | object | — |
| opponents | array<object> | — |
| serie | object | — |
| streams_list | array<object> | — |
| tournament | object | — |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | — |
| winner | one of: object, object | — |
| winner_id | unknown | — |

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:38.355975Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
